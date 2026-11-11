"""Macro ingestion: raw payload first, then ``macro_series`` / ``fund_nav``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.db import session_scope
from tmon.core.timeutil import utcnow
from tmon.ingest.http import PoliteClient
from tmon.ingest.macro import fipiran, inflation, tgju
from tmon.storage.models import FundNav, Instrument, MacroSeries
from tmon.storage.objectstore import ObjectStore, get_object_store, store_raw_payload
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)


async def sync_tgju(session: Session, client: PoliteClient, store: ObjectStore) -> dict[str, int]:
    out: dict[str, int] = {}
    for series, key in tgju.SERIES.items():
        url = tgju.url(key)
        fetched_at = utcnow()
        resp = await client.get(url)
        store_raw_payload(
            session,
            store,
            source=tgju.SOURCE,
            source_url=url,
            payload=resp.content,
            fetched_at=fetched_at,
            ext="json",
            content_type="application/json",
        )
        bars = tgju.parse_history(resp.content)
        out[series] = upsert(
            session,
            MacroSeries,
            [
                {
                    "series": series,
                    "source": tgju.SOURCE,
                    "ref_period": b.date,
                    "value": b.close,
                    # a market price is public the day it prints
                    "release_date": b.date,
                    "meta": {"open": b.open, "low": b.low, "high": b.high, "jalali": b.jalali},
                    "source_url": url,
                    "fetched_at": fetched_at,
                }
                for b in bars
            ],
        )
    return out


async def sync_funds(session: Session, client: PoliteClient, store: ObjectStore) -> dict[str, int]:
    fetched_at = utcnow()
    resp = await client.post(fipiran.COMPARE_URL, json={})
    store_raw_payload(
        session,
        store,
        source=fipiran.SOURCE,
        source_url=fipiran.COMPARE_URL,
        payload=resp.content,
        fetched_at=fetched_at,
        ext="json",
        content_type="application/json",
    )
    rows = fipiran.parse_compare(resp.content)
    codes = {r.ins_code for r in rows if r.ins_code}
    ids = dict(
        session.execute(
            select(Instrument.ins_code, Instrument.id).where(Instrument.ins_code.in_(codes))
        ).all()
    )
    n = upsert(
        session,
        FundNav,
        [
            {
                "reg_no": r.reg_no,
                "date": r.date,
                "name": r.name,
                "ins_code": r.ins_code,
                "instrument_id": ids.get(r.ins_code) if r.ins_code else None,
                "fund_type": r.fund_type,
                "type_of_invest": r.type_of_invest,
                "cancel_nav": r.cancel_nav,
                "issue_nav": r.issue_nav,
                "statistical_nav": r.statistical_nav,
                "net_asset": r.net_asset,
                "source_url": fipiran.COMPARE_URL,
                "fetched_at": fetched_at,
            }
            for r in rows
        ],
    )
    return {"funds": n, "linked": sum(1 for r in rows if r.ins_code and r.ins_code in ids)}


def import_inflation(session: Session, path: Path) -> int:
    rows = inflation.parse_csv(path.read_text(encoding="utf-8"))
    now = utcnow()
    return upsert(
        session,
        MacroSeries,
        [
            {
                **{k: v for k, v in r.items() if k != "source_url"},
                "meta": {"import": path.name},
                "source_url": r["source_url"],
                "fetched_at": now,
            }
            for r in rows
        ],
    )


async def _run() -> dict[str, Any]:
    client = PoliteClient()
    out: dict[str, Any] = {}
    try:
        with session_scope() as session:
            store = get_object_store()
            # each source on its own: one being down must not stop the other
            for name, fn in (("tgju", sync_tgju), ("funds", sync_funds)):
                try:
                    out[name] = await fn(session, client, store)
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    log.warning("macro %s failed: %s", name, exc)
                    out[name] = {"error": str(exc)[:200]}
    finally:
        await client.aclose()
    return out


def run_macro() -> dict[str, Any]:
    return asyncio.run(_run())
