"""Relative target (OPEN_QUESTIONS 67, ADR 0003 section 4).

``y = 1`` when a trade's ``realized_return`` beats the median ``realized_return`` of every
usable trade (``valid`` and ``executable``) opened on the same decision date, else ``0``. The
barrier exits, ``realized_return`` and ``exit_reason`` stay as they are, so the bucket
statistics ``W = E[ret | y=1]`` and ``E[ret | y=0]`` keep the EV an absolute expected return.

Why: the absolute "TP before SL" target is mostly a bet on the day's market direction. The
model learned the market-wide features and gave most symbols one identical probability. A
same-day relative target removes the market direction from ``y`` so only cross-sectional
differences can be learned.
"""

from __future__ import annotations

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config


def relative_target(labels: pl.DataFrame) -> pl.DataFrame:
    """``labels`` with ``y`` replaced by "beat the same-day median of usable trades"."""
    usable = pl.col("valid") & pl.col("executable") & pl.col("realized_return").is_not_null()
    med = pl.col("realized_return").filter(usable).median().over("date")
    y = (
        pl.when(pl.col("valid") & pl.col("realized_return").is_not_null() & med.is_not_null())
        .then((pl.col("realized_return") > med).cast(pl.Int8))
        .otherwise(None)
    )
    return labels.with_columns(y.cast(labels.schema["y"]).alias("y"))


def apply_target(
    labels: pl.DataFrame, timeframe: str, cfg: EngineConfig | None = None
) -> pl.DataFrame:
    """Apply ``labeling.target[timeframe]`` (``barrier`` leaves the labels unchanged)."""
    c = cfg or get_engine_config()
    if c.labeling.target.get(timeframe, "barrier") == "relative":
        return relative_target(labels)
    return labels
