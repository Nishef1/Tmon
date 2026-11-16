"""The market-watch feed carries prices under two sets of names; only the short set is filled."""

from __future__ import annotations

from tmon.ingest.tsetmc.quotes import read
from tmon.portfolio.watch import parse_quote

LIVE = {
    "insCode": "1",
    "lva": "شبهرن",
    "pdv": 19_200,
    "pcl": 19_350,
    "py": 18_900,
    "pf": 19_400,
    "pmx": 19_500,
    "pmn": 19_100,
    "qtj": 1_200_000,
    "qtc": 23_000_000_000,
    "ztt": 800,
    "pMax": 19_740,
    "pMin": 18_600,
    # the older names are present but zero
    "pDrCotVal": 0,
    "pClosing": 0,
    "priceYesterday": 0,
    "qTotTran5J": 0,
    "qTotCap": 0,
}


def test_read_uses_the_short_names_when_the_old_ones_are_zero() -> None:
    r = read(LIVE)
    assert r["last"] == 19_200
    assert r["close"] == 19_350
    assert r["yesterday"] == 18_900
    assert r["first"] == 19_400
    assert (r["high"], r["low"]) == (19_500, 19_100)
    assert r["volume"] == 1_200_000
    assert r["value"] == 23_000_000_000
    assert (r["limit_up"], r["limit_down"]) == (19_740, 18_600)
    assert r["symbol"] == "شبهرن"


def test_read_falls_back_to_the_old_names() -> None:
    r = read({"pDrCotVal": 1010, "pClosing": 1000, "priceYesterday": 990, "qTotTran5J": 5})
    assert (r["last"], r["close"], r["yesterday"], r["volume"]) == (1010, 1000, 990, 5)


def test_zero_is_missing_not_a_price() -> None:
    r = read({"pdv": 0, "pcl": 0})
    assert r["last"] is None and r["close"] is None


def test_parse_quote_keeps_last_and_close_apart() -> None:
    q = parse_quote(LIVE)
    assert q is not None
    assert q.last == 19_200
    assert q.close == 19_350
    assert q.yesterday == 18_900
    assert q.volume == 1_200_000
