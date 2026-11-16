"""Shareholder-meeting reminders for held symbols.

A stock's price usually drops by the dividend on the meeting day, and the owner may want to
decide before it. The portfolio page already shows a banner; this turns the same fact into an
alert so it reaches the messenger channels without opening the page.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tmon.api.routers.dashboard import _meeting
from tmon.portfolio.watch import URGENT, WARN, Finding, HoldingView
from tmon.storage.models import CorporateEvent

WARN_DAYS = 7  # the portfolio page banner uses the same window
URGENT_DAYS = 1  # tomorrow or today: a second, louder push


def meeting_finding(
    p_id: int, holding: HoldingView, kind: str, date: dt.date, days_left: int
) -> Finding | None:
    """The reminder for one holding, or ``None`` while the meeting is still far away."""
    if days_left < 0 or days_left > WARN_DAYS:
        return None
    when = "امروز" if days_left == 0 else "فردا" if days_left == 1 else f"{days_left} روز دیگر"
    return Finding(
        "meeting",
        URGENT if days_left <= URGENT_DAYS else WARN,
        holding.instrument_id,
        f"{kind} {holding.symbol} {when}",
        f"{kind} {holding.symbol} در تاریخ {date.isoformat()} برگزار می‌شود. "
        "اگر سود نقدی تقسیم شود، قیمت بعد از مجمع معمولاً به اندازهٔ آن پایین می‌آید.",
        f"{p_id}:meeting:{holding.instrument_id}:{date.isoformat()}",
        {"date": date.isoformat(), "days_left": days_left},
    )


def meeting_findings(
    session: Session, views: dict[int, list[HoldingView]], today: dt.date
) -> dict[int, list[Finding]]:
    """Reminders per portfolio for the meetings of held symbols within the next week."""
    held = {h.instrument_id for hs in views.values() for h in hs}
    if not held:
        return {}
    events: dict[int, list[CorporateEvent]] = {}
    for e in session.scalars(
        select(CorporateEvent).where(
            CorporateEvent.instrument_id.in_(held),
            or_(CorporateEvent.event_date >= today, CorporateEvent.stage == "meeting_cancelled"),
        )
    ):
        events.setdefault(e.instrument_id, []).append(e)
    out: dict[int, list[Finding]] = {}
    for pid, hs in views.items():
        for h in hs:
            m = _meeting(events.get(h.instrument_id, []), today)
            f = meeting_finding(pid, h, m.kind, m.date, m.days_left) if m else None
            if f:
                out.setdefault(pid, []).append(f)
    return out
