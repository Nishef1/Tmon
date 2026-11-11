"""Index history parsing and ingestion (mocked HTTP; payload shape copied from the live API)."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest
import respx
from sqlalchemy import select

from tmon.core.engine_config import get_engine_config
from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.classify import load_classifier
from tmon.ingest.tsetmc.indices import ingest_indices
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import MarketIndexDaily
from tmon.storage.objectstore import MemoryStore

PAYLOAD = {
    "indexB2": [
        {"insCode": 1, "dEven": 20081204, "xNivInuClMresIbs": 9248.9,
         "xNivInuPbMresIbs": 9233.2, "xNivInuPhMresIbs": 9248.9},
        {"insCode": 1, "dEven": 20081206, "xNivInuClMresIbs": 9178.3,
         "xNivInuPbMresIbs": 9167.8, "xNivInuPhMresIbs": 9248.8},
    ]
}  # fmt: skip


def test_parse_index_history():
    bars = parsers.parse_index_history(PAYLOAD)
    assert [b.day for b in bars] == [date(2008, 12, 4), date(2008, 12, 6)]
    assert bars[1].close == 9178.3 and bars[1].low == 9167.8 and bars[1].high == 9248.8


def test_parse_index_history_rejects_other_shapes_and_drops_nonsense_rows():
    with pytest.raises(parsers.ParseError):
        parsers.parse_index_history({"bestLimitsHistory": []})
    bad = {"indexB2": [{"dEven": 20260101, "xNivInuClMresIbs": 0.0,
                        "xNivInuPbMresIbs": 0.0, "xNivInuPhMresIbs": 0.0}]}  # fmt: skip
    assert parsers.parse_index_history(bad) == []


def test_ingest_indices_stores_both_benchmarks_with_provenance(session):
    codes = get_engine_config().benchmarks.indices
    assert set(codes) == {"tedpix", "equal_weight"}

    async def go():
        client = PoliteClient(
            limiter=DomainRateLimiter(0.0),
            retry=RetryPolicy(max_retries=0, jitter=0.0),
            client=httpx.AsyncClient(),
        )
        try:
            ctx = Ctx(session, client, MemoryStore(), load_classifier())
            with respx.mock:
                for code in codes.values():
                    respx.get(endpoints.index_history_url(code)).mock(
                        return_value=httpx.Response(200, json=PAYLOAD)
                    )
                return await ingest_indices(ctx)
        finally:
            await client.aclose()

    assert asyncio.run(go()) == {"tedpix": 2, "equal_weight": 2}
    rows = session.scalars(select(MarketIndexDaily)).all()
    assert len(rows) == 4 and all(r.source_url and r.fetched_at for r in rows)
