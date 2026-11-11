"""Feature builder: raw ingested tables -> point-in-time feature frame.

Pipeline (all vectorised Polars, no per-row loops)::

    prices + events -> adjusted OHLCV -> technical -> board -> structure -> market -> flags

Every feature at date ``t`` depends only on rows ``<= t`` of the same instrument or on the
rows of date ``t`` across instruments. ``tests/test_pit.py`` proves this by truncation.

Feature sets are versioned and selected per timeframe. Only D1 exists in Phase 1; asking for
W1/M1 raises so nothing silently trains on the wrong columns.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features import indicators as ind
from tmon.features.adjustment import apply_adjustments
from tmon.features.market import add_market_features
from tmon.features.orderbook import add_board_features, add_order_book

G = "instrument_id"
KEYS = ("instrument_id", "date")

TECHNICAL_COLUMNS: tuple[str, ...] = (
    *(f"ret_{n}" for n in ind.RET_WINDOWS),
    *(f"roc_{n}" for n in ind.ROC_WINDOWS),
    *(f"sma_{n}_dist" for n in ind.SMA_WINDOWS),
    *(f"ema_{n}_dist" for n in ind.SMA_WINDOWS),
    "macd_pct", "macd_signal_pct", "macd_hist_pct",
    "adx_14", "plus_di", "minus_di",
    "ichi_tenkan_dist", "ichi_kijun_dist", "ichi_tk_diff",
    "ichi_cloud_top_dist", "ichi_cloud_bottom_dist", "ichi_chikou_cmp",
    "rsi_14", "stoch_k", "stoch_d", "willr_14",
    "atr_14_pct", "bb_pct_b", "bb_bandwidth", "rv_20",
    "obv_chg_20", "mfi_14", "vwap_gap",
    "dist_high_20", "dist_low_20", "dist_high_52w", "dist_low_52w",
    "breakout_20_vol", "pivot_dist", "pivot_r1_dist", "pivot_s1_dist",
)  # fmt: skip

BOARD_COLUMNS: tuple[str, ...] = (
    "ind_buy_power", "ind_net_flow_ratio", "ind_net_flow_z", "inst_to_ind",
    "rel_volume", "vol_to_base", "smart_money_flag", "last_close_gap",
    "intraday_range_pos", "ret_1_norm", "queue_code", "days_in_queue",
)  # fmt: skip

MARKET_COLUMNS: tuple[str, ...] = (
    "mkt_ret_ew", "mkt_ret_vw", "breadth", "mkt_ind_net_flow_ratio",
    "mkt_ind_net_flow_z", "mkt_ret_ew_5d", "mkt_ret_ew_20d",
    "mkt_ind_net_flow_ratio_5d", "rel_ret_market", "rel_ret_sector", "sector_ret_ew",
)  # fmt: skip

# Stored and displayed, but never fed to a model: scale-variant in rial terms, mostly
# empty historically, or bookkeeping.
REFERENCE_COLUMNS: tuple[str, ...] = (
    "ind_buy_per_capita", "ind_sell_per_capita", "ind_net_flow", "atr_14",
    "mkt_value", "mkt_retail_buy_value", "mkt_ind_net_flow",
    "ob_imbalance", "queue_to_base", "queue_state", "client_value_estimated",
    "median_value_20", "history_len", "limit_pct",
)  # fmt: skip

FLAG_COLUMNS: tuple[str, ...] = ("market_halt", "eligible")


class UnsupportedTimeframeError(NotImplementedError):
    pass


@dataclass(frozen=True)
class FeatureSet:
    timeframe: str
    version: str
    columns: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        """Hash of the ordered column list: changes whenever the model input changes."""
        return hashlib.sha256("|".join(self.columns).encode()).hexdigest()[:12]

    @property
    def key(self) -> str:
        """Value stored in ``features.feature_set_version``."""
        return f"{self.timeframe}_{self.version}_{self.fingerprint}"


_D1 = FeatureSet("D1", "v1", TECHNICAL_COLUMNS + BOARD_COLUMNS + MARKET_COLUMNS)
FEATURE_SETS: dict[str, FeatureSet] = {"D1": _D1}


def get_feature_set(timeframe: str) -> FeatureSet:
    try:
        return FEATURE_SETS[timeframe]
    except KeyError:
        raise UnsupportedTimeframeError(
            f"no feature set for timeframe {timeframe!r}; "
            f"only {sorted(FEATURE_SETS)} exist in Phase 1"
        ) from None


def limit_pct_expr(rules: RuleBook, *, date_col: str = "date") -> pl.Expr:
    """Daily price-limit fraction as a Polars expression built from ``market_rules`` records
    (later ``valid_from`` wins). Null where no rule is valid."""
    expr = pl.lit(None, dtype=pl.Float64)
    for rec in rules.all_for("price_limit"):  # ascending valid_from
        cond = pl.col(date_col) >= rec.valid_from
        if rec.valid_to is not None:
            cond = cond & (pl.col(date_col) <= rec.valid_to)
        expr = pl.when(cond).then(pl.lit(float(rec.value["pct"]))).otherwise(expr)
    return expr


def build_features(
    prices: pl.DataFrame,
    client_types: pl.DataFrame | None,
    rules: RuleBook,
    *,
    sectors: pl.DataFrame | None = None,
    order_book_imbalance: pl.DataFrame | None = None,
    config: EngineConfig | None = None,
) -> pl.DataFrame:
    """Build the full feature frame (``KEYS`` + flags + model + reference columns).

    ``prices``: ``instrument_id, date, open, high, low, close, last, prev_close, volume, value,
    base_volume, market_halt`` (raw, unadjusted). ``client_types``: ``instrument_id, date`` and
    the twelve ``{buy,sell}_{count,volume,value}_{i,n}`` columns, or ``None``.
    """
    cfg = config or get_engine_config()
    if prices.is_empty():
        raise ValueError("no price rows to build features from")

    d = prices.sort(KEYS)
    for optional in ("base_volume", "market_halt"):
        if optional not in d.columns:
            d = d.with_columns(
                pl.lit(None, dtype=pl.Float64).alias(optional)
                if optional == "base_volume"
                else pl.lit(False).alias(optional)
            )
    d = d.with_columns(pl.col("market_halt").fill_null(False))

    d = apply_adjustments(d)
    d = ind.add_trend_momentum_volatility_volume(d)
    d = ind.add_vwap_gap(d)

    client_cols = [
        f"{s}_{m}_{k}"
        for s in ("buy", "sell")
        for m in ("count", "volume", "value")
        for k in ("i", "n")
    ]
    if client_types is not None and not client_types.is_empty():
        d = d.join(client_types.select(*KEYS, *client_cols), on=list(KEYS), how="left")
    else:
        d = d.with_columns([pl.lit(None, dtype=pl.Float64).alias(c) for c in client_cols])
    d = d.with_columns(limit_pct_expr(rules).alias("limit_pct"))

    d = add_board_features(d)
    d = add_order_book(d, order_book_imbalance)
    d = ind.add_structure(d)
    d = d.with_columns(
        pl.col("value").rolling_median(20).over(G).alias("median_value_20"),
        pl.int_range(pl.len()).over(G).add(1).alias("history_len"),
    )
    d = add_market_features(d, sectors)
    d = d.with_columns(
        (
            (pl.col("median_value_20") >= cfg.universe.min_median_value_20d)
            & (pl.col("history_len") >= cfg.universe.min_history_days)
            & ~pl.col("market_halt")
        )
        .fill_null(False)
        .alias("eligible")
    )
    keep = [*KEYS, *FLAG_COLUMNS, *_D1.columns, *REFERENCE_COLUMNS]
    return d.select(list(dict.fromkeys(keep))).sort(KEYS)


def model_matrix(features: pl.DataFrame, timeframe: str = "D1") -> pl.DataFrame:
    """Rows that may be used for training or scoring (outside halt windows). Columns: keys +
    the timeframe's feature set. Warm-up rows stay and carry nulls, which the model tolerates;
    the ``eligible`` flag is what enforces minimum history."""
    fs = get_feature_set(timeframe)
    return features.filter(~pl.col("market_halt")).select(*KEYS, *fs.columns)
