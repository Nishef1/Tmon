"""Seed ``market_rules`` with the values stated in docs/01-market-structure-and-rules.md.

Rules whose number is not given in the docs (commission, tax) are seeded as
``verified: false`` approximations and surfaced in backtest reports and
docs/OPEN_QUESTIONS.md. ``valid_from`` equals the doc review date when the docs do not
state when a rule started.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.timeutil import from_jalali
from tmon.domain.rules import RuleBook, RuleRecord
from tmon.storage.models import MarketRule

MARKET = "IR"
REVIEW_DATE = date(2026, 11, 11)  # docs review: 20 Aban 1405
EPOCH = date(2000, 1, 1)

SEED_RULES: list[dict[str, Any]] = [
    {
        "rule": "trading_hours",
        "value": {"open": "09:00", "close": "12:30", "boards": "equity_and_equity_funds"},
        "valid_from": from_jalali(1405, 3, 16),
        "source_url": "https://nabzebourse.com/fa/news/130871/",
    },
    {
        "rule": "closing_session_tal",
        "value": {"open": "12:45", "close": "13:00", "price": "closing_only", "markets": [1, 2]},
        "valid_from": REVIEW_DATE,
        "source_url": "https://nabzebourse.com/fa/news/138416/",
    },
    {
        "rule": "price_limit",
        "value": {
            "pct": 0.03,
            "applies_to": ["stock", "right"],
            "verified": False,
            "note": "+-3% per docs/01; earlier limit history unknown, applied to all history",
        },
        "valid_from": EPOCH,
        "source_url": "https://learning.charisma.ir/beginning-investing/",
    },
    {
        "rule": "settlement",
        "value": {"days": 2, "verified": False, "note": "T+2 per docs/01, to be confirmed"},
        "valid_from": REVIEW_DATE,
        "source_url": None,
    },
    {
        "rule": "market_halt",
        "value": {
            "start": "2026-02-28",
            "end": "2026-05-18",
            "reopen": "2026-05-19",
            "reason": "war_closure",
        },
        "valid_from": date(2026, 2, 28),
        "source_url": "https://www.taadolnewspaper.ir/fa/news/388315/",
    },
    {
        "rule": "price_limit_change_pending",
        "value": {"status": "announced_not_effective", "date": None},
        "valid_from": REVIEW_DATE,
        "source_url": "https://nabzebourse.com/fa/news/139122/",
    },
    # --- unverified approximations: replace with official figures ---------------
    {
        "rule": "commission_buy",
        "value": {"rate": 0.0037, "verified": False, "note": "approximate, general knowledge"},
        "valid_from": EPOCH,
        "source_url": None,
    },
    {
        "rule": "commission_sell",
        "value": {"rate": 0.0039, "verified": False, "note": "approximate, general knowledge"},
        "valid_from": EPOCH,
        "source_url": None,
    },
    {
        "rule": "sell_tax",
        "value": {"rate": 0.005, "verified": False, "note": "approximate, general knowledge"},
        "valid_from": EPOCH,
        "source_url": None,
    },
]


def seed_rulebook() -> RuleBook:
    """The seed rules as an in-memory :class:`RuleBook` (offline runs, tests, synthetic data)."""
    return RuleBook(
        RuleRecord(
            MARKET, s["rule"], s["value"], s["valid_from"], s.get("valid_to"), s.get("source_url")
        )
        for s in SEED_RULES
    )


def seed_market_rules(session: Session) -> int:
    """Insert seed rules that are not yet present (matched by market+rule+valid_from)."""
    added = 0
    for spec in SEED_RULES:
        exists = session.scalar(
            select(MarketRule.id).where(
                MarketRule.market == MARKET,
                MarketRule.rule == spec["rule"],
                MarketRule.valid_from == spec["valid_from"],
            )
        )
        if exists is not None:
            continue
        session.add(
            MarketRule(
                market=MARKET,
                rule=spec["rule"],
                value=spec["value"],
                valid_from=spec["valid_from"],
                valid_to=spec.get("valid_to"),
                source_url=spec.get("source_url"),
            )
        )
        added += 1
    session.flush()
    return added
