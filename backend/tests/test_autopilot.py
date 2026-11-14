"""The autopilot: regime reading, what counts as an event, when the deep study is due."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from tmon.engine import regime
from tmon.tools import adapt_cycle, autopilot


def _series(returns: list[float], start: float = 100.0) -> tuple[list[date], list[float]]:
    v = [start]
    for r in returns:
        v.append(v[-1] * (1 + r))
    d0 = date(2022, 1, 1)
    return [d0 + timedelta(days=i) for i in range(len(v))], v


def _read(returns: list[float]) -> dict[str, Any]:
    d, v = _series(returns)
    out = regime.summarize(d, v, stress_days=120, stress_drawdown=0.2)
    assert out is not None
    return out


def test_a_steadily_rising_index_is_calm_and_bullish_only() -> None:
    r = _read([0.001] * 1100)
    assert r["stress"] is False and r["bullish_only"] is True and r["bear_windows"] == 0


def test_a_deep_fall_from_the_peak_is_stress() -> None:
    r = _read([0.002] * 800 + [-0.004] * 100)  # peak, then about -33%
    assert r["stress"] is True and r["drawdown"] > 0.2


def test_a_lost_year_makes_the_history_not_bullish_only() -> None:
    r = _read([0.003] * 600 + [-0.0008] * 250 + [0.003] * 250)  # one window below -10%
    assert r["bear_windows"] >= 1 and r["bullish_only"] is False


def test_a_series_that_is_too_short_gives_no_reading() -> None:
    d, v = _series([0.001] * 100)
    assert regime.summarize(d, v, stress_days=120, stress_drawdown=0.2) is None


def test_bad_index_values_are_ignored_not_trusted() -> None:
    d, v = _series([0.001] * 1100)
    v[500] = float("nan")
    v[600] = 0.0
    assert regime.summarize(d, v, stress_days=120, stress_drawdown=0.2) is not None


def test_regime_changed_is_the_stress_flag_flipping() -> None:
    calm = {"regime": {"stress": False}}
    assert adapt_cycle.regime_changed(calm, {"stress": True})
    assert not adapt_cycle.regime_changed(calm, {"stress": False})
    assert adapt_cycle.regime_changed(None, {"stress": False})  # first reading: look once
    assert not adapt_cycle.regime_changed(calm, None)  # no index: no reason to redo anything


def _state(as_of: str, champions: dict[str, str], stress: bool = False) -> dict[str, Any]:
    return {
        "as_of": as_of,
        "horizons": {h: {"champion": c} for h, c in champions.items()},
        "regime": {"stress": stress, "bullish_only": not stress},
    }


def _deep(last: str, passed: tuple[str, ...] = ()) -> dict[str, Any]:
    cells = {m.split("@")[0]: {"gate": {"passed": True}} for m in passed}
    return {"last": last, "results": {"5": {"equal": {"gate": None}, **cells}}}


def _assess(
    state: dict[str, Any],
    deep: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
    can_run: bool = True,
) -> dict[str, Any]:
    return autopilot.assess(
        state, deep, previous, checked_at="2026-11-14T10:00:00", refresh_days=28, can_run=can_run
    )


def test_a_fresh_study_is_not_due_and_an_old_one_is() -> None:
    s = _state("2026-11-14", {"5": "equal"})
    fresh = _assess(s, _deep("2026-11-10"))
    assert fresh["deep"]["due"] is False and fresh["deep"]["age_days"] == 4
    old = _assess(s, _deep("2026-10-01"))
    assert old["deep"]["due"] is True and old["deep"]["reason"] == autopilot.OLD
    assert _assess(s, None)["deep"]["reason"] == autopilot.NO_STUDY


def test_a_champion_change_and_a_regime_flip_are_events() -> None:
    first = _assess(_state("2026-11-13", {"5": "equal"}), _deep("2026-11-10"))
    assert first["events"] == []  # nothing to compare with yet
    second = _assess(
        _state("2026-11-14", {"5": "ridge4_x120"}, stress=True), _deep("2026-11-10"), first
    )
    kinds = {e["kind"] for e in second["events"]}
    assert kinds == {"champion", "regime"}
    champ = next(e for e in second["events"] if e["kind"] == "champion")
    assert (champ["horizon"], champ["before"], champ["after"]) == (5, "equal", "ridge4_x120")


def test_a_regime_flip_makes_an_otherwise_fresh_study_due_until_it_is_redone() -> None:
    calm = _assess(_state("2026-11-13", {"5": "equal"}), _deep("2026-11-12"))
    flipped = _assess(_state("2026-11-14", {"5": "equal"}, stress=True), _deep("2026-11-12"), calm)
    assert flipped["deep"]["due"] and flipped["deep"]["reason"] == autopilot.REGIME
    again = _assess(_state("2026-11-15", {"5": "equal"}, stress=True), _deep("2026-11-12"), flipped)
    assert again["deep"]["due"], "still due: the study predates the flip"
    redone = _assess(_state("2026-11-16", {"5": "equal"}, stress=True), _deep("2026-11-16"), again)
    assert not redone["deep"]["due"] and redone["forced_since"] is None


def test_a_new_study_is_an_event_with_who_passed_and_who_was_lost() -> None:
    base = _assess(_state("2026-11-14", {"5": "equal"}), _deep("2026-10-01", ("gbm@5",)))
    after = _assess(_state("2026-12-20", {"5": "equal"}), _deep("2026-12-19", ("gru@5",)), base)
    by_kind = {e["kind"]: e for e in after["events"]}
    assert by_kind["deep_refreshed"]["passed"] == ["gru@5"]
    assert by_kind["deep_passed"]["methods"] == ["gru@5"]
    assert by_kind["deep_lost"]["methods"] == ["gbm@5"]


def test_events_are_capped() -> None:
    prev: dict[str, Any] = {
        "champions": {"5": "equal"},
        "regime": {"stress": False},
        "deep": {"last": "2026-11-01", "passed": []},
        "events": [{"at": "2026-01-01", "kind": "champion"}] * autopilot.EVENTS_KEEP,
    }
    out = _assess(_state("2026-11-14", {"5": "gbm"}), _deep("2026-11-10"), prev)
    assert len(out["events"]) == autopilot.EVENTS_KEEP and any(
        e.get("after") == "gbm" for e in out["events"]
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(autopilot, "_load", lambda key: docs.get(key))
    monkeypatch.setattr(autopilot, "_store", lambda doc: docs.__setitem__(autopilot.KEY, doc))
    monkeypatch.setattr(adapt_cycle, "load_state", lambda: docs.get("state"))
    return docs


def test_run_without_a_state_does_nothing(store: dict[str, dict[str, Any]]) -> None:
    assert "skipped" in autopilot.run()
    assert autopilot.KEY not in store


def test_run_without_torch_records_that_the_study_is_old_and_does_not_start_it(
    store: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    store["state"] = _state("2026-11-14", {"5": "equal"})
    store[autopilot.DEEP_KEY] = _deep("2026-09-01")
    monkeypatch.setattr(autopilot, "torch_available", lambda: False)
    started: list[int] = []
    monkeypatch.setattr(autopilot, "_run_deep_study", lambda: started.append(1))
    autopilot.run(refresh_deep=True)
    autopilot.run(refresh_deep=True)  # the same data date: still one event
    doc = store[autopilot.KEY]
    assert started == [] and doc["deep"]["due"] and doc["deep"]["can_run"] is False
    assert [e["kind"] for e in doc["events"]].count("deep_skipped") == 1


def test_run_with_torch_redoes_the_study_and_the_page_data_follows(
    store: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    store["state"] = _state("2026-11-14", {"5": "equal"})
    store[autopilot.DEEP_KEY] = _deep("2026-09-01")
    monkeypatch.setattr(autopilot, "torch_available", lambda: True)

    def redo() -> None:
        store[autopilot.DEEP_KEY] = _deep("2026-11-14", ("gbm@5",))

    monkeypatch.setattr(autopilot, "_run_deep_study", redo)
    autopilot.run()  # the cheap daily check never starts the study
    assert store[autopilot.KEY]["deep"]["due"]
    autopilot.run(refresh_deep=True)
    doc = store[autopilot.KEY]
    assert doc["deep"]["due"] is False and doc["deep"]["passed"] == ["gbm@5"]
    assert "deep_refreshed" in {e["kind"] for e in doc["events"]}


def test_the_daily_cycle_has_an_optional_autopilot_step_after_adapt() -> None:
    from tmon.tasks.cycle import default_steps

    names = [s.name for s in default_steps(("1d",))]
    steps = {s.name: s for s in default_steps(("1d",))}
    assert names.index("autopilot") == names.index("adapt") + 1
    assert steps["autopilot"].required is False


def test_the_regime_summary_is_json_serialisable() -> None:
    import json

    json.dumps(_read([0.001] * 1100))
    assert np.isfinite(_read([0.001] * 1100)["drawdown"])


def test_api_serves_the_stored_check_newest_event_first_and_says_so_when_there_is_none() -> None:
    from tmon.api.autopilot import autopilot_out

    assert autopilot_out(None).available is False
    doc = _assess(_state("2026-11-13", {"5": "equal"}), _deep("2026-11-10", ("gbm@5",)))
    doc = _assess(_state("2026-11-14", {"5": "gbm"}), _deep("2026-11-10", ("gbm@5",)), doc)
    doc["regime"] = {
        "as_of": "2026-11-14",
        "drawdown": 0.01,
        "return_recent": 0.2,
        "recent_days": 120,
        "windows": [0.5, -0.01],
        "bear_windows": 0,
        "bullish_only": True,
        "stress": False,
        "stress_drawdown": 0.2,
    }
    out = autopilot_out(doc)
    assert out.available and out.deep is not None and out.deep.passed == ["gbm@5"]
    assert out.regime is not None and out.regime.bullish_only
    assert out.events[0].kind == "champion" and out.events[0].after == "gbm"
