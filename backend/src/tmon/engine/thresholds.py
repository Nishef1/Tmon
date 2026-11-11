"""Break-even thresholds, signal rule and tiers (ADR 0002 section 3).

For one probability bucket with ``W = E[return | win]``, ``L = -E[return | not win]`` (the size of
the average loss, taken from every ``y = 0`` row: stop-loss, same-day and expiry) and a round-trip
cost ``c``::

    p_breakeven = (L + c) / (W + L)          # EV_net = p*W - (1-p)*L - c = 0
    p_min       = max(p_breakeven + margin, p_floor)
    signal      = p >= p_min  and  EV_net >= ev_min_abs  and  bucket_n >= min_bucket_samples

Tiers are offsets above the break-even probability, so the confidence labels keep their meaning
whatever the payoff ratio of the barrier pair is.  ``L`` is the *signed* negative of the bucket's
mean non-win return, so that ``p_breakeven`` is exactly the root of the same ``EV_net`` that is
tested afterwards (a bucket whose non-winners average a gain has ``L < 0``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tmon.core.engine_config import ModelCfg, ThresholdsCfg


def breakeven_probability(win: np.ndarray, loss: np.ndarray, cost: np.ndarray) -> np.ndarray:
    """``(L + c) / (W + L)``; NaN where ``W + L`` is not positive (no payoff to break even on)."""
    win, loss, cost = (np.asarray(a, dtype=float) for a in (win, loss, cost))
    span = win + loss
    with np.errstate(divide="ignore", invalid="ignore"):
        be = (loss + cost) / span
    return np.asarray(np.where(span > 0, be, np.nan))


def minimum_probability(
    p_breakeven: np.ndarray, margin: float, floor: float, bump: np.ndarray | float = 0.0
) -> np.ndarray:
    """``max(p_breakeven + margin, floor)`` plus the defensive-mode bump. NaN stays NaN."""
    return np.asarray(np.maximum(np.asarray(p_breakeven) + margin, floor) + bump)


def expected_value(
    p: np.ndarray, win: np.ndarray, e_loss: np.ndarray, cost: np.ndarray
) -> np.ndarray:
    """Net expected return of a trade: ``p*W + (1-p)*E[return | not win] - c``."""
    return np.asarray(p * win + (1 - p) * e_loss - cost)


@dataclass(frozen=True)
class Decision:
    signal: np.ndarray
    tier: np.ndarray
    tier_a_eligible: np.ndarray
    p_breakeven: np.ndarray
    p_min: np.ndarray
    ev: np.ndarray


def decide(
    p: np.ndarray,
    e_win: np.ndarray,
    e_loss: np.ndarray,
    cost: np.ndarray,
    bucket_n: np.ndarray,
    recent_n: np.ndarray,
    recent_accuracy: np.ndarray,
    *,
    thresholds: ThresholdsCfg,
    model: ModelCfg,
    defensive_bump: np.ndarray | float = 0.0,
    allow_tier_a: bool = False,
    enforce: bool = True,
) -> Decision:
    """Apply the ADR 0002 rules to rows whose bucket statistics are already looked up.

    ``enforce=False`` is the diagnostic view: any row with positive net EV and a populated
    bucket is a "signal" (never published).
    """
    t = thresholds
    p_be = breakeven_probability(e_win, -np.asarray(e_loss, dtype=float), cost)
    p_min = minimum_probability(p_be, t.margin, t.p_floor, defensive_bump)
    ev = expected_value(p, e_win, e_loss, cost)
    enough = np.asarray(bucket_n) >= t.min_bucket_samples
    if enforce:
        signal = np.isfinite(ev) & np.isfinite(p_min) & enough & (p >= p_min) & (ev >= t.ev_min_abs)
    else:
        signal = np.isfinite(ev) & enough & (ev > 0)

    ta, tb = t.tiers.A, t.tiers.B
    recent_ok = (np.asarray(recent_n) >= model.min_recent_samples) & (
        np.asarray(recent_accuracy) >= p_be + ta.recent_bucket_accuracy_margin
    )
    tier_a_ok = signal & (p >= p_be + ta.p_win_margin) & recent_ok
    tier = np.where(
        tier_a_ok & allow_tier_a,
        "A",
        np.where(signal & (p >= p_be + tb.p_win_margin), "B", "C"),
    )
    return Decision(signal, tier, tier_a_ok, p_be, p_min, ev)
