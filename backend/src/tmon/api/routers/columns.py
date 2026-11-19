"""Derived columns: the catalog, one symbol's full table and the market block.

The values come from ``tmon.features.columns`` and are display-only; no verdict or weight reads
them (OPEN_QUESTIONS 138)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.market import _latest_full
from tmon.api.schemas import (
    ColumnCatalog,
    ColumnDef,
    ColumnGroup,
    ColumnItem,
    ColumnSection,
    InstrumentColumns,
    MarketBlock,
)
from tmon.core.db import get_session
from tmon.features import columns as cols
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily

router = APIRouter(tags=["columns"])
SessionDep = Annotated[Session, Depends(get_session)]

DATASET_EDGE = "2001-04-30"  # our prices start in March 2001, so an earlier listing looks like this


def last_day(session: Session) -> dt.date | None:
    return session.scalar(select(func.max(PriceDaily.date)))


def table_for(session: Session) -> cols.Table | None:
    """The derived columns on the latest price day, with flows of the latest full-coverage day."""
    last = last_day(session)
    if last is None:
        return None
    return cols.compute(session, last, _latest_full(session, ClientTypeDaily.date))


def numeric_keys() -> list[str]:
    return [c.key for c in cols.CATALOG if c.kind != "text"]


@router.get("/columns/catalog", response_model=ColumnCatalog)
def catalog() -> ColumnCatalog:
    return ColumnCatalog(
        groups=[ColumnGroup(key=k, label=v) for k, v in cols.GROUPS.items()],
        columns=[ColumnDef(**vars(c)) for c in cols.CATALOG],
    )


@router.get("/columns/market", response_model=MarketBlock)
def market_block(session: SessionDep) -> MarketBlock:
    t = table_for(session)
    if t is None:
        return MarketBlock()
    return MarketBlock.model_validate(cols.market_summary(session, t))


@router.get("/instruments/{instrument_id}/columns", response_model=InstrumentColumns)
def instrument_columns(instrument_id: int, session: SessionDep) -> InstrumentColumns:
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "instrument not found")
    t = table_for(session)
    row = None if t is None else t.rows.get(instrument_id)
    if t is None or row is None:
        return InstrumentColumns(instrument_id=instrument_id, available=False)
    row = {**row, **cols.listing(session, instrument_id)}
    first = row.get("first_day")
    sector = t.sectors.get(instrument_id)
    peers = [
        r for i, r in t.rows.items() if i != instrument_id and sector and t.sectors[i] == sector
    ]
    keys = numeric_keys()
    ind_med = cols.medians(peers, keys)
    mkt_med = cols.medians(list(t.rows.values()), keys)
    has_stmt = row.get("statement_kind") is not None
    sections: list[ColumnSection] = []
    for gkey, glabel in cols.GROUPS.items():
        items: list[ColumnItem] = []
        for c in cols.CATALOG:
            if c.group != gkey:
                continue
            hint = c.hint
            if c.key == "first_day" and isinstance(first, str) and first <= DATASET_EDGE:
                hint = "اولین روز داده‌ی ماست؛ نماد ممکن است قبل‌تر هم معامله شده باشد"
            items.append(
                ColumnItem(
                    key=c.key,
                    label=c.label,
                    kind=c.kind,
                    hint=hint,
                    value=row.get(c.key),
                    industry_median=ind_med.get(c.key),
                    market_median=mkt_med.get(c.key),
                )
            )
        note = None
        if gkey in ("growth", "margins", "balance", "multiples") and not has_stmt:
            note = cols.NO_STMT
        if gkey == "book" and all(i.value is None for i in items):
            note = cols.NO_BOOK
        if items:
            sections.append(ColumnSection(key=gkey, label=glabel, items=items, note=note))
    kind = row.get("statement_kind")
    end = row.get("statement_period_end")
    return InstrumentColumns(
        instrument_id=instrument_id,
        available=True,
        as_of=t.as_of.isoformat(),
        flow_date=t.flow_date.isoformat() if t.flow_date else None,
        book_date=t.book_date.isoformat() if t.book_date else None,
        statement_kind=kind if isinstance(kind, str) else None,
        statement_period_end=end if isinstance(end, str) else None,
        sections=sections,
    )
