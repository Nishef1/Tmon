"""What moves a stock besides its own chart (docs/reports/stock-drivers-2026-11.md).

For every stock: how much of its weekly move goes with the overall index and the free-market
dollar (one regression on the last three years), how closely it follows world copper and Brent,
where its price in dollars sits in its own last ten years, its last cash dividend read off the
price gap, and how it moved against the index in the 20 trading days after each dated shock in
``config/market_events.csv`` (wars, sanctions, unrest, deals).

These describe the past. The research behind them found that none of the outside prices made
the ranking model better (the report), so nothing here feeds a verdict.
"""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.core.config import BACKEND_ROOT

G = "instrument_id"
C = pl.col
EVENTS_PATH = BACKEND_ROOT / "config" / "market_events.csv"
WINDOW_WEEKS = 156  # three years of Tehran trading weeks
MIN_WEEKS = 78
BLOCK = 4  # correlations use 4-week sums: a week is too noisy, a month is what people see
MAX_GAP_WEEKS = 4  # a change across a longer halt or closure is one outsized point: dropped
EVENT_DAYS = 20
USD_YEARS = 10
MIN_USD_DAYS = 500
DIVIDEND_MIN_FACTOR = 0.8  # a gap under 20% is almost always a cash dividend, bigger is a raise
BAD_KINDS = ("war", "sanction", "unrest")


def read_events(path: Path = EVENTS_PATH) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("date")]


def week(e: pl.Expr) -> pl.Expr:
    """Saturday to Friday share one key: +2 days moves Saturday onto the ISO Monday."""
    return (e + pl.duration(days=2)).dt.truncate("1w")


def outside_levels(index: pl.DataFrame, macro: pl.DataFrame) -> pl.DataFrame:
    """Daily log levels of the index, dollar, copper and Brent on every index day.

    ``index``: date, close. ``macro``: series, date, value (usd_free, copper_usd, brent_usd)."""
    d = index.select("date", C("close").alias("tedpix")).sort("date")
    for s in ("usd_free", "copper_usd", "brent_usd"):
        one = macro.filter(C("series") == s).select("date", C("value").alias(s)).sort("date")
        d = d.join_asof(one.unique("date", keep="last").sort("date"), on="date")
    return d.with_columns(*[C(c).log().alias("l_" + c) for c in d.columns if c != "date"])


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    xx = np.column_stack([np.ones(len(y)), x])
    b, *_ = np.linalg.lstsq(xx, y, rcond=None)
    res = y - xx @ b
    return b[1:], float(1 - res.var() / y.var()) if y.var() > 0 else math.nan


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 12 or a[ok].std() == 0 or b[ok].std() == 0:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def sensitivities(closes: pl.DataFrame, lv: pl.DataFrame, as_of: date) -> dict[int, dict[str, Any]]:
    """Betas on the index and dollar, and 4-week correlations, over the last WINDOW_WEEKS.

    A week's change is measured between consecutive weeks the stock traded, for the stock and
    for every outside price alike, so a halt does not pair a month of stock move with one week
    of index move. A change across a gap longer than MAX_GAP_WEEKS (the 2026 closure) is left
    out: one such point would dominate three years of weekly changes."""
    lw = lv.group_by(wk=week(C("date"))).agg(pl.all().exclude("date").sort_by("date").last())
    sw = closes.group_by(G, wk=week(C("date"))).agg(C("close").sort_by("date").last())
    sw = sw.join(lw, on="wk").sort(G, "wk")
    cols = ["close", "l_tedpix", "l_usd_free", "l_copper_usd", "l_brent_usd"]
    sw = sw.with_columns(C("close").log()).with_columns(
        *[C(c).diff().over(G).alias("r_" + c) for c in cols],
        gap=C("wk").diff().over(G),
    )
    sw = sw.filter(C("gap").is_null() | (C("gap") <= timedelta(weeks=MAX_GAP_WEEKS)))
    recent = as_of - timedelta(weeks=8)  # a stock not traded for two months gets no betas
    sw = sw.filter(C("wk") >= recent - timedelta(weeks=WINDOW_WEEKS))
    out: dict[int, dict[str, Any]] = {}
    for (iid,), g in sw.drop_nulls(["r_close", "r_l_tedpix", "r_l_usd_free"]).group_by(G):
        g = g.sort("wk").tail(WINDOW_WEEKS)
        if g.height < MIN_WEEKS or g["wk"].max() < recent:  # type: ignore[operator]
            continue
        y = g["r_close"].to_numpy()
        beta, r2 = _ols(y, g.select("r_l_tedpix", "r_l_usd_free").to_numpy())
        blk = g.with_columns(b=pl.int_range(pl.len()) // BLOCK).group_by("b").agg(
            C("^r_.*$").sum(), n=pl.len()
        ).filter(C("n") == BLOCK)  # fmt: skip
        s = blk["r_close"].to_numpy()
        out[int(iid)] = {
            "weeks": g.height,
            "beta_index": float(beta[0]),
            "beta_usd": float(beta[1]),
            "r2": r2,
            "corr_index": _corr(s, blk["r_l_tedpix"].to_numpy()),
            "corr_usd": _corr(s, blk["r_l_usd_free"].to_numpy()),
            "corr_copper": _corr(s, blk["r_l_copper_usd"].to_numpy()),
            "corr_brent": _corr(s, blk["r_l_brent_usd"].to_numpy()),
        }
    return out


