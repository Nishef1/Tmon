"""TSETMC adjusted-series parsing and the comparison used by the adjustment check. Payload rows are
copied from the live ``Financial.aspx?t=ph`` responses (a=1 adjusted, a=0 raw) of 2026-11-11."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from tmon.features.adjustment import apply_adjustments
from tmon.ingest.tsetmc import parsers
from tmon.ingest.tsetmc.adjcheck import compare

ADJUSTED = "20261109,29010,28140,28250,28510,670093258,28320;20261110,29160,28680,29100,29160,362139164,29150"


def test_parse_adjusted_history_field_order():
    bars = parsers.parse_adjusted_history(ADJUSTED)
    assert [b.day for b in bars] == [date(2026, 11, 9), date(2026, 11, 10)]
    last = bars[-1]
    # same day in the Export-txt feed: high 29160, low 28680, first 29100, last 29160, final 29150
    assert (last.high, last.low, last.open, last.last, last.close) == (
        29160,
        28680,
        29100,
        29160,
        29150,
    )
    assert last.volume == 362139164


def test_parse_adjusted_history_rejects_malformed_rows():
    with pytest.raises(parsers.ParseError):
        parsers.parse_adjusted_history("20261110,1,2,3")
    with pytest.raises(parsers.ParseError):
        parsers.parse_adjusted_history("2026xxxx,1,2,3,4,5,6")


def test_our_adjustment_matches_a_source_series_rounded_to_whole_rials():
    # a 1:1 capital increase: the reference price halves from 1000 to 500 on 2026-01-03
    raw = pl.DataFrame(
        {
            "instrument_id": [1, 1, 1, 1],
            "date": [date(2026, 1, d) for d in (1, 2, 3, 4)],
            "close": [1000.0, 1001.0, 502.0, 504.0],
            "prev_close": [999.0, 1000.0, 500.0, 502.0],
        }
    )
    adj = apply_adjustments(raw).select("date", "adj_close")
    # a source series rounded to whole rials differs by at most 0.5 rial per row
    theirs = adj.select("date", pl.col("adj_close").round(0).alias("close"))
    cmp = compare(adj, theirs)
    assert cmp.height == 4
    assert cmp["err"].max() < 0.5 / 250  # < 0.2% at these prices
    # an unadjusted comparison series would be flagged
    raw_series = raw.select("date", pl.col("close"))
    assert compare(adj, raw_series)["err"].max() > 0.4
