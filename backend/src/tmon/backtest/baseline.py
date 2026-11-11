"""Rule-based D1 baseline (docs/10 section 4, stage 1). A yardstick, never a product signal."""

from __future__ import annotations

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config


class BaselineD1:
    """Enter when real-investor money is flowing in, the board is lively, the close is above
    the day's VWAP and RSI is neither weak nor overbought. Thresholds come from engine.yaml.
    Candidates on a day are ranked by real-investor buy power."""

    name = "baseline_d1"

    def __init__(self, cfg: EngineConfig | None = None) -> None:
        self.cfg = (cfg or get_engine_config()).baseline_d1

    def fit(self, train: pl.DataFrame) -> None:  # fixed rules: nothing to learn
        return None

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        b = self.cfg
        rule = (
            (pl.col("ind_net_flow") > 0)
            & (pl.col("ind_buy_power") > b.min_ind_buy_power)
            & (pl.col("rel_volume") > b.min_rel_volume)
            & (pl.col("vwap_gap") > 0)
            & pl.col("rsi_14").is_between(b.rsi_min, b.rsi_max)
        ).fill_null(False)
        return test.select(
            "instrument_id",
            "date",
            rule.alias("signal"),
            pl.col("ind_buy_power").fill_null(0.0).alias("score"),
        )
