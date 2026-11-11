"""Market rules with validity dates. Nothing here hard-codes a rule value; values come
from the ``market_rules`` table (seeded by :mod:`tmon.storage.seed`)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.storage.models import MarketRule


class MissingRuleError(LookupError):
    pass


@dataclass(frozen=True)
class RuleRecord:
    market: str
    rule: str
    value: dict[str, Any]
    valid_from: date
    valid_to: date | None
    source_url: str | None = None

    def covers(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)

    @property
    def verified(self) -> bool:
        return bool(self.value.get("verified", False))


class RuleBook:
    def __init__(self, records: Iterable[RuleRecord]) -> None:
        self._records = sorted(records, key=lambda r: r.valid_from)

    @classmethod
    def from_session(cls, session: Session, market: str = "IR") -> RuleBook:
        rows = session.scalars(select(MarketRule).where(MarketRule.market == market)).all()
        return cls(
            RuleRecord(r.market, r.rule, dict(r.value), r.valid_from, r.valid_to, r.source_url)
            for r in rows
        )

    def record(self, rule: str, asof: date, *, market: str = "IR") -> RuleRecord:
        matches = [
            r for r in self._records if r.rule == rule and r.market == market and r.covers(asof)
        ]
        if not matches:
            raise MissingRuleError(f"no '{rule}' rule valid on {asof} for market {market}")
        return matches[-1]  # latest valid_from wins

    def value(self, rule: str, asof: date, *, market: str = "IR") -> dict[str, Any]:
        return self.record(rule, asof, market=market).value

    def all_for(self, rule: str, *, market: str = "IR") -> list[RuleRecord]:
        return [r for r in self._records if r.rule == rule and r.market == market]

    def unverified(self) -> list[RuleRecord]:
        return [r for r in self._records if not r.verified]


@dataclass(frozen=True)
class CostModel:
    """Round-trip transaction cost as a fraction of notional.

    ``cost = commission_buy + commission_sell + sell_tax + slippage``; slippage is the
    total round-trip allowance from ``engine.yaml`` (docs/10 section 6).
    """

    commission_buy: float
    commission_sell: float
    sell_tax: float
    slippage: float

    @property
    def buy_side(self) -> float:
        return self.commission_buy + self.slippage / 2

    @property
    def sell_side(self) -> float:
        return self.commission_sell + self.sell_tax + self.slippage / 2

    @property
    def round_trip(self) -> float:
        return self.buy_side + self.sell_side

    @classmethod
    def from_rules(cls, rules: RuleBook, asof: date, slippage_fraction: float) -> CostModel:
        return cls(
            commission_buy=float(rules.value("commission_buy", asof)["rate"]),
            commission_sell=float(rules.value("commission_sell", asof)["rate"]),
            sell_tax=float(rules.value("sell_tax", asof)["rate"]),
            slippage=slippage_fraction,
        )

    def net_return(self, gross_return: float) -> float:
        """Net simple return of a trade bought at 1 and sold at ``1 + gross_return``."""
        buy_cost = 1 + self.buy_side
        proceeds = (1 + gross_return) * (1 - self.sell_side)
        return proceeds / buy_cost - 1
