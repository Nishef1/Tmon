"""Seed ``market_rules`` with the values stated in docs/01-market-structure-and-rules.md.

Costs come from dated broker pages (see COST_SOURCES); other numbers not in the docs are seeded as
``verified: false`` approximations and surfaced in backtest reports and
docs/OPEN_QUESTIONS.md. ``valid_from`` equals the doc review date when the docs do not
state when a rule started.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.timeutil import from_jalali
from tmon.domain.rules import RuleBook, RuleRecord
from tmon.storage.models import MarketRule

MARKET = "IR"
REVIEW_DATE = date(2026, 11, 11)  # docs review: 20 Aban 1405
EPOCH = date(2000, 1, 1)

# Dated pages with the same totals (read 2026-11-11). All cite the SEO fee-ceiling report.
COST_SOURCES = [
    {
        "url": "https://enigma.ir/blog/the-amount-of-trading-fees-in-the-capital-market",
        "publisher": "Enigma",
        "date": "2024-08-26",
    },
    {
        "url": "https://learning.charisma.ir/beginning-investing/%DA%A9%D8%A7%D8%B1%D9%85%D8%B2%D8%AF-%D9%85%D8%B9%D8%A7%D9%85%D9%84%D8%A7%D8%AA/",
        "publisher": "Charisma Financial Services Group (broker)",
        "date": "2026-09-14",
    },
    {
        "url": "https://learning.emofid.com/trading-fees/",
        "publisher": "Mofid Securities (broker)",
        "date": "2026-09-30",
    },
]
COST_VERIFIED_FROM = date(2024, 8, 26)

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
    # --- costs (ADR 0002 section 2) ---------------------------------------------------
    # Stock trades on the Tehran Stock Exchange: total buy 0.3712%, total sell 0.88% of which 0.5%
    # is the sell tax (so sell commissions are 0.38%). The Fara Bourse buy total is 0.3632%; the
    # higher exchange figure is used for both (conservative, 0.008% apart). Read 2026-11-11 from
    # three pages that all cite the SEO report "سقف نرخ کارمزدها و خدمات در بازار سرمایه ایران"
    # (edition 49); the primary SEO document itself was not reachable, the per-body shares are
    # images in the sources. Verified for dates from the oldest dated source onward.
    {
        "rule": "commission_buy",
        "value": {
            "rate": 0.003712,
            "verified": True,
            "note": "Tehran Stock Exchange stock buy total; Fara Bourse 0.003632 (not used)",
            "sources": COST_SOURCES,
        },
        "valid_from": COST_VERIFIED_FROM,
        "source_url": COST_SOURCES[1]["url"],
    },
    {
        "rule": "commission_sell",
        "value": {
            "rate": 0.0038,
            "verified": True,
            "note": "sell total 0.0088 minus the 0.5% sell tax; both markets",
            "sources": COST_SOURCES,
        },
        "valid_from": COST_VERIFIED_FROM,
        "source_url": COST_SOURCES[1]["url"],
    },
    {
        "rule": "sell_tax",
        "value": {
            "rate": 0.005,
            "verified": True,
            "note": "0.5% of the sale value, included in the 0.88% sell total",
            "sources": COST_SOURCES,
        },
        "valid_from": COST_VERIFIED_FROM,
        "source_url": COST_SOURCES[1]["url"],
    },
    # Earlier dates: the same figures are assumed (the 2024 and 2026 sources agree and no change
    # is documented in between), but no source dates that far back. Kept unverified.
    {
        "rule": "commission_buy",
        "value": {"rate": 0.003712, "verified": False, "note": "assumed equal; no dated source"},
        "valid_from": EPOCH,
        "valid_to": COST_VERIFIED_FROM - timedelta(days=1),
        "source_url": None,
    },
    {
        "rule": "commission_sell",
        "value": {"rate": 0.0038, "verified": False, "note": "assumed equal; no dated source"},
        "valid_from": EPOCH,
        "valid_to": COST_VERIFIED_FROM - timedelta(days=1),
        "source_url": None,
    },
    {
        "rule": "sell_tax",
        "value": {"rate": 0.005, "verified": False, "note": "assumed equal; no dated source"},
        "valid_from": EPOCH,
        "valid_to": COST_VERIFIED_FROM - timedelta(days=1),
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
    """Insert missing seed rules and refresh existing ones (matched by market+rule+valid_from)."""
    added = 0
    for spec in SEED_RULES:
        existing = session.scalar(
            select(MarketRule).where(
                MarketRule.market == MARKET,
                MarketRule.rule == spec["rule"],
                MarketRule.valid_from == spec["valid_from"],
            )
        )
        if existing is not None:
            # the seed owns these rows: a corrected value or source reaches existing databases
            existing.value = spec["value"]
            existing.valid_to = spec.get("valid_to")
            existing.source_url = spec.get("source_url")
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
