"""Chronological split of one training window (ADR 0002 section 5, docs/10 section 6).

::

    | fit (trees) | early stopping | cal_a (isotonic) | cal_b (bucket statistics) |

* the trees see only ``fit`` and stop on ``es``;
* the isotonic map ``raw score -> p`` is fitted on ``cal_a``;
* the per-bucket statistics (count, accuracy, ``W``, ``L``) come from ``cal_b``, which neither the
  trees nor the isotonic map ever saw, so ``W`` and ``L`` are not flattered by the fit.

A row is kept in a part only if its label window is resolved before the next part begins
(``exit_date`` purge), so no label is computed from prices that a later part is judged on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from tmon.core.engine_config import ModelCfg


@dataclass(frozen=True)
class TrainSplit:
    fit: pl.DataFrame
    es: pl.DataFrame
    cal_a: pl.DataFrame
    cal_b: pl.DataFrame
    es_start: date
    cal_a_start: date
    cal_b_start: date
    recent_cut: date  # first day of the "recent" stretch used for the tier A accuracy check

    @property
    def calibration(self) -> pl.DataFrame:
        """The whole last slice: ``cal_a`` and ``cal_b`` (the inner validation slice)."""
        return pl.concat([self.cal_a, self.cal_b])


def split_training_window(train: pl.DataFrame, mc: ModelCfg) -> TrainSplit | None:
    """Split ``train`` (columns ``date``, ``exit_date``) in time order. ``None`` if too short."""
    dates = train["date"].unique().sort()
    n = dates.len()
    if n < 30:
        return None
    cal_i = int(n * (1 - mc.calibration_fraction))
    mid_i = cal_i + (n - cal_i) // 2
    es_i = int(n * (1 - mc.calibration_fraction - mc.early_stopping_fraction))
    if not 0 < es_i < cal_i < mid_i < n:
        return None
    es_start, cal_a_start, cal_b_start = dates[es_i], dates[cal_i], dates[mid_i]
    d, x = pl.col("date"), pl.col("exit_date")
    return TrainSplit(
        fit=train.filter((d < es_start) & (x < es_start)),
        es=train.filter((d >= es_start) & (d < cal_a_start) & (x < cal_a_start)),
        cal_a=train.filter((d >= cal_a_start) & (d < cal_b_start) & (x < cal_b_start)),
        cal_b=train.filter(d >= cal_b_start),
        es_start=es_start,
        cal_a_start=cal_a_start,
        cal_b_start=cal_b_start,
        recent_cut=dates[max(0, n - mc.recent_days)],
    )
