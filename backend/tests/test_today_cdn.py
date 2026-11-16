from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.ingest.tsetmc import today_cdn
from tmon.storage.models import Instrument, PriceDaily

INFO = {
    "dEven": 20261116,
    "priceFirst": 12330.0,
    "priceMax": 12340.0,
    "priceMin": 11640.0,
    "pClosing": 12110.0,
    "pDrCotVal": 11940.0,
    "priceYesterday": 11990.0,
    "qTotTran5J": 24176649.0,
    "qTotCap": 292722727470.0,
    "zTotTran": 1600.0,
}


def test_a_reply_becomes_the_same_columns_the_bulk_feed_writes() -> None:
    day, cols = today_cdn.parse_info(INFO) or (None, {})
    assert day == dt.date(2026, 11, 16)
    assert cols["open"] == 12330 and cols["close"] == 12110 and cols["last"] == 11940
    assert cols["prev_close"] == 11990 and cols["trades"] == 1600


def test_a_symbol_that_did_not_trade_has_no_bar() -> None:
    assert today_cdn.parse_info({**INFO, "zTotTran": 0.0, "qTotTran5J": 0.0}) is None
    assert today_cdn.parse_info({**INFO, "priceFirst": 0.0}) is None


def _inst(session: Session, code: str, symbol: str, last_day: dt.date) -> int:
    i = Instrument(ins_code=code, symbol_fa=symbol, name_fa=symbol, sector_code="34")
    session.add(i)
    session.flush()
    session.add(PriceDaily(instrument_id=i.id, date=last_day, close=1.0, last=1.0, volume=1.0))
    session.flush()
    return i.id


def test_only_todays_traded_symbols_are_filled_and_never_while_the_market_is_open(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    yesterday = dt.date(2026, 11, 15)
    a = _inst(session, "1", "الف", yesterday)
    b = _inst(session, "2", "ب", yesterday)  # suspended: the endpoint still answers with old day
    old = {**INFO, "dEven": 20261115}
    monkeypatch.setattr(
        today_cdn, "_fetch", lambda code: today_cdn.parse_info(INFO if code == "1" else old)
    )
    morning = dt.datetime(2026, 11, 16, 5, 0, tzinfo=dt.UTC)  # 08:30 Tehran
    assert today_cdn.fill_today(session, now=morning)["skipped_open_market"] == 1
    evening = dt.datetime(2026, 11, 16, 15, 30, tzinfo=dt.UTC)  # 19:00 Tehran
    assert today_cdn.fill_today(session, now=evening)["stored"] == 1
    today = dt.date(2026, 11, 16)
    ids = set(session.scalars(select(PriceDaily.instrument_id).where(PriceDaily.date == today)))
    assert ids == {a} and b not in ids
    # a second run asks only for the symbol that has no bar yet and stores nothing new
    again = today_cdn.fill_today(session, now=evening)
    assert again["asked"] == 1 and again["stored"] == 0
