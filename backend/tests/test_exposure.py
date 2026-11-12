"""R2 exposure layer: component logic on series whose answer is known."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from tmon.backtest.exposure_eval import evaluate, simulate
from tmon.core.engine_config import get_engine_config
from tmon.engine.exposure import compute_exposure

CFG = get_engine_config().v2.exposure
N = 420


def _dates() -> list[date]:
    return [date(2023, 1, 1) + timedelta(days=i) for i in range(N)]


def _inputs(path: np.ndarray, rf_daily: float = 0.0005, share: float = 0.0):
    ds = _dates()
    idx = pl.DataFrame({"date": ds, "close": path})
    rf = pl.DataFrame({"date": ds, "ret": [rf_daily] * N})
    ss = pl.DataFrame({"date": ds, "share": [share] * N})
    return idx, rf, ss


def test_steady_uptrend_is_fully_invested():
    idx, rf, ss = _inputs(100 * 1.003 ** np.arange(N))
    e = compute_exposure(idx, rf, ss, CFG)
    assert e["exposure"][-1] == 1.0 and e["trend"][-1] == 1.0 and e["abs_mom"][-1] == 1.0


def test_downtrend_goes_to_cash():
    idx, rf, ss = _inputs(100 * 0.998 ** np.arange(N))
    e = compute_exposure(idx, rf, ss, CFG)
    assert e["exposure"][-1] == 0.0


def test_history_too_short_leaves_exposure_null():
    idx, rf, ss = _inputs(100 * 1.003 ** np.arange(N))
    e = compute_exposure(idx, rf, ss, CFG)
    assert e["exposure"][: CFG.trend_window_days - 1].null_count() == CFG.trend_window_days - 1


def test_trend_up_but_bill_beats_index_gives_half():
    # index rises 0.02% a day, the bill 0.05% a day: trend on, absolute momentum off
    idx, rf, ss = _inputs(100 * 1.0002 ** np.arange(N))
    e = compute_exposure(idx, rf, ss, CFG)
    assert e["trend"][-1] == 1.0 and e["abs_mom"][-1] == 0.0 and e["exposure"][-1] == 0.5


def test_sell_queue_stress_scales_exposure():
    idx, rf, ss = _inputs(100 * 1.003 ** np.arange(N), share=0.2)
    assert abs(compute_exposure(idx, rf, ss, CFG)["exposure"][-1] - 0.8) < 1e-9


def test_vol_cap_target_overrides_and_never_exceeds_one():
    rng = np.random.default_rng(1)
    path = 100 * np.cumprod(1 + 0.004 + rng.normal(0, 0.03, N))
    idx, rf, ss = _inputs(path)
    lo = compute_exposure(idx, rf, ss, CFG, target_vol_annual=0.05)
    off = compute_exposure(idx, rf, ss, CFG, target_vol_annual=None)
    assert lo["vol_cap"].drop_nulls().max() <= 1.0
    assert (lo["vol_cap"].drop_nulls() < 1.0).any() and (off["vol_cap"] == 1.0).all()


def test_exposure_applies_to_the_next_day_and_costs_changes():
    ds = _dates()[:5]
    exp = pl.DataFrame({"date": ds, "x": [0.0, 1.0, 1.0, 1.0, 1.0]})
    ret = pl.DataFrame({"date": ds, "ret": [0.0, 0.10, 0.10, 0.10, 0.10]})
    rf = pl.DataFrame({"date": ds, "ret": [0.0] * 5})
    s = simulate(exp, ret, rf, cost_per_side=0.0, column="x")
    # 1.0 is decided at day 2's close -> it earns day 3's 10%; day 2's own 10% is missed
    assert s["date"][0] == ds[2] and abs(s["ret"][0] - 0.10) < 1e-12
    c = simulate(exp, ret, rf, cost_per_side=0.01, column="x")
    assert abs(c["ret"][0] - 0.09) < 1e-12  # the switch from 0 to 1 is paid once
    assert abs(c["ret"][1] - 0.10) < 1e-12  # and not again while the exposure stays


def test_evaluate_protects_a_crash_and_reports_acceptance():
    rng = np.random.default_rng(5)
    r = np.r_[rng.normal(0.002, 0.01, 300), rng.normal(-0.01, 0.01, 60), rng.normal(0.0, 0.01, 60)]
    idx, rf, ss = _inputs(100 * np.cumprod(1 + r))
    res = evaluate(idx, rf, ss, 0.2)
    a = res.acceptance
    assert a["lower_drawdown_than_index"] and a["passed"] in (True, False)
    assert res.n_days > 50 and "لایهٔ مواجهه (کامل)" in res.strategies
