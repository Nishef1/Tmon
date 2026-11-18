"""The autopilot: regime reading and what counts as an event."""

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


def _assess(state: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    return autopilot.assess(state, previous, checked_at="2026-11-14T10:00:00")


def test_a_champion_change_and_a_regime_flip_are_events() -> None:
    first = _assess(_state("2026-11-13", {"5": "equal"}))
    assert first["events"] == []  # nothing to compare with yet
    second = _assess(_state("2026-11-14", {"5": "ridge4_x120"}, stress=True), first)
    kinds = {e["kind"] for e in second["events"]}
    assert kinds == {"champion", "regime"}
    champ = next(e for e in second["events"] if e["kind"] == "champion")
    assert (champ["horizon"], champ["before"], champ["after"]) == (5, "equal", "ridge4_x120")


def test_events_are_capped() -> None:
    prev: dict[str, Any] = {
        "champions": {"5": "equal"},
        "regime": {"stress": False},
        "events": [{"at": "2026-01-01", "kind": "champion"}] * autopilot.EVENTS_KEEP,
    }
    out = _assess(_state("2026-11-14", {"5": "gbm"}), prev)
    assert len(out["events"]) == autopilot.EVENTS_KEEP and any(
        e.get("after") == "gbm" for e in out["events"]
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(autopilot, "_load", docs.get)
    monkeypatch.setattr(autopilot, "_store", lambda doc: docs.__setitem__(autopilot.KEY, doc))
    monkeypatch.setattr(adapt_cycle, "load_state", lambda: docs.get("state"))
    return docs


def test_run_without_a_state_does_nothing(store: dict[str, dict[str, Any]]) -> None:
    assert "skipped" in autopilot.run()
    assert autopilot.KEY not in store


def test_run_stores_one_check(store: dict[str, dict[str, Any]]) -> None:
    store["state"] = _state("2026-11-14", {"5": "equal"})
    assert autopilot.run() == {"as_of": "2026-11-14", "events": 0}
    assert store[autopilot.KEY]["champions"] == {"5": "equal"}


def test_the_daily_cycle_has_an_optional_autopilot_step_after_adapt() -> None:
    from tmon.tasks.cycle import default_steps

    names = [s.name for s in default_steps()]
    steps = {s.name: s for s in default_steps()}
    assert names.index("autopilot") == names.index("adapt") + 1
    assert steps["autopilot"].required is False


def test_the_regime_summary_is_json_serialisable() -> None:
    import json

    json.dumps(_read([0.001] * 1100))
    assert np.isfinite(_read([0.001] * 1100)["drawdown"])


def test_api_serves_the_stored_check_newest_event_first_and_says_so_when_there_is_none() -> None:
    from tmon.api.autopilot import autopilot_out

    assert autopilot_out(None).available is False
    doc = _assess(_state("2026-11-13", {"5": "equal"}))
    doc = _assess(_state("2026-11-14", {"5": "gbm"}), doc)
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
    assert out.available
    assert out.regime is not None and out.regime.bullish_only
    assert out.events[0].kind == "champion" and out.events[0].after == "gbm"
