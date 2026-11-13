"""Stock drivers (tmon.backtest.drivers): betas, dollar price, dividends, shock moves, sentences."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from tmon.backtest import drivers as dv

START = dt.date(2020, 1, 4)  # a Saturday


def _days(n: int) -> list[dt.date]:
    # five trading days a week, Saturday to Wednesday
    out, d = [], START
    while len(out) < n:
        if d.weekday() in (5, 6, 0, 1, 2):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _world(n: int = 1000, beta: float = 1.5, usd_beta: float = 0.0) -> tuple[pl.DataFrame, ...]:
    rng = np.random.default_rng(1)
    days = _days(n)
    ri = rng.normal(0, 0.01, n)
    ru = rng.normal(0, 0.01, n)
    index = pl.DataFrame({"date": days, "close": 1000 * np.exp(np.cumsum(ri))})
    usd = 1000 * np.exp(np.cumsum(ru))
    macro = pl.concat(
        [
            pl.DataFrame({"series": s, "date": days, "value": v})
            for s, v in (("usd_free", usd), ("copper_usd", usd * 0 + 9000.0), ("brent_usd", usd))
        ]
    )
    stock = 100 * np.exp(np.cumsum(beta * ri + usd_beta * ru))
    closes = pl.DataFrame({"instrument_id": 1, "date": days, "close": stock})
    return closes, index, macro


def test_betas_recover_the_index_and_dollar_ties() -> None:
    closes, index, macro = _world(beta=1.5, usd_beta=0.4)
    lv = dv.outside_levels(index, macro)
    out = dv.sensitivities(closes, lv, closes["date"].max())
    s = out[1]
    assert s["beta_index"] == pytest.approx(1.5, abs=1e-6)
    assert s["beta_usd"] == pytest.approx(0.4, abs=1e-6)
    assert s["r2"] == pytest.approx(1.0) and s["weeks"] <= dv.WINDOW_WEEKS
    assert s["corr_copper"] is None  # a flat series has no correlation


def test_a_stock_not_traded_for_months_gets_no_betas() -> None:
    closes, index, macro = _world()
    lv = dv.outside_levels(index, macro)
    late = closes["date"].max() + dt.timedelta(days=120)
    assert dv.sensitivities(closes, lv, late) == {}


def test_a_change_across_a_long_closure_is_left_out() -> None:
    closes, index, macro = _world(beta=1.5)
    days = closes["date"].to_list()
    shut = (pl.col("date") > days[700]) & (pl.col("date") < days[760])
    # the stock is halted and the index jumps 50% over the closure while Brent doubles
    closes = closes.filter(~shut).with_columns(
        pl.when(pl.col("date") >= days[760]).then(pl.col("close") * 1.2).otherwise(pl.col("close"))
    )
    # while the exchange is shut the index repeats its last close, as TSETMC publishes it
    last = index["close"][700]
    index = index.with_columns(
        pl.when(shut).then(last).when(pl.col("date") >= days[760])
        .then(pl.col("close") * 1.5).otherwise(pl.col("close")).alias("close")
    )  # fmt: skip
    macro = macro.with_columns(
        pl.when((pl.col("series") == "brent_usd") & (pl.col("date") >= days[760]))
        .then(pl.col("value") * 2)
        .otherwise(pl.col("value"))
    )
    s = dv.sensitivities(closes, dv.outside_levels(index, macro), days[-1])[1]
    assert s["beta_index"] == pytest.approx(1.5, abs=1e-6)


def test_usd_position_is_the_share_of_cheaper_days() -> None:
    days = _days(600)
    closes = pl.DataFrame({"instrument_id": 1, "date": days, "close": np.linspace(100, 200, 600)})
    lv = pl.DataFrame({"date": days, "usd_free": [1.0] * 600})
    out = dv.usd_position(closes, lv, days[-1])[1]
    assert out["usd_pctl"] == pytest.approx(599 / 600) and out["usd_from_peak"] == 0.0


def test_dividends_keep_small_gaps_only() -> None:
    adj = pl.DataFrame(
        {
            "instrument_id": [1, 1, 2],
            "date": [dt.date(2024, 7, 1), dt.date(2025, 7, 1), dt.date(2025, 7, 1)],
            "close_before": [1000.0, 1200.0, 1000.0],
            "price_after": [900.0, 1080.0, 500.0],  # the last one is a capital increase
            "adj_factor": [0.9, 0.9, 0.5],
        }
    )
    out = dv.dividends(adj)
    assert out == {1: {"div_date": "2025-07-01", "dps": 120.0, "div_yield": pytest.approx(0.1)}}


def test_event_moves_skip_a_stock_halted_before_the_shock() -> None:
    closes, index, _ = _world(n=300)
    days = closes["date"].to_list()
    ev = [{"date": str(days[100]), "kind": "war"}, {"date": str(days[200]), "kind": "deal"}]
    halted = closes.filter((pl.col("date") < days[150]) | (pl.col("date") > days[210]))
    out = dv.event_moves(halted, index, ev)[1]
    assert [r[0] for r in out] == [0]  # the second shock fell inside the halt
    _, st, ix = out[0]
    assert st == pytest.approx(closes["close"][119] / closes["close"][99] - 1)
    assert ix == pytest.approx(index["close"][119] / index["close"][99] - 1)


def test_sentences_follow_the_numbers() -> None:
    from tmon.api.routers.dashboard import drivers_out

    ev = [{"date": f"202{i}-01-0{i + 1}", "kind": "war", "title_fa": "t", "source": "s"}
          for i in range(4)]  # fmt: skip
    sym = {"weeks": 150, "beta_index": 1.3, "beta_usd": 0.25, "r2": 0.6, "corr_copper": 0.45,
           "corr_brent": 0.1, "usd_pctl": 0.9, "usd_from_peak": -0.1, "usd_years": 10.0,
           "moves": [[0, 0.1, 0.05], [1, -0.1, 0.0], [2, 0.2, 0.1], [3, 0.0, 0.1]]}  # fmt: skip
    doc = {"as_of": "2026-11-11", "event_days": 20, "events": ev, "symbols": {"7": sym}}
    d = drivers_out(doc, 7)
    assert d is not None and d.moves[0].date == dt.date(2023, 1, 4)  # newest first
    text = " ".join(d.lines)
    assert "تندتر از بازار" in text and "دلاری" in text and "مس" in text and "برنت" not in text
    assert "2 بار از شاخص کل بهتر و 2 بار بدتر" in text
    sym["beta_usd"] = 0.02
    assert "اثر روشنی" in " ".join(drivers_out(doc, 7).lines)  # type: ignore[union-attr]
    assert drivers_out(doc, 8) is None and drivers_out(None, 7) is None
