"""Industry candles built from every member stock ("the industry as a consensus of its symbols").

For each industry and day the candle is the average of what its members did that day, each
measured against its own previous adjusted close:

- equal weight: every symbol counts once (the consensus of the symbols);
- value weight: a symbol counts by the value it traded the day before (where the money sits).

The level starts at 100 at the first day of the window and moves by the average close-to-close
move. Open, high and low are the same average of each member's open, high and low. The high and
low of the day are therefore approximate (members peak at different times), and the open is not
forced to equal the previous close. Nothing here is a tradable index; it only describes the day.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from datetime import timedelta

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.returns import MAX_DAY_MOVE, _payout_ids
from tmon.domain.enums import InstrumentType
from tmon.features.adjustment import apply_adjustments
from tmon.storage.models import Instrument, PriceDaily

FLAT = 0.0005  # a move smaller than this counts as "no change" (as on the market page)
HORIZONS = {"week": ("هفته", 7), "month": ("ماه", 30), "m3": ("سه ماه", 90), "year": ("سال", 365)}
SPARK_DAYS = 60
WINDOW_DAYS = 400  # calendar days loaded: a year of returns plus the warm-up of the averages


@dataclass
class Composite:
    """One industry's series; every list has one item per day, oldest first."""

    dates: list[dt.date] = field(default_factory=list)
    open: list[float] = field(default_factory=list)
    high: list[float] = field(default_factory=list)
    low: list[float] = field(default_factory=list)
    close: list[float] = field(default_factory=list)
    members: list[int] = field(default_factory=list)  # symbols that counted that day
    up: list[int] = field(default_factory=list)
    down: list[int] = field(default_factory=list)
    flat: list[int] = field(default_factory=list)


def load_adjusted(
    session: Session, last: dt.date, sector_codes: list[str] | None = None
) -> tuple[pl.DataFrame, dict[int, str]]:
    """Adjusted daily bars of the listed stocks (one sector, or all) and each one's sector code.

    The returned frame has ``instrument_id, date, adj_open, adj_high, adj_low, adj_close, value``.
    """
    since = last - timedelta(days=WINDOW_DAYS)
    q = (
        select(
            PriceDaily.instrument_id,
            Instrument.sector_code,
            PriceDaily.date,
            PriceDaily.open,
            PriceDaily.high,
            PriceDaily.low,
            PriceDaily.close,
            PriceDaily.prev_close,
            PriceDaily.value,
        )
        .join(Instrument, Instrument.id == PriceDaily.instrument_id)
        .where(
            Instrument.instrument_type == InstrumentType.STOCK.value,
            PriceDaily.date >= since,
            PriceDaily.date <= last,
            PriceDaily.market_halt.is_(False),
        )
        .order_by(PriceDaily.instrument_id, PriceDaily.date)
    )
    if sector_codes is not None:
        q = q.where(Instrument.sector_code.in_(sector_codes))
    rows = session.execute(q).all()
    sector = {r[0]: (r[1] or "").strip() for r in rows}
    if not rows:
        return pl.DataFrame(), sector

    def col(i: int) -> list[float | None]:
        return [None if r[i] is None else float(r[i]) for r in rows]  # type: ignore[arg-type]

    raw = pl.DataFrame(
        {
            "instrument_id": [r[0] for r in rows],
            "date": [r[2] for r in rows],
            "open": col(3),
            "high": col(4),
            "low": col(5),
            "close": col(6),
            "prev_close": col(7),
            "value": col(8),
        },
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "prev_close": pl.Float64,
            "value": pl.Float64,
        },
    ).filter(pl.col("close") > 0)
    # a bar missing its open, high or low is as wide as its close
    raw = raw.with_columns(
        pl.col("open").fill_null(pl.col("close")),
        pl.col("high").fill_null(pl.col("close")),
        pl.col("low").fill_null(pl.col("close")),
    )
    adj = apply_adjustments(raw, payout_ids=_payout_ids(session)).select(
        "instrument_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "value"
    )
    return adj, sector


def member_moves(adj: pl.DataFrame) -> pl.DataFrame:
    """Each bar against the same symbol's previous adjusted close (first bars and stale
    reference prices dropped), with the value it traded the day before as its weight."""
    if adj.is_empty():
        return adj
    d = adj.sort(["instrument_id", "date"]).with_columns(
        pc=pl.col("adj_close").shift(1).over("instrument_id"),
        w=pl.col("value").shift(1).over("instrument_id"),
    )
    d = d.filter(pl.col("pc") > 0).with_columns(
        ro=pl.col("adj_open") / pl.col("pc"),
        rh=pl.col("adj_high") / pl.col("pc"),
        rl=pl.col("adj_low") / pl.col("pc"),
        rc=pl.col("adj_close") / pl.col("pc"),
        w=pl.col("w").fill_null(0.0).clip(lower_bound=0.0),
    )
    return d.filter((pl.col("rc") - 1).abs() <= MAX_DAY_MOVE)


