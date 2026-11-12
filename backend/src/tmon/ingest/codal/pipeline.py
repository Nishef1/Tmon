"""Codal letter-index ingestion: raw JSON first, then codal_letters and corporate_events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import to_tehran, utcnow
from tmon.ingest.codal import endpoints
from tmon.ingest.codal.events import EVENT_LETTER_CODES, classify_letter
from tmon.ingest.codal.parsers import Letter, SearchPage, parse_search
from tmon.ingest.codal.reports import (
    format_signature,
    is_correction,
    parse_number,
    parse_report,
    period_end,
    row_label,
    subsidiary_of,
)
from tmon.ingest.http import DomainRateLimiter, FetchError, PoliteClient
from tmon.ingest.tsetmc.parsers import ParseError
from tmon.storage.models import (
    CodalLetter,
    CodalReport,
    CodalReportCell,
    CorporateEvent,
    Instrument,
)
from tmon.storage.objectstore import ObjectStore, get_object_store, store_raw_payload
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

SOURCE = "codal"
# When several instruments share a symbol, the listed share is the one Codal letters are about.
_TYPE_PREFERENCE = ("stock", "right")


@dataclass
class CodalCtx:
    session: Session
    client: PoliteClient
    store: ObjectStore

    async def search(self, url: str) -> tuple[SearchPage, datetime]:
        fetched_at = utcnow()
        resp = await self.client.get(url)
        store_raw_payload(
            self.session,
            self.store,
            source=SOURCE,
            source_url=url,
            payload=resp.content,
            fetched_at=fetched_at,
            ext="json",
            content_type="application/json",
        )
        return parse_search(resp.content), fetched_at


def symbol_map(session: Session) -> dict[str, int]:
    """symbol_fa -> instrument id, preferring the share line when a symbol is shared."""
    rank = {t: i for i, t in enumerate(_TYPE_PREFERENCE)}
    best: dict[str, tuple[int, int]] = {}
    for iid, sym, itype in session.execute(
        select(Instrument.id, Instrument.symbol_fa, Instrument.instrument_type)
    ):
        r = rank.get(itype, len(rank))
        if sym not in best or r < best[sym][0]:
            best[sym] = (r, iid)
    return {sym: iid for sym, (_, iid) in best.items()}


def letter_rows(
    letters: list[Letter], symbols: dict[str, int], source_url: str, fetched_at: datetime
) -> list[dict[str, Any]]:
    return [
        {
            "tracing_no": x.tracing_no,
            "instrument_id": symbols.get(x.symbol),
            "symbol": x.symbol,
            "company_name": x.company_name,
            "letter_code": x.letter_code or None,
            "title": x.title,
            "sent_at": x.sent_at,
            "published_at": x.published_at,
            "url": x.url,
            "has_html": x.has_html,
            "has_excel": x.has_excel,
            "has_pdf": x.has_pdf,
            "under_supervision": x.under_supervision,
            "source_url": source_url,
            "fetched_at": fetched_at,
        }
        for x in letters
    ]


def event_rows(
    letters: list[Letter], symbols: dict[str, int], source_url: str, fetched_at: datetime
) -> list[dict[str, Any]]:
    """corporate_events rows for letters about an instrument we know; one row per letter."""
    out = []
    for x in letters:
        kind = classify_letter(x.letter_code, x.title)
        iid = symbols.get(x.symbol)
        if kind is None or iid is None:
            continue
        out.append(
            {
                "tracing_no": x.tracing_no,
                "instrument_id": iid,
                "type": kind.type,
                "stage": kind.stage,
                "title": x.title,
                "announced_at": to_tehran(x.published_at).date() if x.published_at else None,
                "published_at": x.published_at,
                "source": SOURCE,
                "source_url": x.url or source_url,
                "fetched_at": fetched_at,
            }
        )
    return out


def store_page(
    session: Session, page: SearchPage, symbols: dict[str, int], url: str, fetched_at: datetime
) -> tuple[int, int]:
    letters = letter_rows(page.letters, symbols, url, fetched_at)
    events = event_rows(page.letters, symbols, url, fetched_at)
    n_letters = upsert(session, CodalLetter, letters)
    n_events = upsert(session, CorporateEvent, events, conflict_columns=["tracing_no"])
    return n_letters, n_events


async def sync_letters(
    ctx: CodalCtx,
    *,
    symbol: str | None = None,
    letter_code: str | None = None,
    max_pages: int = 1,
    start_page: int = 1,
    stop_at_known: bool = True,
) -> dict[str, int]:
    """Page through the index newest-first until a short page, ``max_pages``, or (with
    ``stop_at_known``) a page whose letters are all stored already.

    Codal answers HTTP 429 once a request quota is used up (about 55 requests in a few minutes
    were enough on 2026-11-11). The run then stops with what it has; ``stopped_at_page`` says
    where to resume with ``start_page``. Every page is committed as it arrives."""
    symbols = symbol_map(ctx.session)
    totals = {"pages": 0, "letters": 0, "events": 0}
    for page_no in range(start_page, start_page + max_pages):
        url = endpoints.search_url(page=page_no, symbol=symbol, letter_code=letter_code)
        try:
            page, fetched_at = await ctx.search(url)
        except FetchError as exc:
            log.warning("codal: stopped at page %d: %s", page_no, exc)
            ctx.session.rollback()
            totals["stopped_at_page"] = page_no
            break
        ids = [x.tracing_no for x in page.letters]
        known = set(
            ctx.session.scalars(
                select(CodalLetter.tracing_no).where(CodalLetter.tracing_no.in_(ids))
            )
        )
        n_letters, n_events = store_page(ctx.session, page, symbols, url, fetched_at)
        ctx.session.commit()
        totals["pages"] += 1
        totals["letters"] += n_letters
        totals["events"] += n_events
        if len(page.letters) < endpoints.PAGE_SIZE:
            break
        if stop_at_known and ids and known.issuperset(ids):
            break
    return totals


async def sync_event_letters(ctx: CodalCtx, *, max_pages: int = 1) -> dict[str, int]:
    """Market-wide scan of every event letter code (newest first)."""
    totals = {"pages": 0, "letters": 0, "events": 0}
    for code in EVENT_LETTER_CODES:
        out = await sync_letters(ctx, letter_code=code, max_pages=max_pages)
        for k in totals:
            totals[k] += out[k]
        if "stopped_at_page" in out:  # quota used up: the next hourly run picks up the rest
            totals["stopped"] = 1
            break
    return totals


def store_report(ctx: CodalCtx, letter: CodalLetter, payload: bytes, url: str) -> int:
    """Keep the raw export, parse it, and replace any earlier parse of the same letter."""
    fetched_at = utcnow()
    raw = store_raw_payload(
        ctx.session,
        ctx.store,
        source=SOURCE,
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
        ext="xls",
        content_type="application/vnd.ms-excel",
    )
    tables = parse_report(payload)
    cells = [
        {
            "tracing_no": letter.tracing_no,
            "table_index": t.index,
            "row_index": r,
            "col_index": c,
            "table_title": t.title,
            "row_label": row_label(row),
            "col_header": t.columns[c] or None,
            "text": text,
            "value": parse_number(text),
        }
        for t in tables
        for r, row in enumerate(t.rows)
        for c, text in enumerate(row)
        if text
    ]
    ctx.session.execute(
        delete(CodalReportCell).where(CodalReportCell.tracing_no == letter.tracing_no)
    )
    upsert(
        ctx.session,
        CodalReport,
        [
            {
                "tracing_no": letter.tracing_no,
                "instrument_id": letter.instrument_id,
                "letter_code": letter.letter_code,
                "period_end": period_end(letter.title),
                "is_correction": is_correction(letter.title),
                "subsidiary": subsidiary_of(letter.title),
                "published_at": letter.published_at,
                "format_signature": format_signature(tables),
                "n_tables": len(tables),
                "n_cells": len(cells),
                "raw_object_key": raw.object_key,
                "source_url": url,
                "fetched_at": fetched_at,
            }
        ],
    )
    upsert(ctx.session, CodalReportCell, cells)
    return len(cells)


async def sync_reports(
    ctx: CodalCtx,
    *,
    letter_code: str,
    symbol: str | None = None,
    limit: int = 10,
) -> dict[str, int]:
    """Fetch and parse the Excel export of stored letters with ``letter_code`` that have no
    parsed report yet, newest first. Stops at the first refusal (429, CAPTCHA) with what it has."""
    q = (
        select(CodalLetter)
        .outerjoin(CodalReport, CodalReport.tracing_no == CodalLetter.tracing_no)
        .where(
            CodalLetter.letter_code == letter_code,
            CodalLetter.has_excel.is_(True),
            CodalReport.tracing_no.is_(None),
        )
        .order_by(CodalLetter.published_at.desc())
        .limit(limit)
    )
    if symbol:
        q = q.where(CodalLetter.symbol == symbol)
    totals = {"reports": 0, "cells": 0, "skipped": 0}
    for letter in ctx.session.scalars(q).all():
        serial = endpoints.letter_serial(letter.url)
        if not serial:
            totals["skipped"] += 1
            continue
        url = endpoints.excel_url(serial)
        try:
            resp = await ctx.client.get(url)
            n = store_report(ctx, letter, resp.content, url)
        except (FetchError, ParseError) as exc:
            log.warning("codal: report %s stopped: %s", letter.tracing_no, exc)
            ctx.session.rollback()
            totals["stopped_at"] = letter.tracing_no
            break
        ctx.session.commit()
        totals["reports"] += 1
        totals["cells"] += n
    return totals


def codal_client() -> PoliteClient:
    s = get_settings()
    limiter = DomainRateLimiter(
        s.http_min_interval_seconds,
        {
            endpoints.SEARCH_HOST: s.codal_min_interval_seconds,
            endpoints.EXCEL_HOST: s.codal_min_interval_seconds,
            "www.codal.ir": s.codal_min_interval_seconds,
        },
    )
    return PoliteClient(limiter=limiter)


async def _run(kind: str, **kwargs: Any) -> dict[str, int]:
    client = codal_client()
    try:
        with session_scope() as session:
            ctx = CodalCtx(session, client, get_object_store())
            if kind == "events":
                return await sync_event_letters(ctx, **kwargs)
            if kind == "reports":
                return await sync_reports(ctx, **kwargs)
            if kind == "meetings":
                from tmon.ingest.codal.meetings import sync_meetings

                return await sync_meetings(ctx)
            return await sync_letters(ctx, **kwargs)
    finally:
        await client.aclose()


def run_letters(**kwargs: Any) -> dict[str, int]:
    return asyncio.run(_run("letters", **kwargs))


def run_reports(**kwargs: Any) -> dict[str, int]:
    return asyncio.run(_run("reports", **kwargs))


def run_meetings() -> dict[str, int]:
    return asyncio.run(_run("meetings"))


def run_events(max_pages: int = 1) -> dict[str, int]:
    return asyncio.run(_run("events", max_pages=max_pages))
