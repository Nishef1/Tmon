"""Leveraged-fund document for the compare page (``tmon.backtest.leveraged_funds``).

``python -m tmon.tools.leveraged_funds`` writes one JSON document (object store key
``v2/leveraged_funds.json``): each leveraged fund's beta, month distribution and drawdown, the
fund types side by side over the last three years, and today's price against the fund's NAV.
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.backtest import leveraged_funds as lf
from tmon.core.db import session_scope
from tmon.domain.enums import InstrumentType as T
from tmon.storage.models import FundNav, Instrument, MarketIndexDaily, PriceDaily
from tmon.storage.objectstore import write_artifact

KEY = "v2/leveraged_funds.json"
TEPIX = "32097828799138957"  # شاخص کل (TSETMC insCode)
TYPE_YEARS = 3
LIQUID_VALUE = 1e10  # rials a day (1 billion toman): below it a fund's closes are not a market
TYPES = (
    (T.ETF_FIXED_INCOME, "درآمد ثابت"),
    (T.ETF_MIXED, "مختلط"),
    (T.ETF_EQUITY, "سهامی"),
    (T.ETF_COMMODITY, "کالایی"),
    (T.ETF_LEVERAGED, "اهرمی"),
)


def _panel(
    session: Session, ids: list[int], start: dt.date | None
) -> tuple[list[dt.date], dict[int, np.ndarray], dict[int, float]]:
    """Closes of ``ids`` on the union of their days (NaN where one had none), and each fund's
    median traded value over its last 60 days."""
    q = select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close, PriceDaily.value).where(
        PriceDaily.instrument_id.in_(ids)
    )
    if start:
        q = q.where(PriceDaily.date >= start)
    rows = session.execute(q.order_by(PriceDaily.date)).all()
    days = sorted({r[1] for r in rows})
    col = {d: i for i, d in enumerate(days)}
    out = {i: np.full(len(days), np.nan) for i in ids}
    values: dict[int, list[float]] = {i: [] for i in ids}
    for iid, d, c, v in rows:
        if c is not None and c > 0:
            out[iid][col[d]] = c
        values[iid].append(float(v or 0.0))
    med = {i: float(np.median(v[-60:])) if v else 0.0 for i, v in values.items()}
    return days, out, med


def _index(session: Session, days: list[dt.date]) -> np.ndarray:
    got = dict(
        session.execute(
            select(MarketIndexDaily.date, MarketIndexDaily.close).where(
                MarketIndexDaily.index_code == TEPIX
            )
        ).all()
    )
    x = np.array([got.get(d, np.nan) for d in days], dtype=float)
    for i in range(1, len(x)):  # a day without an index print carries the last level
        if not np.isfinite(x[i]):
            x[i] = x[i - 1]
    return x


def _nav(session: Session, instrument_id: int) -> tuple[dt.date, float] | None:
    n = session.scalars(
        select(FundNav)
        .where(FundNav.instrument_id == instrument_id, FundNav.cancel_nav.is_not(None))
        .order_by(FundNav.date.desc())
        .limit(1)
    ).first()
    return (n.date, float(n.cancel_nav)) if n and n.cancel_nav else None


def build_document(session: Session) -> dict[str, Any]:
    lev = list(
        session.scalars(
            select(Instrument).where(
                Instrument.instrument_type == T.ETF_LEVERAGED,
                Instrument.id.in_(
                    select(PriceDaily.instrument_id)
                    .group_by(PriceDaily.instrument_id)
                    .having(func.count() >= lf.MIN_DAYS)
                ),
            )
        )
    )
    days, closes, _ = _panel(session, [i.id for i in lev], None)
    ix = _index(session, days)
    funds: list[dict[str, Any]] = []
    for inst in lev:
        row = lf.fund_row(closes[inst.id], ix)
        if row is None:
            continue
        first = days[int(np.argmax(np.isfinite(closes[inst.id])))]
        price = float(closes[inst.id][-1]) if np.isfinite(closes[inst.id][-1]) else None
        nav = _nav(session, inst.id)
        funds.append(
            {
                "instrument_id": inst.id,
                "symbol": inst.symbol_fa,
                "since": str(first),
                **row,
                "price": price,
                "fund_nav": nav[1] if nav else None,
                "nav_date": str(nav[0]) if nav else None,
                "price_over_nav": price / nav[1] if nav and price else None,
            }
        )
    funds.sort(key=lambda f: -f["days"])
    window = days[-1].replace(year=days[-1].year - TYPE_YEARS)
    types: list[dict[str, Any]] = []
    for itype, label in TYPES:
        ids = list(
            session.scalars(select(Instrument.id).where(Instrument.instrument_type == itype))
        )
        _, c3, med = _panel(session, ids, window)
        keep = [i for i in ids if np.isfinite(c3[i]).sum() >= 500 and med[i] > LIQUID_VALUE]
        if not keep:
            continue
        row = lf.basket_row(np.column_stack([c3[i] for i in keep]))
        if row:
            types.append({"type": itype.value, "label": label, **row})
    return {
        "as_of": str(days[-1]) if days else None,
        "since_all": str(days[0]) if days else None,
        "target": lf.TARGET,
        "funds": funds,
        "types": types,
        "type_years": TYPE_YEARS,
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-leveraged-funds")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    with session_scope() as s:
        doc = build_document(s)
    write_artifact(KEY, doc, a.out)
    print(f"as_of={doc['as_of']} funds={len(doc['funds'])} types={len(doc['types'])}")


if __name__ == "__main__":
    main()
