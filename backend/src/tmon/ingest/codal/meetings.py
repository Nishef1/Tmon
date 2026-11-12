"""Date of a general assembly, read from the body of its Codal invitation letter.

The letter index (``codal_letters``) only says that an invitation was published; the day the
assembly meets is in the letter's HTML, in a sentence like «در ساعت 10:00 روز دوشنبه مورخ
1405/09/02». The date is stored in ``corporate_events.event_date`` of the invitation event.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from tmon.core.timeutil import from_jalali, to_tehran, utcnow
from tmon.ingest.codal import endpoints
from tmon.ingest.codal.parsers import ascii_digits
from tmon.ingest.http import FetchError
from tmon.storage.models import CodalLetter, CorporateEvent
from tmon.storage.objectstore import store_raw_payload

log = logging.getLogger(__name__)

INVITATION_STAGES = ("invitation", "egm_invitation", "ordinary_extraordinary_invitation")
# how far back an invitation is still worth reading: older assemblies have already met
LOOKBACK_DAYS = 45

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[\s ‌]+")
_DATE = r"(1[34]\d{2})/(\d{1,2})/(\d{1,2})"
# the sentence naming the meeting: «... ساعت 10:00 روز دوشنبه مورخ 1405/09/02»
_MEETING = re.compile(r"(?:ساعت\s*(\d{1,2}:\d{2})\s*)?(?:روز\s*\S+\s*)?مورخ\s*" + _DATE)


@dataclass(frozen=True)
class Meeting:
    day: date
    clock: str | None


def parse_meeting(html: str) -> Meeting | None:
    """The date (and hour, when stated) of the assembly in an invitation letter, or None when the
    letter does not say. Only the part after «زمان و محل» is read, so the financial period the
    agenda mentions (``منتهی به 1405/05/31``) is never mistaken for the meeting day."""
    text = _SPACE.sub(" ", ascii_digits(_TAG.sub(" ", html.replace("&nbsp;", " "))))
    start = text.find("زمان و محل")
    if start < 0:
        return None
    end = text.find("دستور جلسه", start)
    chunk = text[start : end if end > 0 else start + 1500]
    for m in _MEETING.finditer(chunk):
        y, mo, d = int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            return Meeting(from_jalali(y, mo, d), m.group(1))
        except ValueError:
            continue
    return None


async def sync_meetings(ctx) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Read the assembly date of every recent invitation that has none yet. Stops at the first
    refusal (429, CAPTCHA) with what it has."""
    today = to_tehran(utcnow()).date()
    rows = ctx.session.execute(
        select(CorporateEvent, CodalLetter.url)
        .join(CodalLetter, CodalLetter.tracing_no == CorporateEvent.tracing_no)
        .where(
            CorporateEvent.stage.in_(INVITATION_STAGES),
            CorporateEvent.event_date.is_(None),
            CorporateEvent.announced_at >= today - timedelta(days=LOOKBACK_DAYS),
        )
        .order_by(CorporateEvent.announced_at.desc())
    ).all()
    totals = {"found": 0, "no_date": 0}
    for event, url in rows:
        if not url:
            totals["no_date"] += 1
            continue
        fetched_at: datetime = utcnow()
        try:
            resp = await ctx.client.get(url)
        except FetchError as exc:
            log.warning("codal: invitation %s stopped: %s", event.tracing_no, exc)
            totals["stopped_at"] = event.tracing_no or 0
            break
        store_raw_payload(
            ctx.session,
            ctx.store,
            source="codal",
            source_url=url,
            payload=resp.content,
            fetched_at=fetched_at,
            ext="html",
            content_type="text/html",
        )
        meeting = parse_meeting(resp.text)
        if meeting is None:
            totals["no_date"] += 1
        else:
            event.event_date = meeting.day
            totals["found"] += 1
        ctx.session.commit()
    return totals


__all__ = ["INVITATION_STAGES", "Meeting", "endpoints", "parse_meeting", "sync_meetings"]
