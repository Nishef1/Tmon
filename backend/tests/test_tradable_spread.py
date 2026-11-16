import datetime as dt

import polars as pl

from tmon.backtest.signal_decay import tradable_spread


def _frame(n_days: int = 60, n_names: int = 120):
    rows, liq = [], []
    for d in range(n_days):
        day = dt.date(2025, 1, 1) + dt.timedelta(days=d)
        for i in range(n_names):
            comp = i / n_names
            # the top scores earn more, but the best 20 names are locked in a buy queue
            queued = i >= n_names - 20
            fwd = 0.10 if queued else 0.01 * comp
            rows.append(
                {
                    "instrument_id": i,
                    "date": day,
                    "composite": comp,
                    "queue_state": "buy_queue" if queued else "none",
                    "fwd_5": fwd,
                }
            )
            liq.append({"instrument_id": i, "date": day, "median_value_20": 1e9 + i})
    return pl.DataFrame(rows), pl.DataFrame(liq)


def test_buy_queue_names_are_not_counted_and_edge_is_over_the_mean():
    panel, liq = _frame()
    out = tradable_spread(panel, liq, 5, top_n=100)
    assert out["n_days"] == 60
    # without the queued names the top decile earns about 0.8% and the group about 0.4%
    assert 0.002 < out["top_excess"] < 0.006
    assert out["bottom_excess"] < 0
