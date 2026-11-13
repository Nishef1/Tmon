"""Glossary signals (tmon.backtest.ta_signals): indicators, no look-ahead, lock filter, verdicts."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from tmon.api.technical import technical_out, verdict_sentence
from tmon.backtest import ta_signals as ts

C = pl.col


def _world(n: int = 400, seed: int = 3, symbols: int = 1) -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(seed)
    days = [dt.date(2015, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    rows, flows = [], []
    for s in range(1, symbols + 1):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
        hi = close * (1 + rng.uniform(0, 0.02, n))
        lo = close * (1 - rng.uniform(0, 0.02, n))
        op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.005, n))
        vol = rng.uniform(1e3, 5e3, n)
        for i in range(n):
            rows.append(
                {
                    "instrument_id": s,
                    "date": days[i],
                    "open": float(op[i]),
                    "high": float(max(hi[i], op[i], close[i])),
                    "low": float(min(lo[i], op[i], close[i])),
                    "close": float(close[i]),
                    "last": float(close[i]),
                    "prev_close": float(close[i - 1]) if i else None,
                    "volume": float(vol[i]),
                    "value": float(vol[i] * close[i]),
                    "market_halt": False,
                }
            )
            flows.append(
                {
                    "instrument_id": s,
                    "date": days[i],
                    "buy_value_i": float(rng.uniform(4e4, 6e4)),
                    "sell_value_i": float(rng.uniform(4e4, 6e4)),
                    "buy_count_i": 10,
                    "sell_count_i": 10,
                }
            )
    return pl.DataFrame(rows), pl.DataFrame(flows)


def _wilder_rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    r = close[1:] / close[:-1] - 1
    g, lo = np.clip(r, 0, None), np.clip(-r, 0, None)
    ag, al, out = None, None, [np.nan]
    for i in range(len(r)):
        if i < n - 1:
            out.append(np.nan)
            continue
        if ag is None:
            # polars ewm_mean(adjust=False) starts from the first value, not a simple mean
            ag, al = g[0], lo[0]
            for j in range(1, i + 1):
                ag = ag + (g[j] - ag) / n
                al = al + (lo[j] - al) / n
        else:
            ag = ag + (g[i] - ag) / n
            al = al + (lo[i] - al) / n
        out.append(100 - 100 / (1 + ag / al))
    return np.array(out)


def test_indicators_match_their_textbook_formulas() -> None:
    prices, clients = _world()
    p = ts.indicators(prices, clients).sort("date")
    c = prices["close"].to_numpy()
    assert p["sma20"].to_numpy()[30] == pytest.approx(c[11:31].mean())
    np.testing.assert_allclose(p["rsi"].to_numpy()[20:], _wilder_rsi(c)[20:], rtol=1e-9)
    k = p["stoch_k"].drop_nulls().to_numpy()
    assert k.min() >= 0 and k.max() <= 100
    w = p["willr"].drop_nulls().to_numpy()
    np.testing.assert_allclose(w, p["stoch_k"].drop_nulls().to_numpy() - 100)
    step = np.sign(np.diff(c)) * prices["volume"].to_numpy()[1:]
    assert p["obv"][-1] == pytest.approx(step.sum())
    row = p.row(300, named=True)
    assert row["bb_up"] - row["sma20"] == pytest.approx(row["sma20"] - row["bb_dn"])
    assert 0 < row["mfi"] < 100 and 0 <= row["adx"] <= 100 and row["atr_pct"] > 0
    # yesterday's pivot and its first resistance and support
    prev = p.row(299, named=True)
    tp = (prev["high"] + prev["low"] + prev["close"]) / 3
    assert row["pivot"] == pytest.approx(tp) and row["r1"] == pytest.approx(2 * tp - prev["low"])


def test_no_indicator_sees_the_future() -> None:
    prices, clients = _world()
    cut = prices["date"][300]
    full = ts.flags(ts.indicators(prices, clients)).filter(C("date") <= cut)
    part = ts.flags(ts.indicators(prices.filter(C("date") <= cut), clients)).filter(
        C("date") <= cut
    )
    cols = [c for c in full.columns if c.startswith("s_") or c in ts.NOW_COLS]
    assert full.select(cols).equals(part.select(cols))


def test_a_buy_on_a_locked_up_day_is_left_out() -> None:
    prices, clients = _world(n=420, symbols=6)
    p = ts.indicators(prices, clients)
    # make every symbol's day 350 jump 5%: that day is locked, the day before's entry is dropped
    p = p.with_columns(lock_up=C("lock_up") | (C("date") == prices["date"][350]))
    w = ts.with_outcomes(p)
    assert w.filter(C("date") == prices["date"][349])["entry_up_locked"].all()
    assert not w.filter(C("date") == prices["date"][348])["entry_up_locked"].any()
    # the buy-side benchmark leaves those symbols out, so on that day it has nothing to compare
    assert w.filter(C("date") == prices["date"][349])["xb20"].null_count() == 6


def _stats(halves: list[float], up_edge: list[float], years_pos: float = 0.8) -> dict:
    h = {"n": 500, "excess_mean": sum(halves) / 2, "excess_median": 0.0, "beat": 0.5,
         "up": 0.55, "up_all": 0.5, "halves": halves, "halves_up_edge": up_edge,
         "years": 10, "years_pos": years_pos}  # fmt: skip
    return {"n": 500, "symbols": 50, **{f"h{x}": h for x in ts.H}}


@pytest.mark.parametrize(
    ("side", "halves", "edge", "label"),
    [
        ("buy", [0.03, 0.02], [0.0, 0.0], "works"),
        ("sell", [-0.03, -0.02], [0.0, 0.0], "works"),
        ("buy", [0.03, 0.01], [0.0, 0.0], "no_edge"),  # one half below the cost
        ("buy", [-0.03, -0.02], [0.0, 0.0], "backfires"),
        ("buy", [0.001, 0.002], [0.04, 0.05], "direction_only"),
        ("sell", [0.001, 0.002], [-0.04, -0.05], "direction_only"),
        ("buy", [-0.005, -0.002], [0.0, 0.0], "reverse_small"),
    ],
)
def test_verdict_labels(side: str, halves: list[float], edge: list[float], label: str) -> None:
    yp = 0.8 if side == "buy" else 0.2
    v = ts.verdict(side, _stats(halves, edge, yp), 0.0175)
    assert v["label"] == label


def test_works_needs_most_years_right() -> None:
    assert ts.verdict("buy", _stats([0.03, 0.02], [0, 0], 0.5), 0.0175)["label"] == "no_edge"


def test_sentences_follow_the_numbers() -> None:
    s = {"label": "works", "side": "sell", "profit_horizon": 60, **_stats([-0.03, -0.02], [0, 0])}
    text = verdict_sentence(s, 0.0175)
    assert "60 روز بعد" in text and "2.5٪ بدتر" in text and "(1.8٪)" in text
    s = {"label": "direction_only", "side": "buy", "direction_horizons": [5],
         **_stats([0.0, 0.0], [0.05, 0.05])}  # fmt: skip
    assert "55 از ۱۰۰ بار بالا" in verdict_sentence(s, 0.0175)


def test_symbol_part_reads_the_indicators() -> None:
    sig = {"term": "net_flow", "side": "sell", "title": "t", "label": "works",
           "profit_horizon": 20, **_stats([-0.03, -0.02], [0, 0])}  # fmt: skip
    now = {"date": "2026-11-11", "close": 100.0, "rsi": 25.0, "macd": 2.0, "macd_sig": 1.0,
           "sma20": 90.0, "cloud_top": 95.0, "cloud_bot": 80.0, "tenkan": 99.0, "kijun": 97.0,
           "fired": [{"key": "k", "date": "2026-11-10", "ago": 1}]}  # fmt: skip
    risk = {"from": "2025-11-01", "days": 250, "ret_1y": 0.2, "vol_ann": 0.3, "var95": 0.03,
            "max_dd": -0.2, "sharpe": 0.5, "sortino": 0.7}  # fmt: skip
    doc = {"round_trip_cost": 0.0175, "recent_days": 10, "rf_annual": 0.3,
           "signals": {"k": sig}, "now": {"7": now}, "risk": {"7": risk}}  # fmt: skip
    t = technical_out(doc, 7, beta_index=1.2)
    assert t is not None
    by = {v.key: v for v in t.values}
    assert by["rsi"].tone == "buy" and "اشباع فروش" in by["rsi"].reading
    assert by["macd"].tone == "buy" and by["sma20"].tone == "buy"
    assert by["ichimoku"].reading.startswith("بالای ابر")
    assert t.risk is not None and t.risk.beta_index == 1.2 and t.risk.rf_annual == 0.3
    assert "1 روز معاملاتی پیش" in t.lines[0] and t.fired[0].label == "works"
    assert technical_out(doc, 8) is None and technical_out(None, 7) is None


def test_elliott_counts_waves_only_once_each_pivot_is_confirmed() -> None:
    import numpy as np

    from tmon.backtest.ta_signals import elliott_marks, zigzag

    pts = [100, 130, 115, 170, 150, 200, 175, 195, 160, 180]
    c = np.concatenate(
        [np.linspace(pts[i], pts[i + 1], 6)[:-1] for i in range(len(pts) - 1)] + [[180.0]]
    )
    pv = zigzag(c)
    assert [round(x[2]) for x in pv] == [100, 130, 115, 170, 150, 200, 175, 195, 160]
    assert all(conf > i for i, conf, *_ in pv)
    m = elliott_marks(c)
    assert np.flatnonzero(m["ew_w3"]).tolist() == [pv[2][1], pv[6][1]]  # 150-200-175 too
    assert np.flatnonzero(m["ew_5"]).tolist() == [pv[5][1]]
    assert np.flatnonzero(m["ew_abc"]).tolist() == [pv[8][1]]


def test_fvg_zones_and_their_retest() -> None:
    import datetime as dt

    from tmon.backtest.ta_signals import _fvg

    hi = [10.0, 10.5, 12.0, 12.5, 12.2, 11.0]
    lo = [9.5, 10.0, 11.0, 11.8, 11.5, 10.2]
    p = pl.DataFrame(
        {
            "instrument_id": [1] * 6,
            "date": [dt.date(2026, 1, d) for d in range(1, 7)],
            "high": hi,
            "low": lo,
            "close": [9.8, 10.4, 11.8, 12.2, 11.9, 10.4],
        }
    )
    z = _fvg(p)
    # day 3: low 11.0 above day-1 high 10.0 -> bullish zone 10.0..11.0, read from day 4 on
    assert z["fb_top_y"].to_list()[3:] == [11.0, 11.8, 11.8]
    assert z["fb_bot_y"][3] == 10.0
