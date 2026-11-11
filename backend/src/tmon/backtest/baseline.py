"""Rule-based D1 baseline (docs/10 section 4, stage 1). A yardstick, never a product signal."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.costs import add_costs
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.labeling.grid import Combo, default_combo
from tmon.models.splits import split_training_window


class BaselineD1:
    """Enter when real-investor money is flowing in, the board is lively, the close is above
    the day's VWAP and RSI is neither weak nor overbought. Thresholds come from engine.yaml.
    Candidates on a day are ranked by real-investor buy power.

    The entry rule has nothing to learn, but the barrier pair is chosen the same way as for the
    model (``fit_grid``, ADR 0002 section 4) so that the comparison does not hand the challenger a
    tuned exit and the baseline a fixed one. Without ``rules`` the default pair is used.
    """

    name = "baseline_d1"

    def __init__(
        self,
        cfg: EngineConfig | None = None,
        rules: RuleBook | None = None,
        timeframe: str = "D1",
    ) -> None:
        self.engine_cfg = cfg or get_engine_config()
        self.cfg = self.engine_cfg.baseline_d1
        self.rules = rules
        self.timeframe = timeframe
        self.barrier: Combo = default_combo(timeframe, self.engine_cfg)
        self.info: dict[str, Any] = {}

    def fit(self, train: pl.DataFrame) -> None:  # fixed rules: nothing to learn
        return None

    def _rule(self) -> pl.Expr:
        b = self.cfg
        return (
            (pl.col("ind_net_flow") > 0)
            & (pl.col("ind_buy_power") > b.min_ind_buy_power)
            & (pl.col("rel_volume") > b.min_rel_volume)
            & (pl.col("vwap_gap") > 0)
            & pl.col("rsi_14").is_between(b.rsi_min, b.rsi_max)
        ).fill_null(False)

    def fit_grid(
        self, combos: Sequence[Combo], train_for: Callable[[Combo], pl.DataFrame]
    ) -> Combo:
        """Pick the pair whose baseline signals earned the best mean net return per trade on the
        last ``model.calibration_fraction`` of the training window (the inner validation slice)."""
        c = self.engine_cfg
        default = default_combo(self.timeframe, c)
        log: list[dict[str, Any]] = []
        best: tuple[float, Combo] | None = None
        rows = 0
        for combo in combos:
            train = train_for(combo)
            rows = max(rows, train.height)
            sp = split_training_window(train, c.model) if self.rules is not None else None
            rec: dict[str, Any] = {"k_tp": combo[0], "k_sl": combo[1], "usable": sp is not None}
            if sp is None or self.rules is None:
                log.append({**rec, "n_signals": 0, "score": None})
                continue
            val = sp.calibration
            sig = val.select(self._rule().alias("s"))["s"].to_numpy().astype(bool)
            n = int(sig.sum())
            score: float | None = None
            if n >= c.model.grid_min_signals:
                net = add_costs(
                    val.select("entry_date", "exit_date", "realized_return"),
                    self.rules,
                    c.costs.slippage_fraction,
                )["net_return"].to_numpy()
                score = float(np.mean(net[sig]))
            log.append({**rec, "n_signals": n, "score": score})
            if score is not None and (best is None or score > best[0]):
                best = (score, combo)
        self.barrier = best[1] if best else default
        self.info = {
            "n_train_rows": rows,
            "grid": log,
            "grid_selected_by_score": best is not None,
            "barrier": list(self.barrier),
        }
        return self.barrier

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        return test.select(
            "instrument_id",
            "date",
            self._rule().alias("signal"),
            pl.col("ind_buy_power").fill_null(0.0).alias("score"),
        )
