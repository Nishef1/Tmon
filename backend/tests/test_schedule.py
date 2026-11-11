"""The daily cycle: when it is due (derived from market_rules), that it runs once per day, retries
a failed run a bounded number of times and survives a failing optional step."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from tmon.core.timeutil import TEHRAN
from tmon.storage.seed import seed_rulebook
from tmon.tasks.cycle import CycleFailedError, Step, claim, run_cycle, tick
from tmon.tasks.schedule import cycle_decision, cycle_due_at, is_schedule_day, session_close

RULES = seed_rulebook()
DAYS = "sat,sun,mon,tue,wed"
WED = date(2026, 11, 11)  # a Wednesday
THU = date(2026, 11, 12)


def _at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TEHRAN)


class FakeKV:
    """The few Redis calls the claim uses, with Redis' NX semantics."""

    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def set(self, name, value, *, nx=False, ex=None):
        if nx and name in self.d:
            return None
        self.d[name] = value
        return True

    def exists(self, name):
        return int(name in self.d)

    def incr(self, name):
        self.d[name] = str(int(self.d.get(name, "0")) + 1)
        return int(self.d[name])

    def expire(self, name, time):
        return True

    def delete(self, name):
        return int(self.d.pop(name, None) is not None)


def test_due_time_comes_from_the_rules_not_from_code():
    # the closing session (13:00) is the last one while that rule is valid, then + the delay
    assert session_close(RULES, WED) == time(13, 0)
    assert cycle_due_at(RULES, WED, 30) == _at(WED, 13, 30)
    assert cycle_due_at(RULES, WED, 0) == _at(WED, 13, 0)


def test_only_configured_weekdays_are_scheduled_in_tehran_time():
    assert is_schedule_day(_at(WED, 14, 0), DAYS)
    assert not is_schedule_day(_at(THU, 14, 0), DAYS)
    # 22:00 UTC on Wednesday is already Thursday in Tehran (UTC+03:30)
    assert not is_schedule_day(datetime(2026, 11, 11, 22, 0, tzinfo=UTC), DAYS)
    assert is_schedule_day(datetime(2026, 11, 14, 8, 0, tzinfo=UTC), DAYS)  # Saturday


def test_not_due_before_the_delay_has_passed_and_due_after():
    due, why = cycle_decision(RULES, _at(WED, 13, 29), schedule_days=DAYS, delay_minutes=30)
    assert not due and "13:30" in why
    due, why = cycle_decision(RULES, _at(WED, 13, 30), schedule_days=DAYS, delay_minutes=30)
    assert due and "13:30" in why
    assert cycle_decision(RULES, _at(THU, 15, 0), schedule_days=DAYS, delay_minutes=30)[0] is False


def _ok(log: list[str], name: str, required: bool = True) -> Step:
    return Step(name, lambda: log.append(name) or name, required)


def _boom() -> None:
    raise RuntimeError("tsetmc timed out")


def _tick(kv, steps, now, attempts=3):
    return tick(
        kv, RULES, steps, now=now, schedule_days=DAYS, delay_minutes=30, max_attempts=attempts
    )


def test_cycle_runs_once_per_day_even_with_many_ticks():
    kv, log = FakeKV(), []
    steps = [_ok(log, "ingest"), _ok(log, "features"), _ok(log, "publish")]
    assert _tick(kv, steps, _at(WED, 13, 10)).startswith("skip")
    assert _tick(kv, steps, _at(WED, 13, 30)) == "complete"
    assert log == ["ingest", "features", "publish"]  # in order
    for minute in (35, 40, 55):
        assert _tick(kv, steps, _at(WED, 13, minute)) == "skip: done"
    assert log == ["ingest", "features", "publish"]  # not repeated
    # the next scheduled day runs again
    assert _tick(kv, steps, _at(date(2026, 11, 14), 13, 31)) == "complete"  # Saturday


def test_a_running_cycle_is_not_started_twice():
    kv = FakeKV()
    assert claim(kv, WED, 3) == "claimed"
    assert claim(kv, WED, 3) == "running"  # a second tick while the first still runs


def test_failed_required_step_releases_the_claim_and_retries_are_bounded():
    kv, log = FakeKV(), []
    steps = [_ok(log, "ingest"), Step("features", _boom), _ok(log, "publish")]
    first = _tick(kv, steps, _at(WED, 13, 30), attempts=2)
    assert first.startswith("failed: features") and log == ["ingest"]  # publish never ran
    assert _tick(kv, steps, _at(WED, 13, 35), attempts=2).startswith("failed")  # retried
    assert _tick(kv, steps, _at(WED, 13, 40), attempts=2) == "skip: gave_up"  # then stops
    # a good run after a failure still completes the day
    kv2 = FakeKV()
    assert _tick(kv2, steps, _at(WED, 13, 30)).startswith("failed")
    good = [_ok(log, "ingest"), _ok(log, "features"), _ok(log, "publish")]
    assert _tick(kv2, good, _at(WED, 13, 35)) == "complete"


def test_optional_step_failure_is_logged_and_skipped():
    log: list[str] = []
    steps = [_ok(log, "ingest"), Step("indices", _boom, required=False), _ok(log, "features")]
    res = run_cycle(WED, steps)
    assert [r.ok for r in res] == [True, False, True] and log == ["ingest", "features"]
    with pytest.raises(CycleFailedError):
        run_cycle(WED, [Step("ingest", _boom)])
