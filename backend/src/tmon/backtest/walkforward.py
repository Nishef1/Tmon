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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.features.builder import KEYS
from tmon.labeling.grid import PAIR_COLUMNS, Combo, with_labels


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
    # per fold: chosen barrier pair and every pair's inner-validation score (empty without a grid)
    fold_infos: list[dict[str, Any]] = field(default_factory=list)


def run_walk_forward(
    ds: pl.DataFrame,
    make_strategy: Callable[[], Strategy],
    *,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
    label_sets: Mapping[Combo, pl.DataFrame] | None = None,
) -> WalkForwardResult:
    """Walk-forward evaluation.

    With ``label_sets`` (one label frame per barrier pair, ADR 0002 section 4) and a strategy that
    has ``fit_grid``, each fold lets the strategy choose its pair from the *training window only*
    (labels purged before the test start). The test rows of the fold are then labelled with the
    chosen pair, and the label columns travel with the predictions so the simulator trades exactly
    those barriers. Without them the labels already in ``ds`` are used.
    """
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
    infos: list[dict[str, Any]] = []
    for fold in folds:
        strat = make_strategy()
        grid = label_sets is not None and hasattr(strat, "fit_grid")
        test = ds.filter(
            (pl.col("date") >= fold.test_start)
            & (pl.col("date") <= fold.test_end)
            & pl.col("in_universe")
        )
        if grid:
            assert label_sets is not None
            window = ds.filter(pl.col("in_universe") & (pl.col("date") <= fold.train_cutoff))

            def train_for(
                combo: Combo, window: pl.DataFrame = window, fold: Fold = fold
            ) -> pl.DataFrame:
                return training_rows(with_labels(window, label_sets[combo]), fold)

            gs: Any = strat  # strategies with a grid expose fit_grid and info
            combo = gs.fit_grid(list(label_sets), train_for)
            sizes.append(int(gs.info.get("n_train_rows", 0)))
            test = with_labels(test, label_sets[combo])
            infos.append(
                {
                    "fold": fold.index,
                    "k_tp": combo[0],
                    "k_sl": combo[1],
                    "by_score": bool(gs.info.get("grid_selected_by_score", False)),
                    "grid": gs.info.get("grid", []),
                }
            )
        else:
            train = training_rows(ds, fold)
            sizes.append(train.height)
            strat.fit(train)
        if test.is_empty():
            continue
        pred = strat.predict(test).with_columns(pl.lit(fold.index).alias("fold"))
        if grid:
            keep = [col for col in PAIR_COLUMNS if col not in pred.columns]
            pred = pred.join(test.select(*KEYS, *keep), on=list(KEYS), how="left")
            if "k_tp" not in pred.columns:  # strategies that do not report the pair
                pred = pred.with_columns(
                    pl.lit(combo[0]).alias("k_tp"), pl.lit(combo[1]).alias("k_sl")
                )
        parts.append(pred)
    out = pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame()
    return WalkForwardResult(out, folds, sizes, infos)
