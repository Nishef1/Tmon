"""When may the engine publish tier A? (docs/10 section 9-10)

The rule is deliberately conservative and explicit. Tier A is allowed only if, in the
out-of-sample walk-forward after costs, the model

1. produced at least ``model.tier_a_min_trades`` trades (fewer is noise),
2. had a positive net expectancy per trade,
3. beat the rule-based baseline on both net expectancy and total return, and
4. was calibrated better than a constant base-rate forecast (positive Brier skill), when
   probabilities are available.

Otherwise ``tier_a_allowed`` is False and every reason is reported in plain language, so the
UI and the report can say *why* no tier-A signal exists. After publication the same switch is
thrown by :func:`brier_degraded` (docs/10 section 10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss

from tmon.core.engine_config import EngineConfig, get_engine_config

BRIER_DEGRADATION_LIMIT = 0.20  # docs/10 section 10: 20% worse than in the backtest
BRIER_RECENT_DAYS = 20


@dataclass(frozen=True)
class GateResult:
    tier_a_allowed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tier_a_allowed": self.tier_a_allowed, "reasons": self.reasons}


def evaluate_gate(
    challenger: dict[str, Any],
    baseline: dict[str, Any] | None,
    cfg: EngineConfig | None = None,
) -> GateResult:
    """``challenger``/``baseline`` are strategy summaries from the backtest runner."""
    c = cfg or get_engine_config()
    reasons: list[str] = []
    t = challenger.get("trades", {})
    p = challenger.get("portfolio", {})
    n = int(t.get("n_trades", 0))
    if n < c.model.tier_a_min_trades:
        reasons.append(
            f"تعداد معاملات خارج از نمونه ({n}) کمتر از حداقل {c.model.tier_a_min_trades} است."
        )
    exp = t.get("expectancy_net")
    if exp is None or exp <= 0:
        reasons.append("امید ریاضی خالص هر معامله پس از هزینه مثبت نیست.")
    if baseline is not None and baseline.get("trades", {}).get("n_trades", 0) > 0:
        be = baseline["trades"].get("expectancy_net")
        btr = baseline["portfolio"].get("total_return")
        if exp is None or be is None or exp <= be:
            reasons.append("امید ریاضی مدل از baseline بیشتر نیست.")
        tr = p.get("total_return")
        if tr is None or btr is None or tr <= btr:
            reasons.append("بازده کل مدل پس از هزینه از baseline بیشتر نیست.")
    prob = challenger.get("probabilistic")
    if prob is not None:
        skill = prob.get("brier_skill")
        if skill is None or skill <= 0:
            reasons.append("کالیبراسیون از پیش‌بینی ثابت نرخ پایه بهتر نیست.")
    return GateResult(not reasons, reasons)


def brier_degraded(
    recent_p: np.ndarray,
    recent_y: np.ndarray,
    backtest_brier: float,
    *,
    limit: float = BRIER_DEGRADATION_LIMIT,
) -> bool:
    """True if the recent Brier score is more than ``limit`` worse than the backtest's."""
    if recent_p.size == 0 or backtest_brier <= 0:
        return False
    recent = float(brier_score_loss(recent_y, recent_p))
    return recent > backtest_brier * (1 + limit)
