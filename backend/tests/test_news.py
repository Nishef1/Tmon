"""News pipeline on real feeds (docs/08): parsing, normalisation, clustering, LLM gate."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tmon.ingest.news import pipeline, rss, text
from tmon.ingest.tsetmc.parsers import ParseError
from tmon.storage.models import NewsRaw

FIX = Path(__file__).parent / "fixtures" / "news"


def test_parse_real_feeds():
    bn = rss.parse_feed((FIX / "boursenews.xml").read_bytes(), "boursenews")
    assert len(bn) == 100
    assert all(i.url.startswith("http") and i.title for i in bn)
    assert all(i.published_at is not None and i.published_at.tzinfo for i in bn)
    sena = rss.parse_feed((FIX / "sena.xml").read_bytes(), "sena")
    assert len(sena) == 30
    with pytest.raises(ParseError):
        rss.parse_feed(b"<html>", "x")


def test_normalize_and_shingles():
    assert text.normalize("قيمت ۱۲ سهم كاله") == "قیمت 12 سهم کاله"
    a = text.shingles("افزایش نرخ خوراک پتروشیمی‌ها از ماه آینده")
    b = text.shingles("افزایش نرخ خوراک پتروشیمی‌ها از ماه آینده اعلام شد")
    assert text.jaccard(a, b) >= text.DUPLICATE_JACCARD
    assert text.jaccard(a, text.shingles("شاخص کل امروز سبز شد")) == 0


def test_store_items_dedupes_and_clusters(session):
    now = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)
    mk = lambda u, t: rss.Item("s", u, t, None, now)  # noqa: E731
    items = [
        mk("https://a/1", "افزایش نرخ خوراک پتروشیمی‌ها از ماه آینده"),
        mk("https://b/2", "افزایش نرخ خوراک پتروشیمی‌ها از ماه آینده اعلام شد"),
        mk("https://c/3", "شاخص کل امروز سبز شد"),
    ]
    assert pipeline.store_items(session, items, "https://feed", now) == 3
    assert pipeline.store_items(session, items, "https://feed", now) == 0  # same urls
    rows = {r.url: r for r in session.query(NewsRaw)}
    assert rows["https://b/2"].cluster_id == rows["https://a/1"].id
    assert rows["https://c/3"].cluster_id == rows["https://c/3"].id


def test_llm_step_skipped_without_key(session):
    assert pipeline.extract_events(session, None, "m") == {"skipped": "TMON_LLM_API_KEY not set"}
