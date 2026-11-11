"""Comparison with inflation (docs/06, docs/07): nominal and real return of each asset over a
horizon, with inflation taken point-in-time (only figures released by the as-of day)."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


def months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def value_on_or_before(
    points: Sequence[tuple[date, float]], day: date
) -> tuple[date, float] | None:
    """``points`` sorted by date ascending."""
    best = None
    for d, v in points:
        if d > day:
            break
        best = (d, v)
    return best


def real_return(nominal: float, inflation: float) -> float:
    """docs/06: ``(1 + r) / (1 + π) − 1``."""
    return (1 + nominal) / (1 + inflation) - 1


@dataclass(frozen=True)
class Release:
    ref_period: date
    release_date: date
    value: float
    source_url: str | None


@dataclass(frozen=True)
class PeriodInflation:
    value: float
    method: str  # "cpi_mom × n" or "cpi_yoy"
    releases: tuple[Release, ...]


def period_inflation(
    mom: Sequence[Release], yoy: Sequence[Release], as_of: date, months: int
) -> PeriodInflation | None:
    """Inflation over the last ``months`` months as known on ``as_of``: the product of the latest
    ``months`` monthly releases, or for 12 months the latest point-to-point figure when there are
    not twelve monthly ones. ``None`` when not enough has been released."""
    known = sorted((r for r in mom if r.release_date <= as_of), key=lambda r: r.ref_period)
    if len(known) >= months:
        last = known[-months:]
        acc = 1.0
        for r in last:
            acc *= 1 + r.value
        return PeriodInflation(acc - 1, f"cpi_mom × {months}", tuple(last))
    if months == 12:
        y = sorted((r for r in yoy if r.release_date <= as_of), key=lambda r: r.ref_period)
        if y:
            return PeriodInflation(y[-1].value, "cpi_yoy", (y[-1],))
    return None


def annualised(monthly: float) -> float:
    """docs/07 threshold: ``(1 + π_m)^12 − 1`` (1.044^12 − 1 ≈ 67%)."""
    return (1 + monthly) ** 12 - 1
