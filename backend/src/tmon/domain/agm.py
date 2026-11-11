"""Hold for the AGM or sell before it (docs/05-corporate-events.md).

    NetHold = DPS / (1 + r_m)^k − E[ΔP_after] − tax_on_dividend
    NetSell = P_now × ((1 + r_alt)^k' − 1) − round_trip_costs

All amounts are rial per share. ``NetHold > NetSell`` → hold for the meeting; otherwise sell
before it and look at buying after the reopening. A pure function: the caller supplies every
input and says where each came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AgmInputs:
    dps: float  # dividend per share (rial)
    price_now: float  # current price (rial)
    months_to_payment: float  # k: months until the dividend is actually received
    monthly_discount: float  # r_m: monthly inflation or fixed-income fund return
    expected_drop_after: float  # E[ΔP_after]: drop beyond the adjustment after reopening (rial)
    dividend_tax: float  # tax on the dividend (rial per share)
    alt_monthly_return: float  # r_alt
    months_alt: float  # k': months the sale proceeds earn r_alt
    round_trip_costs: float  # rial per share


@dataclass(frozen=True)
class AgmDecision:
    pv_dividend: float
    net_hold: float
    net_sell: float
    decision: Literal["hold", "sell"]


def hold_or_sell(x: AgmInputs) -> AgmDecision:
    if x.price_now <= 0:
        raise ValueError("price_now must be positive")
    if x.dps < 0 or x.dividend_tax < 0 or x.round_trip_costs < 0:
        raise ValueError("dps, dividend_tax and round_trip_costs must be non-negative")
    if x.months_to_payment < 0 or x.months_alt < 0:
        raise ValueError("months must be non-negative")
    if x.monthly_discount <= -1 or x.alt_monthly_return <= -1:
        raise ValueError("monthly rates must be greater than -100%")
    pv = x.dps / (1 + x.monthly_discount) ** x.months_to_payment
    net_hold = pv - x.expected_drop_after - x.dividend_tax
    net_sell = x.price_now * ((1 + x.alt_monthly_return) ** x.months_alt - 1) - x.round_trip_costs
    return AgmDecision(
        pv_dividend=pv,
        net_hold=net_hold,
        net_sell=net_sell,
        decision="hold" if net_hold > net_sell else "sell",
    )


def monthly_from_annual(annual: float) -> float:
    """Compound monthly rate equivalent to an annual rate."""
    if annual <= -1:
        raise ValueError("annual rate must be greater than -100%")
    return float((1 + annual) ** (1 / 12) - 1)
