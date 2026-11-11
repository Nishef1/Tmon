"""News run: fetch feeds (raw payload first), store new items with normalised titles, cluster
duplicates, and run the LLM step only when a key is configured."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import utcnow
from tmon.ingest.http import PoliteClient
from tmon.ingest.news import rss, text
from tmon.storage.models import NewsEvent, NewsRaw
from tmon.storage.objectstore import ObjectStore, get_object_store, store_raw_payload

log = logging.getLogger(__name__)
CLUSTER_WINDOW = dt.timedelta(days=3)
LLM_BATCH = 20


def store_items(session: Session, items: list[rss.Item], url: str, fetched_at: dt.datetime) -> int:
    """Insert items not seen before; each joins the cluster of a recent near-duplicate title."""
    known = set(session.scalars(select(NewsRaw.url).where(NewsRaw.url.in_([i.url for i in items]))))
    recent = [
        (r.cluster_id or r.id, text.shingles(r.title_norm))
        for r in session.scalars(
            select(NewsRaw).where(NewsRaw.fetched_at >= fetched_at - CLUSTER_WINDOW)
        )
    ]
    n = 0
    for it in items:
        if it.url in known:
            continue
        known.add(it.url)
        norm = text.normalize(it.title)
        sh = text.shingles(norm)
        cluster = next(
            (c for c, other in recent if text.jaccard(sh, other) >= text.DUPLICATE_JACCARD), None
        )
        row = NewsRaw(
            source=it.source,
            url=it.url,
            title=it.title,
            summary=it.summary,
            published_at=it.published_at,
            title_norm=norm,
            cluster_id=cluster,
            source_url=url,
            fetched_at=fetched_at,
        )
        session.add(row)
        session.flush()
        if cluster is None:
            row.cluster_id = row.id
        recent.append((row.cluster_id or row.id, sh))
        n += 1
    return n


def extract_events(session: Session, api_key: str | None, model: str) -> dict[str, Any]:
    if not api_key:
        return {"skipped": "TMON_LLM_API_KEY not set"}
    from tmon.ingest.news import llm

    done = select(NewsEvent.news_id)
    heads = session.scalars(
        select(NewsRaw)
        .where(NewsRaw.id == NewsRaw.cluster_id, NewsRaw.id.not_in(done))
        .order_by(NewsRaw.id.desc())
        .limit(LLM_BATCH)
    ).all()
    stored = failed = 0
    for h in heads:
        try:
            ev = llm.extract(api_key, model, h.title_norm, h.summary)
        except Exception as exc:
            log.warning("news llm failed for %s: %s", h.id, exc)
            failed += 1
            continue
        if ev is None:
            failed += 1
            continue
        session.add(
            NewsEvent(
                news_id=h.id,
                event_type=ev.event_type,
                symbols=[text.normalize(s) for s in ev.symbols],
                sectors=ev.sectors,
                direction=ev.direction,
                magnitude=ev.magnitude,
                confidence=ev.confidence,
                effective_from=ev.effective_from,
                horizon=ev.horizon,
                is_official=ev.is_official,
                summary_fa=ev.summary_fa,
                model=model,
                created_at=utcnow(),
            )
        )
        stored += 1
    return {"events": stored, "failed": failed}


async def fetch_feeds(session: Session, client: PoliteClient, store: ObjectStore) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for source, url in rss.FEEDS.items():
        try:
            fetched_at = utcnow()
            resp = await client.get(url)
            store_raw_payload(
                session,
                store,
                source=f"news-{source}",
                source_url=url,
                payload=resp.content,
                fetched_at=fetched_at,
                ext="xml",
                content_type="application/rss+xml",
            )
            out[source] = store_items(
                session, rss.parse_feed(resp.content, source), url, fetched_at
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            log.warning("news %s failed: %s", source, exc)
            out[source] = {"error": str(exc)[:200]}
    return out


async def _run() -> dict[str, Any]:
    settings = get_settings()
    client = PoliteClient()
    try:
        with session_scope() as session:
            out = {"feeds": await fetch_feeds(session, client, get_object_store())}
            out["llm"] = extract_events(session, settings.llm_api_key, settings.llm_model)
            session.commit()
    finally:
        await client.aclose()
    return out


def run_news() -> dict[str, Any]:
    return asyncio.run(_run())


if __name__ == "__main__":
    from tmon.core.logging import configure_logging

    configure_logging()
    print(run_news())
