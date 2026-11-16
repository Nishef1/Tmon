"""Codal letters through TSETMC's feed (the VPS cannot reach codal.ir): parsing, storing only new
letters, and the choice of source. Fixture captured from cdn.tsetmc.com on 2026-11-16."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from tmon.ingest.codal import tsetmc_feed
from tmon.ingest.codal.tsetmc_feed import parse_feed, store_new
from tmon.storage.models import CodalLetter, Instrument

BODY = (Path(__file__).parent / "fixtures" / "codal" / "tsetmc_feed_25.json").read_bytes()


def test_parse_feed_reads_letters_and_tehran_times():
    letters = parse_feed(BODY)
    assert len(letters) == 25
    first = letters[0]
    assert first.tracing_no == 1635959
    assert first.symbol == "صنم"
    assert first.letter_code == "" and first.url == ""
    # 2026-11-16T15:56:39 Tehran wall time is 12:26:39 UTC (+03:30)
    assert first.published_at == datetime(2026, 11, 16, 12, 26, 39, tzinfo=UTC)
    assert len({x.tracing_no for x in letters}) == 25


def test_store_adds_only_letters_not_stored_yet(session):
    share = Instrument(ins_code="1", symbol_fa="وسپاهان", instrument_type="stock")
    session.add(share)
    session.flush()
    rich = CodalLetter(
        tracing_no=1635983,
        instrument_id=share.id,
        symbol="وسپاهان",
        letter_code="ن-۱۰",
        title="from codal itself",
        url="https://www.codal.ir/x",
        source_url="codal",
        fetched_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    session.add(rich)
    session.commit()
    letters = parse_feed(BODY)
    now = datetime(2026, 11, 16, 13, tzinfo=UTC)
    assert store_new(session, letters, "feed", now) == 24
    assert store_new(session, letters, "feed", now) == 0  # nothing twice
    assert session.scalar(select(func.count()).select_from(CodalLetter)) == 25
    kept = session.get(CodalLetter, 1635983)
    assert (kept.letter_code, kept.title) == ("ن-۱۰", "from codal itself")  # richer row survives
    linked = session.scalars(select(CodalLetter).where(CodalLetter.instrument_id == share.id)).all()
    assert [x.tracing_no for x in linked] == [1635983]


def _use(monkeypatch, codal_pages: int):
    calls: list[str] = []

    async def fake_run(kind, **kw):
        calls.append("codal")
        return {"pages": codal_pages, "letters": 20}

    async def fake_feed(client, top=200):
        calls.append("feed")
        return {"letters": 3}

    monkeypatch.setattr(tsetmc_feed, "_run", fake_run)
    monkeypatch.setattr(tsetmc_feed, "sync_feed", fake_feed)
    monkeypatch.setattr(tsetmc_feed, "_codal_down_until", 0.0)
    return calls


def test_codal_is_used_when_it_answers(monkeypatch):
    calls = _use(monkeypatch, 1)
    assert asyncio.run(tsetmc_feed._newest(3))["via"] == 1
    assert calls == ["codal"]


def test_an_unreachable_codal_falls_back_once_and_is_not_retried_for_a_while(monkeypatch):
    calls = _use(monkeypatch, 0)
    assert asyncio.run(tsetmc_feed._newest(3))["via"] == 2
    assert asyncio.run(tsetmc_feed._newest(3))["via"] == 2
    assert calls == ["codal", "feed", "feed"]  # Codal was tried once, then skipped
