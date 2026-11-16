"""Codal announcements through TSETMC's own feed, for hosts that cannot reach codal.ir.

``cdn.tsetmc.com/api/Codal/GetPreparedData/{top}`` lists the newest Codal letters of the whole
market (checked 2026-11-16, reachable from the VPS where search.codal.ir is not). It has what the
exit watch needs, the tracing number, symbol, title and times, and no letter code or report link, so
a letter that Codal's index already stored keeps its richer row: this feed only adds letters that
are not stored yet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.ingest.codal.parsers import Letter
from tmon.ingest.codal.pipeline import _run, symbol_map
from tmon.ingest.http import FetchError, PoliteClient
from tmon.ingest.tsetmc.parsers import ParseError, normalize_fa
from tmon.storage.models import CodalLetter
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

FEED_URL = "https://cdn.tsetmc.com/api/Codal/GetPreparedData/{top}"


def _local(text: str | None) -> datetime | None:
    """``2026-11-16T15:56:39`` is Tehran wall time; returned as aware UTC."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=TEHRAN).astimezone(UTC)
    except ValueError:
        return None


def parse_feed(payload: bytes | str) -> list[Letter]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseError("TSETMC Codal feed: not JSON") from exc
    if not isinstance(data, dict) or "preparedData" not in data:
        raise ParseError("TSETMC Codal feed: no 'preparedData' key")
    out: list[Letter] = []
    for row in data["preparedData"] or []:
        try:
            out.append(
                Letter(
                    tracing_no=int(row["tracingNo"]),
                    symbol=normalize_fa(row.get("symbol") or ""),
                    company_name=normalize_fa(row.get("name") or ""),
                    title=normalize_fa(row.get("title") or ""),
                    letter_code="",
                    sent_at=_local(row.get("sentDateTime_Gregorian")),
                    published_at=_local(row.get("publishDateTime_Gregorian")),
                    url="",
                    has_html=row.get("hasHtmlReport") == 1,
                    has_excel=row.get("hasExcelReport") == 1,
                    has_pdf=row.get("hasPDFReport") == 1,
                    under_supervision=False,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def store_new(session: Session, letters: list[Letter], url: str, fetched_at: datetime) -> int:
    """Insert the letters that are not stored yet; return how many."""
    if not letters:
        return 0
    ids = [x.tracing_no for x in letters]
    known = set(
        session.scalars(select(CodalLetter.tracing_no).where(CodalLetter.tracing_no.in_(ids)))
    )
    symbols = symbol_map(session)
    rows: list[dict[str, Any]] = [
        {
            "tracing_no": x.tracing_no,
            "instrument_id": symbols.get(x.symbol),
            "symbol": x.symbol,
            "company_name": x.company_name or None,
            "letter_code": None,
            "title": x.title,
            "sent_at": x.sent_at,
            "published_at": x.published_at,
            "url": None,
            "has_html": x.has_html,
            "has_excel": x.has_excel,
            "has_pdf": x.has_pdf,
            "under_supervision": False,
            "source_url": url,
            "fetched_at": fetched_at,
        }
        for x in letters
        if x.tracing_no not in known
    ]
    return upsert(session, CodalLetter, rows)


async def sync_feed(client: PoliteClient, top: int = 200) -> dict[str, int]:
    url = FEED_URL.format(top=top)
    fetched_at = utcnow()
    try:
        resp = await client.get(url)
        letters = parse_feed(resp.content)
    except (FetchError, ParseError) as exc:
        log.warning("codal feed: %s", exc)
        return {"letters": 0, "failed": 1}
    with session_scope() as session:
        n = store_new(session, letters, url, fetched_at)
    return {"letters": n, "seen": len(letters)}


# Codal answers from some hosts and not from others (the VPS cannot connect to it at all). One
# failed fast try is remembered for a while so a tick does not spend minutes retrying a host that
# is known to be unreachable.
RECHECK_SECONDS = 1800.0
_codal_down_until = 0.0


async def _newest(max_pages: int) -> dict[str, int]:
    global _codal_down_until
    if time.monotonic() >= _codal_down_until:
        out = await _run("letters", fail_fast=True, max_pages=max_pages)
        if out.get("pages", 0) > 0:
            return {**out, "via": 1}
        _codal_down_until = time.monotonic() + RECHECK_SECONDS
        log.warning("codal.ir not reachable from here; using the TSETMC Codal feed")
    client = PoliteClient()
    try:
        return {**await sync_feed(client), "via": 2}
    finally:
        await client.aclose()


def run_newest_letters(max_pages: int = 3) -> dict[str, int]:
    """The newest Codal letters from whichever source answers: Codal itself (``via`` 1, with letter
    codes and events), else the TSETMC feed (``via`` 2, letters only)."""
    return asyncio.run(_newest(max_pages))
