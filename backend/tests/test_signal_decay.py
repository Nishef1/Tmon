"""R1 signal decay: IC arithmetic on a market whose edge is planted, so the answer is known."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from tmon.backtest.signal_decay import (
    analyse,
    build_panel,
    daily_ic,
    forward_returns,
    render_markdown,
)

N_SYM, N_DAY = 60, 420


def _market(plant: bool, seed: int = 3) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.02, (N_DAY, N_SYM))
    adj = 1000 * np.cumprod(1 + ret, axis=0)
    days = [date(2022, 1, 1) + timedelta(days=i) for i in range(N_DAY)]
    ids = np.repeat(np.arange(N_SYM), N_DAY)
    dates = days * N_SYM
    adj_df = pl.DataFrame(
        {"instrument_id": ids, "date": dates, "adj_close": adj.T.reshape(-1)}
    ).with_columns(pl.col("date").cast(pl.Date))
    # buy power knows the return over the next 20 days after the next close (plus noise)
    fwd = np.full((N_DAY, N_SYM), np.nan)
    fwd[: N_DAY - 21] = adj[21:] / adj[1 : N_DAY - 20] - 1
    noise = rng.normal(0, 0.05, (N_DAY, N_SYM))
    bp = np.nan_to_num(fwd, nan=0.0) + noise if plant else noise
    feats = pl.DataFrame(
        {
            "instrument_id": ids,
            "date": dates,
            "market_halt": False,
            "eligible": True,
            "queue_state": "none",
            "ind_buy_power": bp.T.reshape(-1),
            "rv_20": rng.normal(0, 1, N_DAY * N_SYM),
            "dist_high_52w": rng.normal(0, 1, N_DAY * N_SYM),
        }
    ).with_columns(pl.col("date").cast(pl.Date))
    return feats, adj_df


def test_forward_return_enters_at_the_next_close():
    adj = pl.DataFrame(
        {
            "instrument_id": [1] * 5,
            "date": [date(2024, 1, d) for d in range(1, 6)],
            "adj_close": [100.0, 110.0, 121.0, 133.1, 146.41],
        }
    )
    out = forward_returns(adj, (1,))
    # decision on day 1: entry close of day 2 (110), exit close of day 3 (121)
    assert abs(out["fwd_1"][0] - 0.10) < 1e-9
    assert out["fwd_1"][-1] is None and out["fwd_1"][-2] is None


def test_planted_signal_has_high_ic_at_its_horizon_and_decays():
    feats, adj = _market(plant=True)
    panel = build_panel(feats, adj, horizons=(5, 20, 60))
    ic20 = daily_ic(panel, "r_ind_buy_power", 20)["ic"].mean()
    ic60 = daily_ic(panel, "r_ind_buy_power", 60)["ic"].mean()
    assert ic20 > 0.3 and ic60 < ic20  # the planted information fades past its horizon


def test_noise_signal_has_ic_near_zero_and_report_renders():
    feats, adj = _market(plant=False)
    panel = build_panel(feats, adj, horizons=(5, 20))
    res = analyse(panel, horizons=(5, 20))
    ic = res.ic["ind_buy_power"][20]
    assert abs(ic["mean"]) < 0.03 and abs(ic["t"]) < 3
    assert res.n_days > 100
    md = render_markdown(res)
    assert "IC" in md and "ind_buy_power" in md and "ابزار تحلیل" in md
