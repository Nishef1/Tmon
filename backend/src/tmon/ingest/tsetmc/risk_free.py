"""Risk-free rate from Iranian treasury bills (اخزا), ADR 0002 section 6.

Each day the bill whose remaining life is nearest to one year (and at least
``rf_min_days_to_maturity``) gives the yield to maturity from its final price:
``(face / price) ** (365 / days) - 1``. The series is stored in ``macro_series`` with its source.

Maturity comes from the Persian name suffix (``...-060615`` = Jalali yymmdd); the Latin ticker of
the same instrument carries the Gregorian date (``TreasuryBill270906``) and the two agree. Only
bills still listed can be read, so the series starts with the earliest listed bill's history."""

from __future__ import annotations

import logging
import re
from datetime import date

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import from_jalali
from tmon.ingest.tsetmc.pipeline import Ctx, ingest_history
from tmon.storage.models import Instrument, MacroSeries, PriceDaily
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

SERIES = "rf_1y_ytm"
SOURCE = "tsetmc:treasury-bills"
_SYMBOL = re.compile(r"^اخزا\d{3,4}$")
_NAME_DATE = re.compile(r"(\d{2})(\d{2})(\d{2})$")


def maturity_from_name(name_fa: str | None) -> date | None:
    """Jalali ``yymmdd`` suffix of a bill name -> Gregorian maturity date (None if absent)."""
    m = _NAME_DATE.search((name_fa or "").strip())
    if not m:
        return None
    yy, mm, dd = (int(g) for g in m.groups())
    try:
        return from_jalali(1400 + yy, mm, dd)
    except ValueError:
        return None


def treasury_bills(session: Session) -> list[Instrument]:
    return [
        i
        for i in session.scalars(select(Instrument))
        if _SYMBOL.match(i.symbol_fa or "") and maturity_from_name(i.name_fa) is not None
    ]


async def ingest_treasury_bills(ctx: Ctx, *, since: date | None = None) -> dict[str, int]:
    """Fetch the price history of every listed treasury bill (no client-type data exists)."""
    out = {"bills": 0, "bars": 0, "failed": 0}
    for bill in treasury_bills(ctx.session):
        try:
            stats = await ingest_history(ctx, bill, since=since, with_client_types=False)
        except Exception as exc:  # one bad bill must not stop the rest
            ctx.session.rollback()
            out["failed"] += 1
            log.error("bill %s failed: %s", bill.symbol_fa, exc)
            continue
        ctx.session.commit()
        out["bills"] += 1
        out["bars"] += stats["bars"]
    return out


def yield_to_maturity(price: pl.Expr, face: float, days: pl.Expr) -> pl.Expr:
    """Effective annual yield of a zero-coupon bill (actual/365)."""
    return (face / price).pow(365.0 / days) - 1.0


def compute_risk_free(session: Session) -> int:
    """(Re)build the daily one-year yield series from stored bill prices; returns rows written."""
    cfg = get_engine_config().benchmarks
    if cfg.treasury_bill_face_value is None:
        raise RuntimeError("benchmarks.treasury_bill_face_value is not configured")
    bills = {i.id: (i.symbol_fa, maturity_from_name(i.name_fa)) for i in treasury_bills(session)}
    if not bills:
        return 0
    rows = session.execute(
        select(
            PriceDaily.instrument_id,
            PriceDaily.date,
            PriceDaily.close,
            PriceDaily.volume,
            PriceDaily.source_url,
            PriceDaily.fetched_at,
        ).where(PriceDaily.instrument_id.in_(list(bills)))
    ).all()
    if not rows:
        return 0
    meta = pl.DataFrame(
        {
            "instrument_id": list(bills),
            "bill": [v[0] for v in bills.values()],
            "maturity": [v[1] for v in bills.values()],
        }
    )
    df = (
        pl.DataFrame(
            {
                "instrument_id": [r[0] for r in rows],
                "date": [r[1] for r in rows],
                "close": [float(r[2] or 0.0) for r in rows],
                "volume": [float(r[3] or 0) for r in rows],
                "source_url": [r[4] for r in rows],
                "fetched_at": [r[5] for r in rows],
            }
        )
        .join(meta, on="instrument_id")
        .with_columns((pl.col("maturity") - pl.col("date")).dt.total_days().alias("days"))
        .filter(
            (pl.col("close") > 0)
            & (pl.col("volume") > 0)
            & (pl.col("days") >= cfg.rf_min_days_to_maturity)
        )
        .with_columns(
            yield_to_maturity(pl.col("close"), cfg.treasury_bill_face_value, pl.col("days")).alias(
                "ytm"
            ),
            (pl.col("days") - cfg.rf_target_days).abs().alias("gap"),
        )
        .sort(["date", "gap", "volume"], descending=[False, False, True])
        .unique(subset="date", keep="first", maintain_order=True)
    )
    return upsert(
        session,
        MacroSeries,
        [
            {
                "series": SERIES,
                "source": SOURCE,
                "ref_period": r["date"],
                "value": r["ytm"],
                "release_date": r["date"],
                "meta": {
                    "bill": r["bill"],
                    "days_to_maturity": r["days"],
                    "price": r["close"],
                    "face": cfg.treasury_bill_face_value,
                },
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
            }
            for r in df.iter_rows(named=True)
        ],
    )
