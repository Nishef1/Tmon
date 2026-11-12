"""R0 bulk loader: instrument list, share events and batched closing-price parsing."""

from __future__ import annotations

from datetime import date

import pytest

from tmon.ingest.tsetmc import endpoints
from tmon.ingest.tsetmc.bulk import (
    parse_closing_prices,
    parse_instrument_list,
    parse_share_changes,
)
from tmon.ingest.tsetmc.parsers import ParseError

ROW = (
    "22129017544200,IRR1AZIN0101,AZIX1,Saipa Azin-R,AZIN,خاذینح,ح . سایپاآذین,"
    "IRR1AZIN0106,20240214,1,سايپاآذين‌,A,N2,NO,3,34 ,3499,400"
)


def test_instrument_list_parses_the_18_field_row():
    (li,) = parse_instrument_list(ROW)
    assert li.ins_code == "22129017544200" and li.symbol == "خاذینح"
    assert li.market_code == "NO" and li.sector_code == "34" and li.type_code == "400"
    assert li.symbol_original is None


def test_instrument_list_rejects_a_short_row_and_an_empty_payload():
    with pytest.raises(ParseError):
        parse_instrument_list("1,2,3")
    with pytest.raises(ParseError):
        parse_instrument_list("")


def test_share_changes_read_the_section_after_the_at_sign():
    rows = parse_share_changes("ignored@1,408934423224097,20100518,120000000,48000000;")
    assert rows[0].ins_code == "408934423224097"
    assert rows[0].date == date(2010, 5, 18)
    assert (rows[0].shares_new, rows[0].shares_old) == (120000000, 48000000)
    with pytest.raises(ParseError):
        parse_share_changes("no share section")


def _row(deven: str, trades: int, vol: int) -> str:
    return f"1,{deven},100.00,99.00,{trades},{vol},5000.00,98.00,101.00,97.00,97.50"


def test_closing_prices_split_blocks_and_skip_zero_trade_days():
    text = ";".join([_row("20260101", 5, 10), _row("20260102", 0, 0)]) + "@" + ""
    bars, skipped = parse_closing_prices(text, 2)
    assert [len(b) for b in bars] == [1, 0] and skipped == [1, 0]
    bar = bars[0][0]
    assert bar.close == 100 and bar.last == 99 and bar.prev_close == 97
    assert bar.open == 97.5 and bar.low == 98 and bar.high == 101 and bar.volume == 10


def test_closing_prices_reject_a_wrong_block_count_or_row_width():
    with pytest.raises(ParseError):
        parse_closing_prices(_row("20260101", 1, 1), 2)
    with pytest.raises(ParseError):
        parse_closing_prices("1,2,3", 1)


def test_batch_url_carries_code_start_and_market_flag():
    url = endpoints.closing_prices_url([("111", 20010321, False), ("222", 20010321, True)])
    assert url.endswith("t=ClosingPrices&a=111,20010321,0;222,20010321,1")


def _ins(session, code: str, symbol: str, name: str, itype: str, tags: dict | None = None):
    from tmon.storage.models import Instrument

    ins = Instrument(
        ins_code=code,
        symbol_fa=symbol,
        name_fa=name,
        market="IR",
        instrument_type=itype,
        tags=tags or {},
    )
    session.add(ins)
    session.flush()
    return ins


def _bar(session, ins, day: date, close: float, prev: float):
    from tmon.storage.models import PriceDaily

    session.add(
        PriceDaily(
            instrument_id=ins.id,
            date=day,
            open=close,
            high=close,
            low=close,
            close=close,
            last=close,
            prev_close=prev,
            volume=10,
            value=1000,
            trades=1,
        )
    )
    session.flush()


def test_alt_trading_line_is_demoted_but_the_listed_share_stays(session):
    from tmon.ingest.tsetmc.bulk import flag_alt_lines

    base = _ins(session, "1", "شکربن", "کربن ایران", "stock", {"in_full_list": True})
    alt = _ins(session, "2", "شکربن3", "کربن ایران", "stock")
    lone = _ins(session, "3", "فملی", "ملی فولاد", "stock", {"in_full_list": True})
    assert flag_alt_lines(session) == 1
    assert (base.instrument_type, lone.instrument_type) == ("stock", "stock")
    assert alt.instrument_type == "other" and alt.tags["alt_line"] is True


def test_fund_nav_line_needs_the_sibling_and_the_placeholder_price(session):
    from tmon.ingest.tsetmc.bulk import flag_nav_lines

    _ins(session, "1", "سرو", "صندوق سرو", "etf_equity")
    nav = _ins(session, "2", "سرو2", "صندوق سرو", "etf_equity")
    real = _ins(session, "3", "کیان4", "صندوق کیان", "etf_fixed_income")
    _ins(session, "4", "کیان", "صندوق کیان", "etf_fixed_income")
    _bar(session, nav, date(2026, 1, 5), 1, 47000)
    _bar(session, real, date(2026, 1, 5), 1100, 1090)
    assert flag_nav_lines(session) == 1
    assert nav.instrument_type == "other" and real.instrument_type == "etf_fixed_income"


def test_exit_is_dated_from_the_last_bar_and_cleared_when_trading_resumes(session):
    from tmon.ingest.tsetmc.bulk import date_exits

    live = _ins(session, "1", "الف", "الف", "stock")
    gone = _ins(session, "2", "ب", "ب", "stock")
    back = _ins(session, "3", "ج", "ج", "stock")
    back.delisted_at = date(2020, 1, 1)
    for d in (date(2026, 1, 1), date(2026, 3, 1)):
        _bar(session, live, d, 10, 10)
        _bar(session, back, d, 10, 10)
    _bar(session, gone, date(2026, 1, 1), 10, 10)
    assert date_exits(session) == 2
    assert live.delisted_at is None and back.delisted_at is None
    assert gone.delisted_at == date(2026, 1, 1)
