"""Whether a symbol is trading: the database holds a price row only for days a symbol traded, so
a symbol with no recent row is stopped (halted by the exchange, or simply untraded)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.storage.models import PriceDaily

State = Literal["active", "idle", "halted"]
HALTED_AFTER = 3  # market days without a trade before "idle" becomes "halted"


def market_days(session: Session, n: int = 60) -> list[dt.date]:
    """The latest ``n`` days on which anything traded, newest first."""
    return list(
        session.scalars(
            select(PriceDaily.date).distinct().order_by(PriceDaily.date.desc()).limit(n)
        )
    )


def trade_state(
    session: Session, instrument_id: int, days: list[dt.date]
) -> tuple[State, dt.date | None, int]:
    """``(state, last trade day, market days since it)``."""
    last = session.scalar(
        select(func.max(PriceDaily.date)).where(
            PriceDaily.instrument_id == instrument_id, PriceDaily.volume > 0
        )
    )
    if not days:
        return "active", last, 0
    idle = len(days) if last is None else sum(1 for d in days if d > last)
    if idle == 0:
        return "active", last, 0
    return ("idle" if idle < HALTED_AFTER else "halted"), last, idle
