"""Walk-forward evaluation with purging and embargo (docs/10 section 5).

Folds move forward through the trading calendar. The model for a fold is fitted on samples
that are completely resolved before the fold starts:

* **purge**: a training sample whose label window (``exit_date``) reaches the test start is
  dropped, so no label is built from prices the model is later tested on;
* **embargo**: additionally, training samples must lie at least ``embargo`` trading days before
  the test start (``embargo = horizon``).

Halt days are not part of the calendar, so folds skip over the halt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config


class Strategy(Protocol):
    """A scorer. ``predict`` returns ``instrument_id, date, signal`` (bool) and ``score``
    (higher = better), optionally ``p_win`` and ``ev``."""

    name: str

    def fit(self, train: pl.DataFrame) -> None: ...

    def predict(self, test: pl.DataFrame) -> pl.DataFrame: ...


@dataclass(frozen=True)
class Fold:
    index: int
    train_cutoff: date  # last decision date allowed in training
    test_start: date
    test_end: date


def make_folds(
    dates: list[date],
    *,
    horizon: int,
    embargo: int,
    retrain_every: int,
    min_train_days: int,
) -> list[Fold]:
    """Folds over the sorted unique trading ``dates``. The first test day is the first day at
    which ``min_train_days`` of fully resolved, embargoed history exist."""
    if retrain_every < 1:
        raise ValueError("retrain_every must be >= 1")
    ds = sorted(set(dates))
    gap = max(embargo, horizon) + 1  # training decisions must be <= test_start_idx - gap
    first_test = min_train_days + gap
    folds: list[Fold] = []
    i = first_test
    while i < len(ds):
        j = min(i + retrain_every - 1, len(ds) - 1)
        folds.append(Fold(len(folds), ds[i - gap], ds[i], ds[j]))
        i = j + 1
    return folds


def training_rows(ds: pl.DataFrame, fold: Fold) -> pl.DataFrame:
    return ds.filter(
        pl.col("trainable")
        & (pl.col("date") <= fold.train_cutoff)
        & (pl.col("exit_date") < fold.test_start)  # purge
    )


@dataclass
class WalkForwardResult:
    predictions: pl.DataFrame
    folds: list[Fold]
    train_sizes: list[int]


def run_walk_forward(
    ds: pl.DataFrame,
    make_strategy: Callable[[], Strategy],
    *,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> WalkForwardResult:
    c = cfg or get_engine_config()
    horizon = c.labeling.timeframes[timeframe].horizon_days
    dates = ds["date"].unique().sort().to_list()
    folds = make_folds(
        dates,
        horizon=horizon,
        embargo=horizon if c.validation.embargo_equals_horizon else 0,
        retrain_every=c.validation.retrain_every_days,
        min_train_days=c.validation.min_train_days,
    )
    parts: list[pl.DataFrame] = []
    sizes: list[int] = []
    for fold in folds:
        train = training_rows(ds, fold)
        sizes.append(train.height)
        strat = make_strategy()
        strat.fit(train)
        test = ds.filter(
            (pl.col("date") >= fold.test_start)
            & (pl.col("date") <= fold.test_end)
            & pl.col("in_universe")
        )
        if test.is_empty():
            continue
        pred = strat.predict(test).with_columns(pl.lit(fold.index).alias("fold"))
        parts.append(pred)
    out = pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame()
    return WalkForwardResult(out, folds, sizes)
