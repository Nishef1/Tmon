"""Gaps in the stored data are counted, noted once and closed when a refill fills them."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from tmon.core.timeutil import utcnow
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily
from tmon.storage.objectstore import MemoryStore
from tmon.tools import data_health as dh

DAYS = [dt.date(2026, 11, 1) + dt.timedelta(days=k) for k in range(14)]
# Saturday 14 Aban 1405 (2026-11-14): after the close, prices not stored yet -> pending.
EVENING = dt.datetime(2026, 11, 14, 17, 0, tzinfo=dt.UTC)  # 20:30 Tehran


def _fill(session: Session, per_day: dict[dt.date, int], flows: bool = True) -> None:
    n = max(per_day.values())
    for i in range(n):
        session.add(
            Instrument(id=i + 1, ins_code=f"c{i}", symbol_fa=f"س{i}", instrument_type="stock")
        )
    session.flush()
    for d, k in per_day.items():
        for i in range(k):
            session.add(
                PriceDaily(instrument_id=i + 1, date=d, close=100, volume=10, market_halt=False)
            )
            if flows:
                session.add(ClientTypeDaily(instrument_id=i + 1, date=d))
    session.commit()


def _state(store: MemoryStore, now: dt.datetime | None = None) -> str:
    doc = dh.refill_state(store, now)
    assert doc is not None
    return str(doc["state"])


def test_a_half_filled_day_is_named_with_both_numbers(session: Session) -> None:
    _fill(session, {d: (60 if d == DAYS[-1] else 100) for d in DAYS})
    r = dh.check(session, EVENING)
    kinds = {(i.kind, i.date): (i.have, i.expected) for i in r["issues"]}
    assert kinds[("prices_partial", DAYS[-1])] == (60, 100)
    assert kinds[("flows_partial", DAYS[-1])] == (60, 100)
    assert not any(i.date == DAYS[-2] for i in r["issues"])


def test_complete_days_report_nothing(session: Session) -> None:
    _fill(session, dict.fromkeys(DAYS, 50))
    assert dh.check(session, dt.datetime(2026, 11, 14, 5, 0, tzinfo=dt.UTC))["issues"] == []


def test_today_is_pending_only_after_the_close_on_a_trading_day(session: Session) -> None:
    _fill(session, dict.fromkeys(DAYS[:-1], 50))  # newest stored day is 13 Nov

    def pending(now: dt.datetime) -> list[str]:
        return [i.kind for i in dh.check(session, now)["issues"]]

    assert pending(EVENING) == ["today_pending"]
    assert pending(dt.datetime(2026, 11, 14, 6, 0, tzinfo=dt.UTC)) == []  # 09:30, market open
    friday = dt.datetime(2026, 11, 20, 17, 0, tzinfo=dt.UTC)
    assert "today_pending" not in pending(friday)  # Friday is a day off


def test_note_keeps_first_seen_and_closes_a_healed_gap(session: Session) -> None:
    store = MemoryStore()
    _fill(session, {d: (60 if d == DAYS[-1] else 100) for d in DAYS})
    first = dh.record(session, store, EVENING)
    gap = next(g for g in first["gaps"] if g["kind"] == "prices_partial")
    assert gap["first_seen"] == "2026-11-14" and gap["closed_on"] is None
    later = dh.record(session, store, EVENING + dt.timedelta(days=1))
    assert (
        next(g for g in later["gaps"] if g["kind"] == "prices_partial")["first_seen"]
        == "2026-11-14"
    )
    for i in range(60, 100):  # the refill brings the missing rows
        session.add(
            PriceDaily(instrument_id=i + 1, date=DAYS[-1], close=100, volume=10, market_halt=False)
        )
        session.add(ClientTypeDaily(instrument_id=i + 1, date=DAYS[-1]))
    session.commit()
    done = dh.record(session, store, EVENING + dt.timedelta(days=2))
    assert all(
        g["closed_on"] == "2026-11-16" for g in done["gaps"] if g["kind"].endswith("partial")
    )


def test_refill_skips_what_this_machine_cannot_reach_and_says_so(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable, Iterator
    from contextlib import contextmanager

    store = MemoryStore()
    _fill(session, dict.fromkeys(DAYS, 50))

    @contextmanager
    def scope() -> Iterator[Session]:
        yield session

    monkeypatch.setattr("tmon.core.db.session_scope", scope)
    ran: list[str] = []

    def step(name: str) -> Callable[[], str]:
        def run() -> str:
            ran.append(name)
            return "ok"

        return run

    res = dh.run_refill(
        store,
        {"history": step("history"), "indices": step("indices")},
        here=lambda: {"history": False, "instruments": False, "cdn": True},
    )
    assert ran == ["indices"]
    by = {s["name"]: s["status"] for s in res["steps"]}
    assert by == {"history": "skipped", "indices": "ok"}
    assert _state(store) == "done"


def test_a_dead_running_job_is_reported_failed(session: Session) -> None:
    store = MemoryStore()
    old = dt.datetime(2026, 11, 14, 10, 0, tzinfo=dt.UTC)
    dh._set(store, {"state": "running", "started_at": old.isoformat(), "steps": []})
    assert _state(store, old + dt.timedelta(minutes=10)) == "running"
    assert _state(store, old + dt.timedelta(hours=2)) == "failed"


def test_endpoint_reports_gap_and_refill_does_not_start_twice(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from tmon.api.main import create_app
    from tmon.core.db import get_session

    store = MemoryStore()
    monkeypatch.setattr(dh, "get_object_store", lambda: store)
    started: list[int] = []
    monkeypatch.setattr(dh, "start_in_background", lambda: started.append(1))
    _fill(session, {d: (60 if d == DAYS[-1] else 100) for d in DAYS})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        h = c.get("/data-health").json()
        assert h["complete"] is False
        assert any(
            i["kind"] == "prices_partial" and (i["have"], i["expected"]) == (60, 100)
            for i in h["issues"]
        )
        assert c.post("/data-health/refill").json()["state"] == "running"
        dh._set(store, {"state": "running", "started_at": utcnow().isoformat(), "steps": []})
        assert c.post("/data-health/refill").json()["state"] == "running"
    assert started == [1]


def test_refill_waits_while_the_daily_cycle_runs(session: Session) -> None:
    store = MemoryStore()
    now = dt.datetime(2026, 11, 14, 17, 0, tzinfo=dt.UTC)
    assert not dh.cycle_running(store, now)
    dh.mark_cycle(True, store)
    assert dh.cycle_running(store)
    res = dh.run_refill(store, {}, here=lambda: {})
    assert res["state"] == "blocked"
    dh.mark_cycle(False, store)
    assert not dh.cycle_running(store)
    stale = utcnow() - dt.timedelta(hours=dh.CYCLE_MAX_HOURS + 1)
    dh._write(store, dh.CYCLE_KEY, {"running": True, "at": stale.isoformat()})
    assert not dh.cycle_running(store)  # a crashed cycle must not block forever


def test_cycle_timings_keep_the_last_cycles_newest_first() -> None:
    from tmon.tasks.cycle import Step, run_cycle

    store = MemoryStore()
    seen = []

    def boom() -> None:
        raise ValueError("x")

    steps = [Step("a", lambda: 1), Step("b", boom, required=False), Step("c", lambda: 2)]
    run_cycle(dt.date(2026, 11, 15), steps, seen.append)
    assert [(r.name, r.ok) for r in seen] == [("a", True), ("b", False), ("c", True)]

    started = dt.datetime(2026, 11, 15, 16, 0, tzinfo=dt.UTC)
    rows = [{"name": r.name, "ok": r.ok, "seconds": r.seconds, "detail": r.detail} for r in seen]
    for n in range(dh.TIMINGS_KEEP + 3):
        day = dt.date(2026, 10, 1) + dt.timedelta(days=n)
        dh.record_timings(day, rows, ok=True, full=n % 7 == 0, started_at=started, store=store)
    dh.record_timings(
        dt.date(2026, 10, 1), rows, ok=False, full=False, started_at=started, store=store
    )

    cycles = dh.read_timings(store)
    assert len(cycles) == dh.TIMINGS_KEEP
    assert (
        cycles[0]["day"] == "2026-10-01" and cycles[0]["ok"] is False
    )  # a re-run replaces its day
    assert cycles[1]["day"] == "2026-11-02"
    assert [s["name"] for s in cycles[0]["steps"]] == ["a", "b", "c"]
    assert cycles[0]["eod_mode"] == "fast"


def test_timings_never_raise_when_the_store_is_broken() -> None:
    class Broken(MemoryStore):
        def put(self, *a, **k):  # type: ignore[no-untyped-def]
            raise OSError("disk full")

    dh.record_timings(
        dt.date(2026, 11, 15), [], ok=True, full=False, started_at=utcnow(), store=Broken()
    )


def test_full_refresh_runs_on_wednesday_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from tmon.tasks.cycle import eod_full_today

    monkeypatch.delenv("TMON_EOD_FULL", raising=False)
    wed = dt.datetime(2026, 11, 18, 16, 0, tzinfo=dt.UTC)  # Wednesday 19:30 Tehran
    assert eod_full_today(wed)
    assert not eod_full_today(wed + dt.timedelta(days=-1))
    monkeypatch.setenv("TMON_EOD_FULL", "1")
    assert eod_full_today(wed + dt.timedelta(days=-1))
