"""When the database was last written: per data kind, the newest market date it holds and the
moment that date's rows were fetched. Each lookup reads only the newest date's rows (through the
date index), so it is cheap enough to call on every page."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.core.db import get_session
from tmon.storage.models import (
    ClientTypeDaily,
    CodalLetter,
    MacroSeries,
    MarketIndexDaily,
    ModelRun,
    NewsRaw,
    OrderBookDaily,
    PriceDaily,
)

router = APIRouter(tags=["meta"])
SessionDep = Annotated[Session, Depends(get_session)]


class FreshnessItem(BaseModel):
    kind: str
    date: date | None
    fetched_at: datetime | None


class FreshnessOut(BaseModel):
    updated_at: datetime | None
    items: list[FreshnessItem]


def _utc(t: datetime | None) -> datetime | None:
    """SQLite keeps no zone; every stamp is written in UTC (tmon.core.timeutil.utcnow)."""
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def _dated(s: Session, kind: str, model: Any, col: Any) -> FreshnessItem:
    last = s.scalar(select(func.max(col)))
    at = s.scalar(select(func.max(model.fetched_at)).where(col == last)) if last else None
    d = last.date() if isinstance(last, datetime) else last
    return FreshnessItem(kind=kind, date=d, fetched_at=_utc(at))


@router.get("/freshness", response_model=FreshnessOut)
def freshness(session: SessionDep) -> FreshnessOut:
    items = [
        _dated(session, "prices", PriceDaily, PriceDaily.date),
        _dated(session, "flows", ClientTypeDaily, ClientTypeDaily.date),
        _dated(session, "index", MarketIndexDaily, MarketIndexDaily.date),
        _dated(session, "order_book", OrderBookDaily, OrderBookDaily.date),
        _dated(session, "macro", MacroSeries, MacroSeries.ref_period),
        _dated(session, "news", NewsRaw, NewsRaw.published_at),
        _dated(session, "codal", CodalLetter, CodalLetter.published_at),
    ]
    run = _utc(session.scalar(select(func.max(ModelRun.created_at))))
    items.append(FreshnessItem(kind="model", date=run.date() if run else None, fetched_at=run))
    stamps = [i.fetched_at for i in items if i.fetched_at]
    return FreshnessOut(updated_at=max(stamps) if stamps else None, items=items)