def usd_position(closes: pl.DataFrame, lv: pl.DataFrame, as_of: date) -> dict[int, dict[str, Any]]:
    """Where today's price in dollars sits among the last USD_YEARS of the stock's own days."""
    start = as_of - timedelta(days=round(365.25 * USD_YEARS))
    usd = lv.select("date", "usd_free").drop_nulls().sort("date")
    d = closes.filter(C("date") >= start).sort("date").join_asof(usd, on="date")
    d = d.with_columns(pu=C("close") / C("usd_free")).drop_nulls("pu").sort(G, "date")
    g = d.group_by(G).agg(
        n=pl.len(),
        first=C("date").first(),
        last_date=C("date").last(),
        pctl=(C("pu") < C("pu").last()).mean(),
        from_peak=C("pu").last() / C("pu").max() - 1,
    )
    g = g.filter((C("n") >= MIN_USD_DAYS) & (C("last_date") >= as_of - timedelta(days=60)))
    return {
        int(r[G]): {
            "usd_pctl": float(r["pctl"]),
            "usd_from_peak": float(r["from_peak"]),
            "usd_years": round((r["last_date"] - r["first"]).days / 365.25, 1),
        }
        for r in g.iter_rows(named=True)
    }


def dividends(adjustments: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """The last price gap small enough to be a cash dividend: date, rial per share, yield."""
    d = adjustments.filter((C("adj_factor") >= DIVIDEND_MIN_FACTOR) & (C("adj_factor") < 1)).sort(
        G, "date"
    )
    last = d.group_by(G).agg(C("date", "close_before", "price_after", "adj_factor").last())
    return {
        int(r[G]): {
            "div_date": str(r["date"]),
            "dps": float(r["close_before"] - r["price_after"]),
            "div_yield": float(1 - r["adj_factor"]),
        }
        for r in last.iter_rows(named=True)
    }


def event_moves(
    closes: pl.DataFrame, index: pl.DataFrame, events: list[dict[str, str]]
) -> dict[int, list[list[float | int]]]:
    """[event number, stock change, index change] over the stock's first EVENT_DAYS trading days
    after each shock, from its last close before it. Skipped when the stock had not traded in
    the month before the shock (a halt would hide the move), or when the window starts inside the
    previous counted shock's window (a ceasefire twelve days after a war is the same move)."""
    idx = index.sort("date")
    idx_d = idx["date"].to_numpy()
    idx_c = idx["close"].to_numpy()
    days = [np.datetime64(e["date"]) for e in events]
    out: dict[int, list[list[float | int]]] = {}
    for (iid,), g in closes.sort("date").group_by(G):
        dd = g["date"].to_numpy()
        cc = g["close"].to_numpy()
        rows: list[list[float | int]] = []
        last_end = -1
        for k, ed in enumerate(days):
            i0 = int(np.searchsorted(dd, ed)) - 1
            i1 = i0 + EVENT_DAYS
            if i0 < 0 or i1 >= len(dd) or (ed - dd[i0]) > np.timedelta64(30, "D"):
                continue
            if i0 < last_end:  # inside the previous shock's window: the same move, not a new one
                continue
            last_end = i1
            j0 = int(np.searchsorted(idx_d, dd[i0], side="right")) - 1
            j1 = int(np.searchsorted(idx_d, dd[i1], side="right")) - 1
            if j0 < 0 or j1 < 0:
                continue
            rows.append([k, float(cc[i1] / cc[i0] - 1), float(idx_c[j1] / idx_c[j0] - 1)])
        if rows:
            out[int(iid)] = rows
    return out


def market_after_bad(
    index: pl.DataFrame, macro: pl.DataFrame, events: list[dict[str, str]]
) -> dict[str, int]:
    """How often the index and the free dollar were higher EVENT_DAYS trading days after a bad
    shock (war, sanction, unrest), counted from the last index close before it. Days the
    exchange was shut repeat the last close and are dropped first; a shock inside the previous
    counted window is skipped, as in ``event_moves``."""
    ix = index.sort("date").filter(C("close") != C("close").shift(1).fill_null(-1.0))
    d, c = ix["date"].to_numpy(), ix["close"].to_numpy()
    us = (
        macro.filter(C("series") == "usd_free").unique("date", keep="last").sort("date")
    )  # fmt: skip
    ud, uv = us["date"].to_numpy(), us["value"].to_numpy()
    out = {"n": 0, "index_up": 0, "usd_n": 0, "usd_up": 0}
    last_end = -1
    for e in events:
        ed = np.datetime64(e["date"])
        i0 = int(np.searchsorted(d, ed)) - 1
        i1 = i0 + EVENT_DAYS
        if i0 < 0 or i1 >= len(d) or i0 < last_end:
            continue
        last_end = i1
        if e["kind"] not in BAD_KINDS:
            continue
        out["n"] += 1
        out["index_up"] += int(c[i1] > c[i0])
        a = int(np.searchsorted(ud, d[i0], side="right")) - 1
        b = int(np.searchsorted(ud, d[i1], side="right")) - 1
        if a >= 0 and (d[i0] - ud[a]) <= np.timedelta64(10, "D"):
            out["usd_n"] += 1
            out["usd_up"] += int(uv[b] > uv[a])
    return out
