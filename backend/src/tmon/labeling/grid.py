"""Barrier grid (ADR 0002 section 4).

Every ``(k_tp, k_sl)`` pair of ``labeling.grid[timeframe]`` gets its own label set. The pair is
*chosen inside each walk-forward training window* (never on the test period), so the number of
pairs tried is a multiple-testing cost that every report discloses.
"""

from __future__ import annotations

from itertools import product

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS
from tmon.labeling.relative import apply_target
from tmon.labeling.triple_barrier import prepare_bars, triple_barrier_labels

Combo = tuple[float, float]  # (k_tp, k_sl)

# label columns that depend on the barrier pair (see backtest.dataset.LABEL_COLUMNS)
PAIR_COLUMNS = (
    "entry_date", "exit_date", "entry_price", "tp_price", "sl_price", "y", "exit_reason",
    "exit_day", "realized_return", "executable", "exit_delayed", "valid",
)  # fmt: skip


def grid_combos(timeframe: str, cfg: EngineConfig | None = None) -> list[Combo]:
    """All pairs of the grid, in a fixed order (``k_tp`` major)."""
    g = (cfg or get_engine_config()).labeling.grid[timeframe]
    return [(float(a), float(b)) for a, b in product(g.k_tp, g.k_sl)]


def default_combo(timeframe: str, cfg: EngineConfig | None = None) -> Combo:
    """The configured default pair if it is in the grid, else the first pair of the grid."""
    c = cfg or get_engine_config()
    combos = grid_combos(timeframe, c)
    want = (float(c.labeling.k_tp), float(c.labeling.k_sl))
    return want if want in combos else combos[0]


def label_sets(
    prices: pl.DataFrame,
    rules: RuleBook,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> dict[Combo, pl.DataFrame]:
    """One label frame per grid pair, with the timeframe's target applied (bars and ATR are
    prepared once)."""
    c = cfg or get_engine_config()
    bars = prepare_bars(prices, rules, c)
    return {
        combo: apply_target(
            triple_barrier_labels(
                prices, rules, timeframe, c, k_tp=combo[0], k_sl=combo[1], bars=bars
            ),
            timeframe,
            c,
        )
        for combo in grid_combos(timeframe, c)
    }


def with_labels(ds: pl.DataFrame, labels: pl.DataFrame) -> pl.DataFrame:
    """``ds`` with the pair-dependent label columns replaced by ``labels``' and ``trainable``
    recomputed (it depends on ``valid`` and ``executable``)."""
    d = ds.drop([c for c in PAIR_COLUMNS if c in ds.columns]).join(
        labels.select(*KEYS, *PAIR_COLUMNS), on=list(KEYS), how="left"
    )
    d = d.with_columns(pl.col("valid").fill_null(False), pl.col("executable").fill_null(False))
    return d.with_columns(
        (pl.col("in_universe") & pl.col("valid") & pl.col("executable")).alias("trainable")
    )
