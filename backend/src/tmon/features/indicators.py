"""Vectorised technical indicators (docs/04, "اندیکاتورها").

Every function takes a Polars frame sorted by ``(instrument_id, date)`` that holds
*adjusted* OHLC prices and adjusted volume, and returns it with new columns. Windows are
trailing and include the current row, so a value at date ``t`` only depends on rows ``<= t``
(point-in-time safe; verified by ``tests/test_pit.py``).

Scale: every emitted feature is dimensionless (ratios, percentages, oscillators). Absolute
price levels are never emitted because adjusted levels change when a *future* event is
applied, which would leak.

There are no per-row Python loops: all recursion is expressed through ``ewm_mean`` and
rolling windows over ``instrument_id`` groups.
"""

from __future__ import annotations

import polars as pl

G = "instrument_id"

SMA_WINDOWS = (5, 10, 20, 50, 100, 200)
ROC_WINDOWS = (5, 10, 20)
RET_WINDOWS = (1, 5, 10, 20)
WEEK_TRADING_DAYS = 5  # Sat-Wed
YEAR_WINDOW = 52 * WEEK_TRADING_DAYS
TIE_TOLERANCE = 1e-9  # relative to price; see add_adx / add_volume_indicators


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


def wilder(x: pl.Expr, n: int) -> pl.Expr:
    """Wilder smoothing seeded with the SMA of the first ``n`` valid values.

    ``avg_t = (avg_{t-1} * (n - 1) + x_t) / n``. Must be evaluated per instrument; the caller
    wraps the result in ``.over(G)``.
    """
    k = x.is_not_null().cum_sum()
    seeded = pl.when(k == n).then(x.rolling_mean(n)).when(k > n).then(x).otherwise(None)
    return seeded.ewm_mean(alpha=1.0 / n, adjust=False)


def ema_expr(x: pl.Expr, n: int) -> pl.Expr:
    """``EMA_t = a * P_t + (1 - a) * EMA_{t-1}`` with ``a = 2 / (n + 1)`` (docs/04).

    Seeded with the first price; the first ``n - 1`` values are masked as warm-up.
    """
    return x.ewm_mean(span=n, adjust=False, min_samples=n)


def true_range() -> pl.Expr:
    prev_close = pl.col("adj_close").shift(1)
    return pl.max_horizontal(
        pl.col("adj_high") - pl.col("adj_low"),
        (pl.col("adj_high") - prev_close).abs(),
        (pl.col("adj_low") - prev_close).abs(),
    )


def _safe_div(num: pl.Expr, den: pl.Expr) -> pl.Expr:
    return pl.when(den != 0).then(num / den).otherwise(None)


# --------------------------------------------------------------------------- #
# Trend
# --------------------------------------------------------------------------- #


def add_returns(df: pl.DataFrame) -> pl.DataFrame:
    c = pl.col("adj_close")
    return df.with_columns(
        *[(c / c.shift(n) - 1.0).over(G).alias(f"ret_{n}") for n in RET_WINDOWS],
        *[((c / c.shift(n) - 1.0) * 100.0).over(G).alias(f"roc_{n}") for n in ROC_WINDOWS],
    )


def add_moving_averages(df: pl.DataFrame) -> pl.DataFrame:
    c = pl.col("adj_close")
    exprs: list[pl.Expr] = []
    for n in SMA_WINDOWS:
        exprs.append((c / c.rolling_mean(n) - 1.0).over(G).alias(f"sma_{n}_dist"))
        exprs.append((c / ema_expr(c, n) - 1.0).over(G).alias(f"ema_{n}_dist"))
    return df.with_columns(exprs)