def composites(moves: pl.DataFrame, sector: dict[int, str], weight: str) -> dict[str, Composite]:
    """Candles per sector code; ``weight`` is ``"equal"`` or ``"value"``."""
    if moves.is_empty():
        return {}
    d = moves.with_columns(
        pl.Series("sector", [sector.get(i, "") for i in moves["instrument_id"].to_list()])
    )
    wt = pl.col("w") if weight == "value" else pl.lit(1.0)
    g = (
        d.with_columns(_w=wt)
        .group_by(["sector", "date"])
        .agg(
            n=pl.len(),
            sw=pl.col("_w").sum(),
            so=(pl.col("ro") * pl.col("_w")).sum(),
            sh=(pl.col("rh") * pl.col("_w")).sum(),
            sl=(pl.col("rl") * pl.col("_w")).sum(),
            sc=(pl.col("rc") * pl.col("_w")).sum(),
            up=(pl.col("rc") > 1 + FLAT).sum(),
            down=(pl.col("rc") < 1 - FLAT).sum(),
            flat=((pl.col("rc") - 1).abs() <= FLAT).sum(),
            eq_n=pl.len(),
            eq_o=pl.col("ro").sum(),
            eq_h=pl.col("rh").sum(),
            eq_l=pl.col("rl").sum(),
            eq_c=pl.col("rc").sum(),
        )
        .sort(["sector", "date"])
    )
    out: dict[str, Composite] = {}
    for sec in g["sector"].unique().to_list():
        rows = g.filter(pl.col("sector") == sec).to_dicts()
        c = Composite()
        level = 100.0
        for r in rows:
            # a day on which no symbol had value yet weights them all equally
            if weight == "value" and r["sw"] > 0:
                mo, mh, ml, mc = (r[k] / r["sw"] for k in ("so", "sh", "sl", "sc"))
            else:
                mo, mh, ml, mc = (r[k] / r["eq_n"] for k in ("eq_o", "eq_h", "eq_l", "eq_c"))
            o, h, lo, cl = level * mo, level * mh, level * ml, level * mc
            c.dates.append(r["date"])
            c.open.append(o)
            c.high.append(max(h, o, cl))
            c.low.append(min(lo, o, cl))
            c.close.append(cl)
            c.members.append(int(r["n"]))
            c.up.append(int(r["up"]))
            c.down.append(int(r["down"]))
            c.flat.append(int(r["flat"]))
            level = cl
        out[sec] = c
    return out


def horizon_return(c: Composite, last: dt.date, back_days: int) -> float | None:
    """Move of the consensus level over the last ``back_days`` calendar days, or ``None`` when
    the series does not reach back that far (the same rule as the per-symbol period table)."""
    if not c.dates or c.dates[-1] != last:
        return None
    target = last - timedelta(days=back_days)
    base: float | None = None
    for d, cl in zip(c.dates, c.close, strict=True):
        if d <= target:
            base = cl
            if target - d > timedelta(days=10):
                base = None
    if base is None or base <= 0:
        return None
    return c.close[-1] / base - 1.0


def spark(c: Composite, n: int = SPARK_DAYS) -> list[float]:
    """The last ``n`` closes, rebased so the first is 100."""
    tail = c.close[-n:]
    if not tail or tail[0] <= 0:
        return []
    return [round(100.0 * x / tail[0], 3) for x in tail]


@dataclass(frozen=True)
class Trend:
    """Where one symbol's last adjusted close sits against its own averages and year."""

    above_sma20: bool | None
    above_sma50: bool | None
    from_year_high: float | None  # <= 0
    spark: list[float]


def trend_table(adj: pl.DataFrame, last: dt.date) -> dict[int, Trend]:
    """Per symbol that traded on ``last``. An average needs its full window of closes."""
    if adj.is_empty():
        return {}
    t = (
        adj.sort(["instrument_id", "date"])
        .group_by("instrument_id", maintain_order=True)
        .agg(
            n=pl.len(),
            d=pl.col("date").last(),
            c=pl.col("adj_close").last(),
            s20=pl.col("adj_close").tail(20).mean(),
            s50=pl.col("adj_close").tail(50).mean(),
            hi=pl.col("adj_close").tail(250).max(),
            tail=pl.col("adj_close").tail(SPARK_DAYS),
        )
        .filter(pl.col("d") == last)
    )
    out: dict[int, Trend] = {}
    for r in t.to_dicts():
        tail = r["tail"]
        out[int(r["instrument_id"])] = Trend(
            above_sma20=(r["c"] > r["s20"]) if r["n"] >= 20 else None,
            above_sma50=(r["c"] > r["s50"]) if r["n"] >= 50 else None,
            from_year_high=(r["c"] / r["hi"] - 1.0) if r["hi"] else None,
            spark=[round(100.0 * x / tail[0], 3) for x in tail] if tail and tail[0] > 0 else [],
        )
    return out
