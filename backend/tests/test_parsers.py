"""Parser tests use small *synthetic* payloads that follow the documented field layout;
they test parsing logic only, not real market data."""

from datetime import date

import pytest

from tmon.ingest.tsetmc import parsers

HISTORY = """<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,<OPEN>,<LAST>
SYM,20250112,1010,1030,1000,1020,5000000,5000,12,D,1000,1015
SYM,20250111,990,1010,985,1000,4000000,4000,9,D,980,998
"""


def test_market_watch():
    text = (
        "h@x@111,IRO1AAA0001,فولاد,شرکت فولاد;222,IRO1BBB0001,خودرو,شرکت خودرو;"
        "bad;111,IRO1AAA0001,dup,dup"
    )
    out = parsers.parse_market_watch_init(text)
    assert [i.ins_code for i in out] == ["111", "222"]
    assert out[0].symbol_fa == "فولاد"
    assert out[1].isin == "IRO1BBB0001"


def test_market_watch_rejects_garbage():
    with pytest.raises(parsers.ParseError):
        parsers.parse_market_watch_init("no groups here")


def test_normalize_arabic_letters():
    assert parsers.normalize_fa("كاريزما‌ي") == "کاریزما ی"


def test_daily_history_sorted_and_mapped():
    bars = parsers.parse_daily_history(HISTORY)
    assert [b.date for b in bars] == [date(2025, 1, 11), date(2025, 1, 12)]
    b = bars[1]
    assert (b.open, b.high, b.low) == (1010, 1030, 1000)
    assert b.close == 1020  # <CLOSE> is the final price
    assert b.last == 1015  # <LAST> is the last trade
    assert b.prev_close == 1000  # <OPEN> is yesterday's final price in this export
    assert (b.volume, b.value, b.trades) == (5000, 5000000, 12)


def test_daily_history_missing_column():
    with pytest.raises(parsers.ParseError):
        parsers.parse_daily_history("<TICKER>,<DTYYYYMMDD>\nSYM,20250101")


def test_daily_history_empty():
    assert parsers.parse_daily_history("") == []


def test_client_types_with_and_without_values():
    full = "20250112,10,2,8,3,1000,200,900,300,5000,1000,4500,1500;20250111,1,1,1,1,1,1,1,1"
    rows = parsers.parse_client_types(full)
    assert [r.date for r in rows] == [date(2025, 1, 11), date(2025, 1, 12)]
    assert rows[0].buy_value_i is None
    r = rows[1]
    assert (r.buy_count_i, r.sell_count_n) == (10, 3)
    assert (r.buy_volume_i, r.sell_volume_n) == (1000, 300)
    assert (r.buy_value_i, r.sell_value_n) == (5000, 1500)


def test_client_types_skips_marker_rows():
    assert parsers.parse_client_types("0;") == []


def test_instrument_info():
    payload = {
        "instrumentInfo": {
            "insCode": "111",
            "cIsin": "IRO1AAA0001",
            "lVal18AFC": "فولاد",
            "lVal30": "شرکت فولاد",
            "sector": {"cSecVal": "27 ", "lSecVal": "فلزات اساسی"},
            "cgrValCot": "N1",
            "cgrValCotTitle": "بازار اول (تابلوی اصلی) بورس",
            "flow": 1,
            "flowTitle": "بورس",
            "baseVol": 123456,
            "zTitad": 1000000,
            "yVal": "305",
            "faraDesc": "نوع صندوق: سهامي",
        }
    }
    info = parsers.parse_instrument_info(payload)
    assert info.type_code == "305"
    assert info.fund_desc == "نوع صندوق: سهامی"  # normalized
    assert info.sector_code == "27"
    assert info.base_volume == 123456
    assert info.group_title.startswith("بازار اول")


def test_instrument_info_missing():
    with pytest.raises(parsers.ParseError):
        parsers.parse_instrument_info({})


def test_best_limits():
    payload = {
        "bestLimits": [
            {
                "number": 2,
                "pMeDem": 99,
                "qTitMeDem": 10,
                "zOrdMeDem": 1,
                "pMeOf": 102,
                "qTitMeOf": 20,
                "zOrdMeOf": 2,
            },
            {
                "number": 1,
                "pMeDem": 100,
                "qTitMeDem": 50,
                "zOrdMeDem": 3,
                "pMeOf": 101,
                "qTitMeOf": 5,
                "zOrdMeOf": 1,
            },
        ]
    }
    levels = parsers.parse_best_limits(payload)
    assert [lv.row for lv in levels] == [1, 2]
    assert levels[0].bid_volume == 50
    assert levels[0].as_dict()["ask_price"] == 101
