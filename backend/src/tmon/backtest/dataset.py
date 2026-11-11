"""Join features with triple-barrier labels into the frame every strategy works on."""

from __future__ import annotations

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.features.builder import KEYS

LABEL_COLUMNS = (
    "entry_date", "exit_date", "entry_price", "tp_price", "sl_price", "y", "exit_reason",
    "exit_day", "realized_return", "executable", "exit_delayed", "valid",
)  # fmt: skip


def build_dataset(
    features: pl.DataFrame, labels: pl.DataFrame, cfg: EngineConfig | None = None
) -> pl.DataFrame:
    """Feature rows (halt days removed) left-joined to their labels.

    Adds ``in_universe``: liquid, enough history, not a halt day and not in an excluded queue
    state at the decision time ``t``. ``trainable`` additionally needs a resolved label and an
    executable entry (docs/10 section 2: unexecutable samples are dropped from training).
    """
    c = cfg or get_engine_config()
    f = features.filter(~pl.col("market_halt"))
    lab = labels.select(*KEYS, *LABEL_COLUMNS)
    d = f.join(lab, on=list(KEYS), how="left").with_columns(
        pl.col("valid").fill_null(False), pl.col("executable").fill_null(False)
    )
    d = d.with_columns(
        (pl.col("eligible") & ~pl.col("queue_state").is_in(c.universe.exclude_queue_states))
        .fill_null(False)
        .alias("in_universe")
    )
    return d.with_columns(
        (pl.col("in_universe") & pl.col("valid") & pl.col("executable")).alias("trainable")
    ).sort(KEYS)
