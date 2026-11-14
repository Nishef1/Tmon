"""Period returns and 52-week range of every symbol, from split/dividend-adjusted closes.

The screener shows one row per symbol, so these are computed for all symbols in one pass and
kept while the bars behind them are unchanged: the first request after new data pays the few
seconds, the rest are free.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from datetime import timedelta

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.features.adjustment import apply_adjustments
from tmon.storage.models import PriceAdjustment, PriceDaily

# a larger one-day move is a first listing day or a stale reference price after a long halt,
# not a return anyone earned
MAX_DAY_MOVE = 0.5


def day_change(close: float | None, prev_close: float | None) -> float | None:
    """Close against the previous close, or ``None`` when the pair is not a real daily move."""
    if not close or not prev_close or prev_close <= 0:
        return None
    move = close / prev_close - 1
    return move if abs(move) <= MAX_DAY_MOVE else None


# calendar days back from the last market day: a week, a month, three months and a year
HORIZONS = {"ret_week": 7, "ret_month": 30, "ret_3m": 90, "ret_year": 365}


@dataclass(frozen=True)
class Period:
    ret_week: float | None = None
    ret_month: float | None = None
    ret_3m: float | None = None
    ret_year: float | None = None
    year_high: float | None = None  # adjusted-close high of the last year
    year_low: float | None = None


_cache: dict[tuple[object, ...], dict[int, Period]] = {}
_lock = threading.Lock()


def _fingerprint(session: Session, last: dt.date) -> tuple[object, ...]:
    """What the table is computed from: any new, corrected or re-adjusted bar changes it."""
    since = last - timedelta(days=HORIZONS["ret_year"] + 15)
    bars = session.execute(
        select(
            func.count(),
            func.max(PriceDaily.fetched_at),
            func.sum(PriceDaily.close),
            func.sum(PriceDaily.prev_close),
        ).where(PriceDaily.date >= since, PriceDaily.date <= last)
    ).one()
    adj = session.execute(
        select(func.count(), func.sum(PriceAdjustment.adj_factor)).where(
            PriceAdjustment.date <= last
        )
    ).one()
    return (last, *tuple(bars), *tuple(adj))


def period_table(session: Session, last: dt.date) -> dict[int, Period]:
    """Cached for exactly as long as the bars behind it are unchanged, never for a fixed time."""
    key = _fingerprint(session, last)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    table = _compute(session, last)
    with _lock:
        _cache.clear()  # only the latest state is ever asked for
        _cache[key] = table
    return table


def _compute(session: Session, last: dt.date) -> dict[int, Period]:
    since = last - timedelta(days=HORIZONS["ret_year"] + 15)
    rows = session.execute(
        select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close, PriceDaily.prev_close)
        .where(PriceDaily.date >= since, PriceDaily.date <= last, PriceDaily.market_halt.is_(False))
        .order_by(PriceDaily.instrument_id, PriceDaily.date)
    ).all()
    if not rows:
        return {}
    raw = pl.DataFrame(
        {
            "instrument_id": [r[0] for r in rows],
            "date": [r[1] for r in rows],
            "close": [None if r[2] is None else float(r[2]) for r in rows],
            "prev_close": [None if r[3] is None else float(r[3]) for r in rows],
        },
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            "close": pl.Float64,
            "prev_close": pl.Float64,
        },
    ).filter(pl.col("close") > 0)
    adj = apply_adjustments(raw).select("instrument_id", "date", "adj_close")
    out: dict[int, dict[str, float | None]] = {
        i: {} for i in adj["instrument_id"].unique().to_list()
    }

    now = adj.filter(pl.col("date") == last).select(
        "instrument_id", pl.col("adj_close").alias("now")
    )
    for name, back in HORIZONS.items():
        target = last - timedelta(days=back)
        then = (
            adj.filter(pl.col("date") <= target)
            .sort("date")
            .group_by("instrument_id")
            .agg(pl.col("date").last().alias("d"), pl.col("adj_close").last().alias("then"))
            # a symbol that did not exist yet, or was halted for weeks, has no honest return
            .filter(pl.col("d") >= target - timedelta(days=10))
        )
        j = now.join(then, on="instrument_id").with_columns(r=pl.col("now") / pl.col("then") - 1)
        for i, r in j.select("instrument_id", "r").iter_rows():
            out[i][name] = r
    start = last - timedelta(days=HORIZONS["ret_year"])
    rng = (
        adj.filter(pl.col("date") >= start)
        .group_by("instrument_id")
        .agg(
            pl.col("adj_close").max().alias("hi"),
            pl.col("adj_close").min().alias("lo"),
            pl.col("date").min().alias("first"),
        )
        # a symbol listed within the year has no full 52-week range
        .filter(pl.col("first") <= start + timedelta(days=10))
    )
    for i, hi, lo, _ in rng.iter_rows():
        out[i]["year_high"], out[i]["year_low"] = hi, lo
    return {i: Period(**v) for i, v in out.items()}
