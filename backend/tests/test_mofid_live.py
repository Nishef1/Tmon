"""Mofid's push feed: TLCP value decoding and the shape of a book."""

from __future__ import annotations

import base64
import json

from tmon.portfolio import mofid_live as m


def test_decode_keeps_unchanged_fields_and_reads_the_markers() -> None:
    first = m.decode("a|b|c|d|e", [])
    assert first == ["a", "b", "c", "d", "e"]
    assert m.decode("|x|^2|#", first) == ["a", "x", "c", "d", None]
    assert m.decode("$|%D9%81|||", first) == ["", "ف", "c", "d", "e"]


def test_a_book_update_becomes_levels() -> None:
    vals = ["20261115105524"] + ["0"] * (len(m.BOOK_FIELDS) - 1)
    f = m.BOOK_FIELDS
    vals[f.index("buy-price-1")], vals[f.index("buy-volume-1")] = "5170", "1321340225"
    vals[f.index("buy-order-count-1")] = "5755"
    out = m.shape("book", vals)
    assert out["levels"] == [
        {"row": 1, "bid_price": 5170.0, "bid_volume": 1321340225.0, "bid_count": 5755,
         "ask_price": 0.0, "ask_volume": 0.0, "ask_count": 0}
    ]  # fmt: skip
    assert out["as_of"].hour == 7  # 10:55 Tehran


def test_the_customer_number_is_read_from_the_token() -> None:
    claims = base64.urlsafe_b64encode(json.dumps({"customer_isin": "123"}).encode()).rstrip(b"=")
    assert m.customer_number(f"h.{claims.decode()}.s") == "123"
    assert m.customer_number("junk") is None
