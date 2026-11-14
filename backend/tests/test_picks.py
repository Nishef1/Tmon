from __future__ import annotations

import datetime as dt

from tmon.api.routers.picks import _check
from tmon.storage.models import Instrument, TrackedPick

D0 = dt.date(2026, 1, 1)


def _closes(n: int, step: float = 0.01) -> list[tuple[dt.date, float]]:
    return [(D0 + dt.timedelta(days=i), 100.0 * (1 + step) ** i) for i in range(n)]


def _pick() -> tuple[TrackedPick, Instrument]:
    snap = {
        "as_of": D0.isoformat(),
        "gauge": 90.0,
        "verdict": "buy",
        "horizons": [
            {"key": "D1", "label": "x", "verdict": "hold", "verdict_label": "صبر کنید"},
            {"key": "W1", "label": "x", "verdict": "buy", "verdict_label": "خرید"},
        ],
        "candles": [
            {"h": 1, "up": 0.6, "q10": -0.02, "q50": 0.0, "q90": 0.02},
            {"h": 5, "up": 0.6, "q10": -0.05, "q50": 0.01, "q90": 0.03},
            {"h": 20, "up": 0.7, "q10": -0.1, "q50": 0.05, "q90": 0.1},
        ],
    }
    p = TrackedPick(id=1, instrument_id=7, entered_on=D0, snapshot=snap)
    i = Instrument(id=7, symbol_fa="ایکس", name_fa="شرکت ایکس")
    return p, i


def test_candles_not_yet_happened_stay_pending() -> None:
    p, i = _pick()
    out = _check(p, i, _closes(4))  # the entry day and three candles
    by_h = {c.h: c for c in out.candles}
    assert by_h[1].status == "inside" and by_h[1].actual is not None
    assert abs(by_h[1].actual - 0.01) < 1e-9
    assert by_h[5].status == "pending" and by_h[5].actual is None
    assert out.resolved == 1 and out.inside == 1


def test_a_miss_is_marked_above_or_below() -> None:
    p, i = _pick()
    out = _check(p, i, _closes(8, step=0.02))  # +2%/day: 5 candles later is +10.4%
    by_h = {c.h: c for c in out.candles}
    assert by_h[5].status == "above"
    assert abs((by_h[1].actual or 0) - 0.02) < 1e-9
    assert out.verdicts[1].verdict == "buy" and out.verdicts[1].right is True
    assert out.verdicts[0].days == 1 and out.verdicts[0].net is not None


def test_a_wait_verdict_is_right_when_the_move_does_not_beat_the_cost() -> None:
    p, i = _pick()
    out = _check(p, i, _closes(3, step=0.005))
    d1 = out.verdicts[0]
    assert d1.verdict == "hold" and d1.right is True  # +0.5% is less than the 1.75% cost


def test_snapshot_day_missing_from_prices_gives_no_numbers() -> None:
    p, i = _pick()
    later = [(D0 + dt.timedelta(days=30 + k), 100.0 + k) for k in range(5)]
    out = _check(p, i, later)
    assert out.resolved == 0 and out.last_return is None
