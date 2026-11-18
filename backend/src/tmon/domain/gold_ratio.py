"""Domestic gold against the ounce and the free dollar, and Brent against gold (pure functions).

The measured study is docs/reports/gold-oil-2026-11.md (backend/research/market_method/
gold_oil_study.py). Weeks run Thursday to Wednesday and take each series' last value, as in the
study. The cut points below are the 20th and 80th percentiles of the deviation from the 52-week
mean in the study's first half (2013-2020); the second half was judged on them.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

GRAM_PER_OUNCE = 31.1035
GOLD_18K_PURITY = 0.75
COIN_GRAMS = 8.133
COIN_PURITY = 0.9
MEAN_WEEKS = 52
MIN_WEEKS = 26
RANK_DAYS = 1095
# (low, high) cuts on the deviation from the 52-week mean, from the study's first half
GOLD_PREM_CUTS = (-0.025, 0.016)
COIN_BUBBLE_CUTS = (-0.034, 0.039)

State = Literal["high", "normal", "low"]
SERIES = ("usd_free", "gold_18k", "coin_emami", "gold_usd", "brent_usd")


@dataclass(frozen=True)
class Ratio:
    value: float
    mean_52w: float | None
    deviation: float | None
    pct_rank_3y: float
    state: State | None


@dataclass(frozen=True)
class GoldOil:
    week: date
    usd_free: float
    gold_18k: float
    coin_emami: float
    gold_usd: float
    brent_usd: float
    gold_18k_fair: float
    coin_fair: float
    usd_implied: float
    gold_prem: Ratio
    coin_bubble: Ratio
    oil_gold: Ratio


def week_of(d: date) -> date:
    """Monday that labels the Thursday-to-Wednesday week holding ``d``."""
    w = d + timedelta(days=4)
    return w - timedelta(days=w.weekday())


def weekly(points: dict[str, list[tuple[date, float]]], fill: int = 2) -> list[dict[str, float]]:
    """Last value per week for every series, carried forward at most ``fill`` weeks; only weeks
    where all series have a value are kept. Each row also holds its week under ``"week"``
    as an ordinal."""
    per: dict[str, dict[date, float]] = {}
    for s, pts in points.items():
        last: dict[date, tuple[date, float]] = {}
        for d, v in pts:
            if v and v > 0:
                k = week_of(d)
                if k not in last or d >= last[k][0]:
                    last[k] = (d, v)
        per[s] = {k: v for k, (_, v) in last.items()}
    if not per:
        return []
    weeks = sorted(set().union(*(set(v) for v in per.values())))
    first, end = weeks[0], weeks[-1]
    rows: list[dict[str, float]] = []
    carry: dict[str, tuple[float, int]] = {}
    w = first
    while w <= end:
        row: dict[str, float] = {"week": float(w.toordinal())}
        ok = True
        for s in points:
            if w in per[s]:
                carry[s] = (per[s][w], 0)
            elif s in carry and carry[s][1] < fill:
                carry[s] = (carry[s][0], carry[s][1] + 1)
            else:
                carry.pop(s, None)
            if s in carry:
                row[s] = carry[s][0]
            else:
                ok = False
        if ok:
            rows.append(row)
        w += timedelta(days=7)
    return rows


def _ratio(values: list[float], weeks: list[date], cuts: tuple[float, float] | None) -> Ratio:
    now = values[-1]
    past = values[-MEAN_WEEKS:]
    mean = sum(past) / len(past) if len(past) >= MIN_WEEKS else None
    dev = None if mean is None else now - mean
    since = weeks[-1] - timedelta(days=RANK_DAYS)
    recent = sorted(v for v, w in zip(values, weeks, strict=True) if w >= since)
    rank = bisect_left(recent, now) / len(recent)
    state: State | None = None
    if dev is not None and cuts is not None:
        state = "high" if dev > cuts[1] else "low" if dev < cuts[0] else "normal"
    return Ratio(now, mean, dev, rank, state)


def gold_oil(points: dict[str, list[tuple[date, float]]]) -> GoldOil | None:
    rows = weekly({s: points.get(s, []) for s in SERIES})
    if len(rows) < MIN_WEEKS:
        return None
    weeks = [date.fromordinal(int(r["week"])) for r in rows]
    prem, bub, oil = [], [], []
    for r in rows:
        gram = r["gold_usd"] * r["usd_free"] / GRAM_PER_OUNCE
        prem.append(r["gold_18k"] / (gram * GOLD_18K_PURITY) - 1)
        bub.append(r["coin_emami"] / (gram * COIN_GRAMS * COIN_PURITY) - 1)
        oil.append(r["brent_usd"] / r["gold_usd"])
    last = rows[-1]
    gram = last["gold_usd"] * last["usd_free"] / GRAM_PER_OUNCE
    return GoldOil(
        week=weeks[-1],
        usd_free=last["usd_free"],
        gold_18k=last["gold_18k"],
        coin_emami=last["coin_emami"],
        gold_usd=last["gold_usd"],
        brent_usd=last["brent_usd"],
        gold_18k_fair=gram * GOLD_18K_PURITY,
        coin_fair=gram * COIN_GRAMS * COIN_PURITY,
        usd_implied=last["gold_18k"] * GRAM_PER_OUNCE / (GOLD_18K_PURITY * last["gold_usd"]),
        gold_prem=_ratio(prem, weeks, GOLD_PREM_CUTS),
        coin_bubble=_ratio(bub, weeks, COIN_BUBBLE_CUTS),
        oil_gold=_ratio(oil, weeks, None),
    )
