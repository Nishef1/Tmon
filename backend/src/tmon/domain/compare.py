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


@dataclass(frozen=True)
class InflationSince:
    value: float
    last_ref: date  # end of the last month covered by a release
    estimated_days: int  # days after ``last_ref``, carried at the last month's rate


def inflation_since(mom: Sequence[Release], start: date, as_of: date) -> InflationSince | None:
    """Consumer-price inflation from ``start`` to ``as_of`` (docs/07, the portfolio's bar): each
    released month spread evenly over its days (geometric), a partial month counted by its days,
    and the days after the last released month carried at that month's rate, counted in
    ``estimated_days`` so the page can say so. Only releases out by ``as_of``. ``None`` when no
    release ends before ``start`` (the first release's month cannot be placed)."""
    known = sorted((r for r in mom if r.release_date <= as_of), key=lambda r: r.ref_period)
    if not known or start < known[0].ref_period or start >= as_of:
        return None
    acc, prev = 1.0, None
    for r in known:
        if prev is not None:
            a, b = max(prev, start), min(r.ref_period, as_of)
            if b > a:
                acc *= (1 + r.value) ** ((b - a).days / (r.ref_period - prev).days)
        prev = r.ref_period
    last = known[-1]
    extra = max(0, (as_of - max(last.ref_period, start)).days)
    if extra:
        span = (last.ref_period - known[-2].ref_period).days if len(known) > 1 else 30
        acc *= (1 + last.value) ** (extra / span)
    return InflationSince(acc - 1, last.ref_period, extra)


def annualised(monthly: float) -> float:
    """docs/07 threshold: ``(1 + π_m)^12 − 1`` (1.044^12 − 1 ≈ 67%)."""
    return (1 + monthly) ** 12 - 1
