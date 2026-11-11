"""RSS feeds checked from this machine on 2026-11-12 (OPEN_QUESTIONS 81) and their parser."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from tmon.ingest.tsetmc.parsers import ParseError

FEEDS: dict[str, str] = {
    "sena": "https://www.sena.ir/rss",
    "boursenews": "https://www.boursenews.ir/fa/rss/allnews",
    "irna": "https://www.irna.ir/rss",
    "donya": "https://www.donya-e-eqtesad.com/fa/rss/allnews",
}


@dataclass(frozen=True)
class Item:
    source: str
    url: str
    title: str
    summary: str | None
    published_at: dt.datetime | None


def _date(text: str | None) -> dt.datetime | None:
    if not text or not text.strip():
        return None
    try:
        d = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        return None
    return d.astimezone(dt.UTC) if d.tzinfo else None


def parse_feed(payload: bytes, source: str) -> list[Item]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ParseError(f"{source}: not an RSS document: {exc}") from exc
    out: list[Item] = []
    for it in root.iter("item"):
        url = (it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        if not url or not title:
            continue
        summary = (it.findtext("description") or "").strip() or None
        out.append(Item(source, url, title, summary, _date(it.findtext("pubDate"))))
    if not out and root.find(".//channel") is None:
        raise ParseError(f"{source}: no channel in feed")
    return out
