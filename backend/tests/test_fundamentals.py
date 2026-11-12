"""EPS / P/E reading, the instrument-info parser's EPS fields, and the symbol search."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import dashboard as dash
from tmon.core.db import get_session
from tmon.domain.fundamentals import fundamental
from tmon.ingest.tsetmc.parsers import parse_instrument_info
from tmon.storage.models import Instrument, PriceDaily, SectorName


def test_pe_is_price_over_eps_and_compared_with_the_group() -> None:
    f = fundamental(eps=500, sector_pe=8.0, close=2500, group="فلزات")
    assert f.pe == pytest.approx(5.0)
    assert f.vs_sector == pytest.approx(5 / 8 - 1)
    assert f.verdict == "cheap" and "فلزات" in f.text and "دخالت ندارد" in f.text
    assert fundamental(500, 8.0, 4000, None).verdict == "fair"
    assert fundamental(500, 8.0, 6000, None).verdict == "expensive"


def test_missing_negative_and_unpriced_eps_say_so() -> None:
    assert fundamental(None, 8.0, 100, None).verdict == "unknown"
    neg = fundamental(-40, 8.0, 100, None)
    assert neg.verdict == "loss" and neg.pe is None and "زیان" in neg.text
    assert fundamental(40, 8.0, None, None).pe is None
    assert fundamental(40, None, 400, None).verdict == "unknown"
    assert fundamental(40, 0.0, 400, None).sector_pe is None


def _info(eps: object) -> dict[str, object]:
    return {"instrumentInfo": {"insCode": "1", "eps": eps}}


def test_parser_reads_the_exchange_eps_and_treats_zero_as_missing() -> None:
    i = parse_instrument_info(_info({"estimatedEPS": "2073", "sectorPE": 11.61}))
    assert i.eps == 2073 and i.sector_pe == pytest.approx(11.61)
    j = parse_instrument_info(_info({"estimatedEPS": None, "sectorPE": 0.0}))
    assert j.eps is None and j.sector_pe is None
    assert parse_instrument_info(_info(None)).eps is None


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _seed(session: Session) -> None:
    session.add(SectorName(code="27", name="فلزات اساسی", source_url="x"))
    session.add_all(
        [
            Instrument(
                id=1, ins_code="c1", symbol_fa="فولاد", name_fa="فولاد مبارکه", sector_code="27",
                instrument_type="stock", tags={"eps": 500.0, "sector_pe": 8.0},
            ),
            Instrument(
                id=2, ins_code="c2", symbol_fa="فولادی", name_fa="صندوق", sector_code=None,
                instrument_type="etf_equity",
            ),
            Instrument(
                id=3, ins_code="c3", symbol_fa="ذوب", name_fa="ذوب آهن", sector_code="27",
                instrument_type="stock",
            ),
        ]
    )  # fmt: skip
    for i in (1, 2, 3):
        session.add(
            PriceDaily(
                instrument_id=i, date=dt.date(2026, 11, 10), open=100, high=100, low=100,
                last=2500, close=2500, prev_close=2400, volume=10, value=1e9, trades=1,
            )
        )  # fmt: skip
    session.commit()


def test_search_matches_symbol_name_and_industry_and_orders_exact_first(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    monkeypatch.setattr(dash, "_ranking_doc", lambda: None)
    body = client.get("/search", params={"q": "فولاد"}).json()
    assert [h["instrument"]["symbol"] for h in body["hits"]] == ["فولاد", "فولادی"]
    top = body["hits"][0]
    assert top["sector_name"] == "فلزات اساسی" and top["kind"] == "سهام"
    assert top["pe"] == pytest.approx(5.0) and top["sector_pe"] == 8.0
    assert top["change_pct"] == pytest.approx(2500 / 2400 - 1)
    assert body["hits"][1]["kind"] == "صندوق قابل معامله" and body["hits"][1]["pe"] is None
    by_group = client.get("/search", params={"q": "فلزات"}).json()
    assert {h["instrument"]["symbol"] for h in by_group["hits"]} == {"فولاد", "ذوب"}
    arabic = client.get("/search", params={"q": "ذوب"}).json()  # same text typed with ي / ك
    assert arabic["hits"][0]["instrument"]["symbol"] == "ذوب"
    assert client.get("/search", params={"q": "   x"}).json()["hits"] == []
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_dashboard_and_screener_carry_eps_pe_and_industry(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    monkeypatch.setattr(dash, "_ranking_doc", lambda: None)
    d = client.get("/instruments/1/dashboard").json()
    assert d["fundamental"]["pe"] == pytest.approx(5.0)
    assert d["fundamental"]["verdict"] == "cheap"
    assert client.get("/instruments/2/dashboard").json()["fundamental"] is None
    rows = client.get("/screener", params={"q": "فلزات", "sort": "pe"}).json()["rows"]
    assert {r["instrument"]["symbol"] for r in rows} == {"فولاد", "ذوب"}
    assert rows[0]["instrument"]["symbol"] == "فولاد" and rows[0]["pe"] == pytest.approx(5.0)
    assert rows[0]["sector_name"] == "فلزات اساسی"
