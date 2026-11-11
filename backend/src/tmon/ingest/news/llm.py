"""Structured event extraction with Claude (docs/08 step 4). Only called when
``TMON_LLM_API_KEY`` is set; the output is validated against the fixed schema below."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "fx_rate",
    "feedstock_price",
    "price_control",
    "tax_tariff",
    "interest_rate",
    "geopolitical",
    "regulator",
    "company_disclosure",
    "energy_restriction",
    "none",
]

SYSTEM = (
    "You read one Persian news item about the Tehran Stock Exchange or the Iranian economy and "
    "return one structured event. event_type is one of the listed types, or 'none' when the "
    "item is not a market-moving event. symbols are TSE tickers in Persian, only when the item "
    "names them. direction is -1, 0 or 1 for the named symbols or sectors; magnitude 1-5; "
    "confidence 0-1 is how sure you are of the direction. effective_from is the date the "
    "measure takes effect when the item states one, else null. is_official is true only for a "
    "decision published by a government body, regulator or the company itself. summary_fa is "
    "one Persian sentence. Do not guess facts the item does not state."
)


class ExtractedEvent(BaseModel):
    event_type: EventType
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    direction: Literal[-1, 0, 1]
    magnitude: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    effective_from: dt.date | None = None
    horizon: Literal["D1", "W1", "M1"] | None = None
    is_official: bool
    summary_fa: str


def extract(api_key: str, model: str, title: str, summary: str | None) -> ExtractedEvent | None:
    """One request per cluster; None when the model refuses or returns nothing usable."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    text = title if not summary else f"{title}\n\n{summary}"
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        system=SYSTEM,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": text}],
        output_format=ExtractedEvent,
    )
    if response.stop_reason != "end_turn":
        return None
    return response.parsed_output
