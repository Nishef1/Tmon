"""R0 discovery: search payload parsing, candidate filter, crawl descent and resumability."""

from __future__ import annotations

import json

import pytest

from tmon.ingest.tsetmc.delisted import (
    ALPHABET,
    SATURATION,
    CrawlState,
    is_candidate_symbol,
    parse_search,
)
from tmon.ingest.tsetmc.parsers import ParseError


def _payload(*rows: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "instrumentSearch": [
                {"insCode": c, "lVal18AFC": s, "lVal30": n, "flowTitle": "بازار بورس"}
                for c, s, n in rows
            ]
        },
        ensure_ascii=False,
    )


def test_parse_search_reads_code_symbol_name():
    hits = parse_search(_payload(("1", "فولاد", "فولاد مباركه"), ("2", "خودرو", "ايران خودرو")))
    assert [(h.ins_code, h.symbol) for h in hits] == [("1", "فولاد"), ("2", "خودرو")]


def test_parse_search_rejects_unexpected_shape():
    with pytest.raises(ParseError):
        parse_search('{"other": []}')


def test_rights_bonds_and_options_are_not_candidates():
    assert is_candidate_symbol("فولاد")
    assert not is_candidate_symbol("فولادح")
    assert not is_candidate_symbol("پاکديس07")
    assert not is_candidate_symbol("")


def test_state_round_trip_and_summary(tmp_path):
    st = CrawlState.load(tmp_path / "s.json")
    assert len(st.frontier) == len(ALPHABET) ** 2
    st.done = {"اب": SATURATION, "اپ": 3}
    st.found = {"9": {"symbol": "x", "name": "y", "board": None}}
    st.save(tmp_path / "s.json")
    back = CrawlState.load(tmp_path / "s.json")
    assert back.done == st.done and back.found == st.found
    assert back.summary()["saturated"] == 1 and back.summary()["found"] == 1
