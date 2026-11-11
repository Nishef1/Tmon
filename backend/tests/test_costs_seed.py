"""Verified cost schedule in market_rules (ADR 0002 section 2)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from tmon.domain.rules import CostModel, RuleBook
from tmon.storage.models import MarketRule
from tmon.storage.seed import COST_VERIFIED_FROM, seed_market_rules


def test_costs_are_verified_with_sources_from_the_oldest_dated_source(session):
    seed_market_rules(session)
    session.commit()
    rules = RuleBook.from_session(session)
    for name in ("commission_buy", "commission_sell", "sell_tax"):
        rec = rules.record(name, date(2026, 11, 11))
        assert rec.verified and rec.source_url and rec.value["sources"]
    assert rules.value("commission_buy", date(2026, 11, 11))["rate"] == 0.003712
    assert rules.value("commission_sell", date(2026, 11, 11))["rate"] == 0.0038
    assert rules.value("sell_tax", date(2026, 11, 11))["rate"] == 0.005
    # before the oldest dated source the same figures are assumed and flagged unverified
    assert not rules.record("sell_tax", date(2023, 1, 1)).verified
    assert rules.record("sell_tax", COST_VERIFIED_FROM).verified


def test_round_trip_cost_matches_the_published_totals(session):
    seed_market_rules(session)
    # ADR 0002: 0.25% slippage per side = 0.5% round trip
    cm = CostModel.from_rules(RuleBook.from_session(session), date(2026, 11, 11), 0.005)
    # buy 0.3712% + sell 0.88% (incl. 0.5% tax) = 1.2512%, plus the slippage
    assert cm.round_trip == pytest.approx(0.012512 + 0.005)


def test_seed_refreshes_existing_rows(session):
    seed_market_rules(session)
    row = session.scalars(select(MarketRule).where(MarketRule.rule == "sell_tax")).first()
    assert row is not None
    row.value = {"rate": 0.9, "verified": False}
    session.flush()
    seed_market_rules(session)
    session.refresh(row)
    assert row.value["rate"] != 0.9