def add_macd(df: pl.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pl.DataFrame:
    c = pl.col("adj_close")
    d = df.with_columns((ema_expr(c, fast) - ema_expr(c, slow)).over(G).alias("_macd"))
    d = d.with_columns(
        # signal EMA starts once MACD is valid: mask leading nulls via ewm over valid values
        pl.col("_macd")
        .ewm_mean(span=signal, adjust=False, min_samples=signal)
        .over(G)
        .alias("_sig")
    )
    return d.with_columns(
        (pl.col("_macd") / c).alias("macd_pct"),
        (pl.col("_sig") / c).alias("macd_signal_pct"),
        ((pl.col("_macd") - pl.col("_sig")) / c).alias("macd_hist_pct"),
    ).drop("_macd", "_sig")


def add_adx(df: pl.DataFrame, n: int = 14) -> pl.DataFrame:
    h, lo = pl.col("adj_high"), pl.col("adj_low")
    up = h - h.shift(1)
    down = lo.shift(1) - lo
    # ties (up == down) are decided with a relative tolerance so that float round-off from a
    # later price adjustment cannot flip a +DM/-DM decision (point-in-time stability)
    tol = TIE_TOLERANCE * pl.col("adj_close")
    plus_dm = pl.when(((up - down) > tol) & (up > 0)).then(up).otherwise(0.0)
    minus_dm = pl.when(((down - up) > tol) & (down > 0)).then(down).otherwise(0.0)
    row = pl.int_range(pl.len())
    d = df.with_columns(
        pl.when(row == 0).then(None).otherwise(plus_dm).over(G).alias("_pdm"),
        pl.when(row == 0).then(None).otherwise(minus_dm).over(G).alias("_mdm"),
        pl.when(row == 0).then(None).otherwise(true_range()).over(G).alias("_tr1"),
    )
    d = d.with_columns(
        wilder(pl.col("_pdm"), n).over(G).alias("_spdm"),
        wilder(pl.col("_mdm"), n).over(G).alias("_smdm"),
        wilder(pl.col("_tr1"), n).over(G).alias("_str"),
    )
    d = d.with_columns(
        (100.0 * _safe_div(pl.col("_spdm"), pl.col("_str"))).alias("plus_di"),
        (100.0 * _safe_div(pl.col("_smdm"), pl.col("_str"))).alias("minus_di"),
    )
    d = d.with_columns(
        (
            100.0
            * _safe_div(
                (pl.col("plus_di") - pl.col("minus_di")).abs(),
                pl.col("plus_di") + pl.col("minus_di"),
            )
        ).alias("_dx")
    )
    d = d.with_columns(wilder(pl.col("_dx"), n).over(G).alias("adx_14"))
    return d.drop("_pdm", "_mdm", "_tr1", "_spdm", "_smdm", "_str", "_dx")


def add_ichimoku(
    df: pl.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52
) -> pl.DataFrame:
    """Ichimoku distances. The cloud at ``t`` is the span computed at ``t - kijun`` (the
    standard 26-bar forward plot seen from the future side), and the chikou comparison uses
    ``close_t`` vs ``close_{t-26}``, so nothing looks ahead."""
    h, lo, c = pl.col("adj_high"), pl.col("adj_low"), pl.col("adj_close")

    def mid(n: int) -> pl.Expr:
        return (h.rolling_max(n) + lo.rolling_min(n)) / 2.0

    d = df.with_columns(
        mid(tenkan).over(G).alias("_tenkan"),
        mid(kijun).over(G).alias("_kijun"),
        mid(senkou_b).over(G).alias("_sb_raw"),
    )
    d = d.with_columns(
        ((pl.col("_tenkan") + pl.col("_kijun")) / 2.0).shift(kijun).over(G).alias("_cloud_a"),
        pl.col("_sb_raw").shift(kijun).over(G).alias("_cloud_b"),
    )
    top = pl.max_horizontal("_cloud_a", "_cloud_b")
    bottom = pl.min_horizontal("_cloud_a", "_cloud_b")
    valid = pl.col("_cloud_a").is_not_null() & pl.col("_cloud_b").is_not_null()
    d = d.with_columns(
        (c / pl.col("_tenkan") - 1.0).alias("ichi_tenkan_dist"),
        (c / pl.col("_kijun") - 1.0).alias("ichi_kijun_dist"),
        ((pl.col("_tenkan") - pl.col("_kijun")) / c).alias("ichi_tk_diff"),
        pl.when(valid).then(c / top - 1.0).otherwise(None).alias("ichi_cloud_top_dist"),
        pl.when(valid).then(c / bottom - 1.0).otherwise(None).alias("ichi_cloud_bottom_dist"),
        (c / c.shift(kijun).over(G) - 1.0).alias("ichi_chikou_cmp"),
    )
    return d.drop("_tenkan", "_kijun", "_sb_raw", "_cloud_a", "_cloud_b")


# --------------------------------------------------------------------------- #
# Momentum
# --------------------------------------------------------------------------- #


def add_rsi(df: pl.DataFrame, n: int = 14) -> pl.DataFrame:
    delta = pl.col("adj_close").diff()
    d = df.with_columns(
        delta.clip(lower_bound=0.0).over(G).alias("_gain"),
        (-delta).clip(lower_bound=0.0).over(G).alias("_loss"),
    )
    d = d.with_columns(
        wilder(pl.col("_gain"), n).over(G).alias("_ag"),
        wilder(pl.col("_loss"), n).over(G).alias("_al"),
    )
    total = pl.col("_ag") + pl.col("_al")
    d = d.with_columns(
        pl.when(total > 0)
        .then(100.0 * pl.col("_ag") / total)
        .when(total == 0)
        .then(50.0)  # flat window: neutral
        .otherwise(None)
        .alias(f"rsi_{n}")
    )
    return d.drop("_gain", "_loss", "_ag", "_al")


def add_stochastic(df: pl.DataFrame, n: int = 14, smooth: int = 3) -> pl.DataFrame:
    h, lo, c = pl.col("adj_high"), pl.col("adj_low"), pl.col("adj_close")
    hh = h.rolling_max(n)
    ll = lo.rolling_min(n)
    d = df.with_columns(
        _safe_div(c - ll, hh - ll).mul(100.0).over(G).alias("stoch_k"),
        _safe_div(hh - c, hh - ll).mul(-100.0).over(G).alias(f"willr_{n}"),
    )
    return d.with_columns(pl.col("stoch_k").rolling_mean(smooth).over(G).alias("stoch_d"))


# --------------------------------------------------------------------------- #
# Volatility
# --------------------------------------------------------------------------- #


def add_volatility(
    df: pl.DataFrame, atr_n: int = 14, bb_n: int = 20, bb_k: float = 2.0
) -> pl.DataFrame:
    c = pl.col("adj_close")
    d = df.with_columns(
        wilder(true_range(), atr_n).over(G).alias(f"atr_{atr_n}"),
        c.rolling_mean(bb_n).over(G).alias("_bb_mid"),
        c.rolling_std(bb_n, ddof=0).over(G).alias("_bb_sd"),
        (c / c.shift(1)).log().rolling_std(20).over(G).alias("rv_20"),
    )
    band = bb_k * pl.col("_bb_sd")
    d = d.with_columns(
        (pl.col(f"atr_{atr_n}") / c).alias(f"atr_{atr_n}_pct"),
        _safe_div(c - (pl.col("_bb_mid") - band), 2.0 * band).alias("bb_pct_b"),
        _safe_div(2.0 * band, pl.col("_bb_mid")).alias("bb_bandwidth"),
    )
    return d.drop("_bb_mid", "_bb_sd")


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #


def add_vwap_gap(df: pl.DataFrame) -> pl.DataFrame:
    """``vwap_gap = close / VWAP - 1`` with the daily VWAP ``value / volume`` (docs/04).

    Uses raw same-day exchange figures, so no price adjustment is involved. Null on days
    without volume."""
    return df.with_columns(
        pl.when(pl.col("volume") > 0)
        .then(pl.col("close") / (pl.col("value") / pl.col("volume")) - 1.0)
        .otherwise(None)
        .alias("vwap_gap")
    )


def add_volume_indicators(df: pl.DataFrame, mfi_n: int = 14, obv_window: int = 20) -> pl.DataFrame:
    c, v = pl.col("adj_close"), pl.col("adj_volume")
    tp = (pl.col("adj_high") + pl.col("adj_low") + c) / 3.0
    d = df.with_columns(
        (pl.col("adj_close").diff().sign().fill_null(0.0) * v).cum_sum().over(G).alias("_obv"),
        tp.alias("_tp"),
    )
    d = d.with_columns(
        (pl.col("_tp") * v).alias("_rmf"), pl.col("_tp").diff().over(G).alias("_dtp")
    )
    d = d.with_columns(
        pl.when(pl.col("_dtp") > TIE_TOLERANCE * pl.col("_tp"))
        .then(pl.col("_rmf"))
        .otherwise(0.0)
        .alias("_pos"),
        pl.when(pl.col("_dtp") < -TIE_TOLERANCE * pl.col("_tp"))
        .then(pl.col("_rmf"))
        .otherwise(0.0)
        .alias("_neg"),
    )
    pos_sum = pl.col("_pos").rolling_sum(mfi_n)
    neg_sum = pl.col("_neg").rolling_sum(mfi_n)
    d = d.with_columns(
        pos_sum.over(G).alias("_pos_s"),
        neg_sum.over(G).alias("_neg_s"),
        ((pl.col("_obv") - pl.col("_obv").shift(obv_window)) / v.rolling_sum(obv_window))
        .over(G)
        .alias(f"obv_chg_{obv_window}"),
    )
    total = pl.col("_pos_s") + pl.col("_neg_s")
    # mfi_n money-flow *changes* need mfi_n + 1 bars; the first bar has no change
    enough = pl.int_range(pl.len()).over(G) >= mfi_n
    d = d.with_columns(
        pl.when(~enough | pl.col("_pos_s").is_null() | pl.col("_neg_s").is_null())
        .then(None)
        .when(total > 0)
        .then(100.0 * pl.col("_pos_s") / total)
        .otherwise(50.0)
        .alias(f"mfi_{mfi_n}")
    )
    return d.drop("_obv", "_tp", "_rmf", "_dtp", "_pos", "_neg", "_pos_s", "_neg_s")


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def add_structure(df: pl.DataFrame, year_window: int = YEAR_WINDOW) -> pl.DataFrame:
    """Distance from highs/lows, volume-confirmed breakout and previous-day pivot levels.

    Requires ``rel_volume`` (see :mod:`tmon.features.orderbook`) for the breakout flag.
    """
    h, lo, c = pl.col("adj_high"), pl.col("adj_low"), pl.col("adj_close")
    d = df.with_columns(
        (c / h.rolling_max(20) - 1.0).over(G).alias("dist_high_20"),
        (c / lo.rolling_min(20) - 1.0).over(G).alias("dist_low_20"),
        (c / h.rolling_max(year_window, min_samples=year_window // 2) - 1.0)
        .over(G)
        .alias("dist_high_52w"),
        (c / lo.rolling_min(year_window, min_samples=year_window // 2) - 1.0)
        .over(G)
        .alias("dist_low_52w"),
        h.rolling_max(20).shift(1).over(G).alias("_prior_high_20"),
        ((h + lo + c) / 3.0).shift(1).over(G).alias("_pivot"),
        h.shift(1).over(G).alias("_ph"),
        lo.shift(1).over(G).alias("_pl"),
    )
    r1 = 2.0 * pl.col("_pivot") - pl.col("_pl")
    s1 = 2.0 * pl.col("_pivot") - pl.col("_ph")
    breakout = (c > pl.col("_prior_high_20")) & (pl.col("rel_volume") > 1.5)
    d = d.with_columns(
        pl.when(pl.col("_prior_high_20").is_null() | pl.col("rel_volume").is_null())
        .then(None)
        .otherwise(breakout.cast(pl.Int8))
        .alias("breakout_20_vol"),
        (c / pl.col("_pivot") - 1.0).alias("pivot_dist"),
        (c / r1 - 1.0).alias("pivot_r1_dist"),
        (c / s1 - 1.0).alias("pivot_s1_dist"),
    )
    return d.drop("_prior_high_20", "_pivot", "_ph", "_pl")


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def add_trend_momentum_volatility_volume(df: pl.DataFrame) -> pl.DataFrame:
    """All indicators that need only adjusted OHLCV (no board data)."""
    d = df.sort([G, "date"])
    for fn in (
        add_returns,
        add_moving_averages,
        add_macd,
        add_adx,
        add_ichimoku,
        add_rsi,
        add_stochastic,
        add_volatility,
        add_volume_indicators,
    ):
        d = fn(d)
    return d
