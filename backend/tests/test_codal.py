"""Codal letter index: parser, event mapping and ingestion, on responses captured from
search.codal.ir on 2026-11-11 (tests/fixtures/codal/)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from tmon.ingest.codal import endpoints
from tmon.ingest.codal.events import AGM, CAPITAL_INCREASE, OTHER, classify_letter
from tmon.ingest.codal.parsers import parse_codal_datetime, parse_search
from tmon.ingest.codal.pipeline import CodalCtx, sync_letters
from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc.parsers import ParseError
from tmon.storage.models import CodalLetter, CorporateEvent, Instrument, RawPayload
from tmon.storage.objectstore import MemoryStore

FIXTURES = Path(__file__).parent / "fixtures" / "codal"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_symbol_page():
    page = parse_search(_fixture("search_symbol_famli_p1.json"))
    assert (page.total, page.pages, len(page.letters)) == (1030, 52, 20)
    first = page.letters[0]
    assert first.tracing_no == 1630610
    assert first.symbol == "فملی"
    assert first.letter_code == "ن-۶۰"
    # ۱۴۰۵/۰۸/۱۷ ۱۸:۲۰:۲۰ Tehran (+03:30, no DST since 2022)
    assert first.published_at == datetime(2026, 11, 8, 14, 50, 20, tzinfo=UTC)
    assert first.url.startswith("https://www.codal.ir/Reports/Decision.aspx?LetterSerial=")
    assert first.has_html and first.has_pdf and not first.has_excel
    # a letter without a code is kept with an empty code
    assert any(x.letter_code == "" for x in page.letters)


def test_parse_market_wide_page():
    page = parse_search(_fixture("search_all_p1.json"))
    assert page.total == 635041
    assert len(page.letters) == 20
    assert len({x.tracing_no for x in page.letters}) == 20


def test_rate_limit_body_is_not_json():
    # the body Codal sends with HTTP 429
    with pytest.raises(ParseError):
        parse_search(_fixture("search_429_body.html"))


def test_codal_datetime():
    assert parse_codal_datetime("۱۴۰۵/۰۵/۰۷ ۱۲:۱۵:۰۰") == datetime(2026, 7, 29, 8, 45, tzinfo=UTC)
    assert parse_codal_datetime("") is None
    with pytest.raises(ParseError):
        parse_codal_datetime("۱۴۰۵/۱۳/۰۱ ۰۰:۰۰:۰۰")


def test_search_url_params():
    url = endpoints.search_url(page=3, symbol="فملی", letter_code="ن-۵۲", mains_only=True)
    q = httpx.URL(url).params
    assert q["PageNumber"] == "3"
    assert q["Symbol"] == "فملی"
    assert q["LetterCode"] == "ن-۵۲"
    assert (q["Childs"], q["Mains"]) == ("false", "true")


@pytest.mark.parametrize(
    ("code", "title", "expected"),
    [
        # titles as published (after normalize_fa)
        ("ن-۵۰", "آگهی دعوت به مجمع عمومی عادی سالیانه", (AGM, "invitation")),
        ("ن-۵۲", "تصمیمات مجمع عمومی عادی سالیانه دوره ۱۲ ماهه", (AGM, "decisions")),
        ("ن-۵۱", "خلاصه تصمیمات مجمع عمومی عادی سالیانه", (AGM, "decisions_summary")),
        (
            "ن-۵۱",
            "خلاصه تصمیمات مجمع عمومی عادی به طور فوق العاده",
            (OTHER, "ordinary_extraordinary_decisions_summary"),
        ),
        ("ن-۴۲", "آگهی ثبت تصمیمات مجمع عادی سالیانه", (AGM, "decisions_registered")),
        (
            "ن-۴۲",
            "آگهی ثبت تصمیمات مجمع عمومی عادی بطور فوق العاده",
            (OTHER, "decisions_registered"),
        ),
        ("ن-۱۳", "زمانبندی پرداخت سود", (AGM, "dividend_schedule")),
        (
            "ن-۶۰",
            "پیشنهاد هیئت مدیره به مجمع عمومی فوق العاده در خصوص افزایش سرمایه",
            (CAPITAL_INCREASE, "board_proposal"),
        ),
        ("ن-۶۷", "آگهی ثبت افزایش سرمایه", (CAPITAL_INCREASE, "registered")),
        ("ن-۵۷", "تصمیمات مجمع عمومی فوق العاده", (OTHER, "egm_decisions")),
        ("ن-۳۰", "گزارش فعالیت ماهانه", None),
        ("ن-۱۰", "اطلاعات و صورت های مالی میاندوره ای", None),
        ("", "تصمیمات مجمع صندوق سرمایه گذاری", None),
    ],
)
def test_classify_letter(code, title, expected):
    kind = classify_letter(code, title)
    assert (None if kind is None else (kind.type, kind.stage)) == expected


def _sync(session, store, **kwargs):
    async def go():
        async def nosleep(_: float) -> None:
            return None

        client = PoliteClient(
            limiter=DomainRateLimiter(0.0),
            retry=RetryPolicy(max_retries=0, jitter=0.0),
            client=httpx.AsyncClient(),
            sleep=nosleep,
        )
        try:
            return await sync_letters(CodalCtx(session, client, store), **kwargs)
        finally:
            await client.aclose()

    return asyncio.run(go())


def test_sync_symbol_letters_and_events(session):
    # the share and an option that share the symbol: letters belong to the share
    session.add(Instrument(ins_code="opt", symbol_fa="فملی", instrument_type="option_call"))
    share = Instrument(ins_code="35425587644337450", symbol_fa="فملی", instrument_type="stock")
    session.add(share)
    session.flush()
    store = MemoryStore()
    body = _fixture("search_symbol_famli_p1.json")
    with respx.mock:
        route = respx.get(endpoints.search_url(page=1, symbol="فملی")).mock(
            return_value=httpx.Response(200, content=body)
        )
        first = _sync(session, store, symbol="فملی", max_pages=1)
        again = _sync(session, store, symbol="فملی", max_pages=1)
    assert route.call_count == 2
    assert first == {"pages": 1, "letters": 20, "events": 5}
    assert again["letters"] == 20  # upsert, not duplicates
    assert session.scalar(select(func.count()).select_from(CodalLetter)) == 20
    events = session.scalars(select(CorporateEvent).order_by(CorporateEvent.tracing_no)).all()
    assert len(events) == 5
    assert {e.instrument_id for e in events} == {share.id}
    by_no = {e.tracing_no: e for e in events}
    agm = by_no[1578603]
    assert (agm.type, agm.stage, agm.source) == (AGM, "decisions", "codal")
    assert agm.announced_at == date(2026, 7, 29)  # ۱۴۰۵/۰۵/۰۷ in Tehran
    assert by_no[1630610].type == CAPITAL_INCREASE
    raw = session.scalars(select(RawPayload)).all()
    assert {r.source for r in raw} == {"codal"}
    # the raw response is kept byte for byte before parsing (docs/02, crawler rule 2)
    assert body in store.objects.values()


def test_sync_stops_on_short_page(session):
    store = MemoryStore()
    body = json.loads(_fixture("search_symbol_famli_p1.json"))
    body["Letters"] = body["Letters"][:3]  # a last page has fewer than 20 letters
    with respx.mock:
        respx.get(endpoints.search_url(page=1, symbol="فملی")).mock(
            return_value=httpx.Response(200, content=json.dumps(body).encode())
        )
        out = _sync(session, store, symbol="فملی", max_pages=5)
    assert out["pages"] == 1
    assert out["letters"] == 3
    assert out["events"] == 0  # no instrument is known, so no events


def test_sync_stops_cleanly_on_rate_limit(session):
    store = MemoryStore()
    body = _fixture("search_symbol_famli_p1.json")
    with respx.mock:
        respx.get(endpoints.search_url(page=1, symbol="فملی")).mock(
            return_value=httpx.Response(200, content=body)
        )
        respx.get(endpoints.search_url(page=2, symbol="فملی")).mock(
            return_value=httpx.Response(429, content=_fixture("search_429_body.html"))
        )
        out = _sync(session, store, symbol="فملی", max_pages=5)
    assert out == {"pages": 1, "letters": 20, "events": 0, "stopped_at_page": 2}
    assert session.scalar(select(func.count()).select_from(CodalLetter)) == 20  # page 1 kept


def test_lettercode_filter_reports_zero_total():
    # Codal quirk: with LetterCode set, Total and Page are 0 although letters come back
    page = parse_search(_fixture("search_lettercode_n52_p1.json"))
    assert (page.total, page.pages) == (0, 0)
    assert len(page.letters) == 20
    assert {x.letter_code for x in page.letters} == {"ن-۵۲"}


def test_resume_from_start_page(session):
    store = MemoryStore()
    body = _fixture("search_symbol_famli_p1.json")
    with respx.mock:
        route = respx.get(endpoints.search_url(page=7, symbol="فملی")).mock(
            return_value=httpx.Response(200, content=body)
        )
        out = _sync(session, store, symbol="فملی", max_pages=1, start_page=7)
    assert route.called
    assert out["pages"] == 1
