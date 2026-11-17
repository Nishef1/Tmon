"""Dividend per share of an assembly, read from the body of its Codal decisions letter (ن-۵۲).

The letter index only says that decisions were published; the approved dividend is in the
letter's HTML, in the row ``DividendPerShare`` of the profit-appropriation table: the input of
the ``CurrentPeriod`` column holds the rial amount (``value="800"``). It is stored in
``corporate_events.dps`` of the decisions event. Corrections («اصلاحیه») are separate letters,
so one fiscal year can have several rows.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy import select

from tmon.core.timeutil import utcnow
from tmon.ingest.codal.parsers import ascii_digits
from tmon.ingest.http import FetchError
from tmon.storage.models import CodalLetter, CorporateEvent
from tmon.storage.objectstore import store_raw_payload

log = logging.getLogger(__name__)

DECISION_STAGE = "decisions"
_ROW = re.compile(r"PropertyName\">\s*DividendPerShare\s*</td>(.*?)</tr>", re.DOTALL)
_INPUT = re.compile(r"<input\b[^>]*\bCurrentPeriod\b[^>]*>", re.DOTALL)
_VALUE = re.compile(r"\bvalue=\"([^\"]*)\"")


_CAPTCHA_MARK = "captchaCode"


def is_captcha(html: str) -> bool:
    """Codal answers 200 with a «تأیید کاربر» CAPTCHA page when it throttles a client. It is not a
    letter and is never solved here."""
    return _CAPTCHA_MARK in html


def parse_dps(html: str) -> float | None:
    """The approved dividend per share (rial) in a decisions letter, or None when the letter has no
    such row or the cell is empty (the company proposed no dividend or left the cell blank)."""
    row = _ROW.search(html)
    if row is None:
        return None
    field = _INPUT.search(row.group(1))
    if field is None:
        return None
    value = _VALUE.search(field.group(0))
    if value is None:
        return None
    text = ascii_digits(value.group(1)).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


async def sync_dividends(  # type: ignore[no-untyped-def]
    ctx, *, symbol: str | None = None, since: date | None = None, limit: int = 200
) -> dict[str, int]:
    """Read the dividend of every stored decisions letter that has none yet, newest first and
    corrections («اصلاحیه») last, so a small budget covers the original letters. Stops at
    the first refusal (429, CAPTCHA) with what it has. ``read`` counts letters whose page was
    fetched, ``found`` those that gave a number. ``since`` skips older letters."""
    stmt = (
        select(CorporateEvent, CodalLetter.url)
        .join(CodalLetter, CodalLetter.tracing_no == CorporateEvent.tracing_no)
        .where(
            CorporateEvent.stage == DECISION_STAGE,
            CorporateEvent.dps.is_(None),
        )
        .order_by(CorporateEvent.title.like("%اصلاحیه%"), CorporateEvent.announced_at.desc())
    )
    if symbol:
        stmt = stmt.where(CodalLetter.symbol == symbol)
    if since:
        stmt = stmt.where(CorporateEvent.announced_at >= since)
    totals = {"read": 0, "found": 0, "no_dps": 0}
    for event, url in ctx.session.execute(stmt.limit(limit)).all():
        if not url:
            totals["no_dps"] += 1
            continue
        fetched_at: datetime = utcnow()
        try:
            resp = await ctx.client.get(url)
        except FetchError as exc:
            log.warning("codal: decisions %s stopped: %s", event.tracing_no, exc)
            totals["stopped_at"] = event.tracing_no or 0
            break
        if is_captcha(resp.text):
            log.warning("codal: CAPTCHA at %s, stopping", event.tracing_no)
            totals["captcha"] = 1
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
        dps = parse_dps(resp.text)
        totals["read"] += 1
        if dps is None:
            totals["no_dps"] += 1
        else:
            event.dps = dps
            totals["found"] += 1
        ctx.session.commit()
    return totals


__all__ = ["DECISION_STAGE", "is_captcha", "parse_dps", "sync_dividends"]
