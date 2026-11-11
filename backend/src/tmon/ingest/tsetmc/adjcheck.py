"""Verify our price adjustment against TSETMC's own adjusted series (OPEN_QUESTIONS, M1/M2).

Our adjusted close is derived from the raw bars (``features.adjustment``). TSETMC serves its own
adjusted series (``Financial.aspx?t=ph&a=1``, integer-rounded). For each symbol the relative
difference of the final price is computed over the dates both have; the source rounds prices to
whole rials, so rows where rounding alone can exceed the tolerance (price below ``min_price``) are
reported separately instead of being counted as adjustment errors."""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl
from sqlalchemy import func, select

from tmon.core.timeutil import utcnow
from tmon.features.adjustment import apply_adjustments
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import Instrument, PriceDaily

log = logging.getLogger(__name__)

SYMBOLS = [
    "فملی",
    "فولاد",
    "وبملت",
    "فزر",
    "وتجارت",
    "شستا",
    "خودرو",
    "تاصیکو",
    "ومعادن",
    "ساحل",
    "تاپیکو",
    "ستاره",
    "شپدیس",
    "خساپا",
    "وبصادر",
    "کگل",
    "ذوب",
    "وغدیر",
    "ونوین",
    "صبا",
]
TOLERANCE = 0.005  # acceptance: max error <= 0.5%
MIN_PRICE = 200.0  # whole-rial rounding of the source is <= 0.25% at or above this adjusted price


def _pick(ctx: Ctx, symbol: str) -> Instrument | None:
    """The instrument with that symbol that has the most stored bars."""
    rows = ctx.session.execute(
        select(Instrument, func.count(PriceDaily.date))
        .join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
        .where(Instrument.symbol_fa == symbol)
        .group_by(Instrument.id)
        .order_by(func.count(PriceDaily.date).desc())
    ).first()
    return rows[0] if rows else None


def compare(ours: pl.DataFrame, theirs: pl.DataFrame) -> pl.DataFrame:
    """``ours``: date, adj_close. ``theirs``: date, close. Returns per-date relative error."""
    return (
        ours.join(theirs, on="date", how="inner")
        .filter((pl.col("close") > 0) & (pl.col("adj_close") > 0))
        .with_columns(((pl.col("adj_close") / pl.col("close")) - 1.0).abs().alias("err"))
    )


async def run_check(ctx: Ctx, out: str) -> dict[str, int]:
    lines = [
        "| symbol | days compared | adjustment events (ours) | max error | on | "
        "max error, price ≥ 200 | median error | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    ok = bad = missing = 0
    for sym in SYMBOLS:
        ins = _pick(ctx, sym)
        if ins is None:
            lines.append(f"| {sym} | 0 | - | - | - | - | - | not in database |")
            missing += 1
            continue
        text, _ = await ctx.fetch_text(endpoints.adjusted_history_url(ins.ins_code), ext="txt")
        theirs = pl.DataFrame(
            [(b.day, b.close) for b in parsers.parse_adjusted_history(text)],
            schema={"date": pl.Date, "close": pl.Float64},
            orient="row",
        )
        rows = ctx.session.execute(
            select(
                PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close, PriceDaily.prev_close
            )
            .where(PriceDaily.instrument_id == ins.id)
            .order_by(PriceDaily.date)
        ).all()
        raw = pl.DataFrame(
            {
                "instrument_id": [r[0] for r in rows],
                "date": [r[1] for r in rows],
                "close": [float(r[2] or 0.0) for r in rows],
                "prev_close": [float(r[3] or 0.0) for r in rows],
            }
        )
        adj = apply_adjustments(raw)
        n_events = int((adj["adj_factor_cum"].diff().fill_null(0.0) != 0).sum())
        cmp = compare(adj.select("date", "adj_close"), theirs)
        if cmp.is_empty():
            lines.append(f"| {sym} | 0 | {n_events} | - | - | - | - | no overlap |")
            missing += 1
            continue
        worst = cmp.sort("err", descending=True).row(0, named=True)
        big = cmp.filter(pl.col("close") >= MIN_PRICE)
        worst_big = float(big["err"].max()) if not big.is_empty() else float("nan")  # type: ignore[arg-type]
        verdict = "ok" if worst_big <= TOLERANCE else "EXCEPTION"
        ok += verdict == "ok"
        bad += verdict != "ok"
        lines.append(
            f"| {sym} | {cmp.height} | {n_events} | {worst['err']:.3%} | {worst['date']} | "
            f"{worst_big:.3%} | {float(cmp['err'].median()):.3%} | {verdict} |"  # type: ignore[arg-type]
        )
    body = (
        "# Price adjustment check against TSETMC's own adjusted series\n\n"
        f"Generated {utcnow():%Y-%m-%d} by `tmon.ingest.tsetmc.cli adjustment-check`. "
        "Reference: `Financial.aspx?t=ph&a=1` (adjusted, integer-rounded) vs our adjusted final "
        "price derived from the raw bars (`features/adjustment.py`, reference-price gaps).\n\n"
        f"Acceptance: max error ≤ {TOLERANCE:.1%} on every symbol. The source rounds prices to "
        f"whole rials, so a row whose adjusted price is below {MIN_PRICE:.0f} can differ by up to "
        'that rounding alone; the column "max error, price ≥ 200" excludes those rows and '
        'decides the verdict, the column "max error" shows everything.\n\n'
        + "\n".join(lines)
        + f"\n\nSymbols ok: {ok}, exceptions: {bad}, missing: {missing}.\n"
    )
    Path(out).write_text(body, encoding="utf-8")
    return {"ok": ok, "exceptions": bad, "missing": missing}
