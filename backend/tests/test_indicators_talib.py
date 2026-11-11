"""Cross-check the vectorised Polars indicators against TA-Lib, the industry reference.

TA-Lib is a test-only dependency: production keeps the Polars implementation (no C library in
the runtime image, point-in-time safe, grouped per instrument). Seeding conventions differ
during warm-up (e.g. TA-Lib seeds EMA with an SMA, we seed with the first price), so values are
compared only after a long warm-up, when both recursions have converged.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from tmon.features import indicators as ind

talib = pytest.importorskip("talib")

N_BARS = 3000  # EMA-200 seed influence decays as (1 - 2/201)^n; 3000 bars puts it below 1e-9
TAIL = 300  # compare only the converged tail
RTOL = 1e-6


@pytest.fixture(scope="module")
def bars() -> pl.DataFrame:
    rng = np.random.default_rng(7)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, N_BARS)))
    spread = np.abs(rng.normal(0.0, 0.01, N_BARS)) * close
    high = close + spread * rng.uniform(0.2, 1.0, N_BARS)
    low = close - spread * rng.uniform(0.2, 1.0, N_BARS)
    open_ = low + (high - low) * rng.uniform(0.0, 1.0, N_BARS)
    volume = rng.integers(10_000, 1_000_000, N_BARS).astype(float)
    start = date(2020, 1, 1)
    return pl.DataFrame(
        {
            "instrument_id": [1] * N_BARS,
            "date": [start + timedelta(days=i) for i in range(N_BARS)],
            "adj_open": open_,
            "adj_high": high,
            "adj_low": low,
            "adj_close": close,
            "adj_volume": volume,
        }
    )


@pytest.fixture(scope="module")
def ours(bars: pl.DataFrame) -> pl.DataFrame:
    return ind.add_trend_momentum_volatility_volume(bars)


def _arr(df: pl.DataFrame, col: str) -> np.ndarray:
    return df[col].to_numpy().astype(float)


def _close(a: np.ndarray, b: np.ndarray) -> None:
    np.testing.assert_allclose(a[-TAIL:], b[-TAIL:], rtol=RTOL, atol=1e-9)


@pytest.mark.parametrize("n", ind.SMA_WINDOWS)
def test_sma_and_ema(bars: pl.DataFrame, ours: pl.DataFrame, n: int) -> None:
    c = _arr(bars, "adj_close")
    _close(c / (1 + _arr(ours, f"sma_{n}_dist")), talib.SMA(c, n))
    _close(c / (1 + _arr(ours, f"ema_{n}_dist")), talib.EMA(c, n))


def test_macd(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    c = _arr(bars, "adj_close")
    macd, signal, hist = talib.MACD(c, 12, 26, 9)
    _close(_arr(ours, "macd_pct") * c, macd)
    _close(_arr(ours, "macd_signal_pct") * c, signal)
    _close(_arr(ours, "macd_hist_pct") * c, hist)


def test_rsi(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    _close(_arr(ours, "rsi_14"), talib.RSI(_arr(bars, "adj_close"), 14))


def test_atr(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    h, lo, c = (_arr(bars, k) for k in ("adj_high", "adj_low", "adj_close"))
    _close(_arr(ours, "atr_14_pct") * c, talib.ATR(h, lo, c, 14))


def test_adx_and_di(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    h, lo, c = (_arr(bars, k) for k in ("adj_high", "adj_low", "adj_close"))
    _close(_arr(ours, "adx_14"), talib.ADX(h, lo, c, 14))
    _close(_arr(ours, "plus_di"), talib.PLUS_DI(h, lo, c, 14))
    _close(_arr(ours, "minus_di"), talib.MINUS_DI(h, lo, c, 14))


def test_stochastic_and_williams(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    h, lo, c = (_arr(bars, k) for k in ("adj_high", "adj_low", "adj_close"))
    fastk, fastd = talib.STOCHF(h, lo, c, fastk_period=14, fastd_period=3, fastd_matype=0)
    _close(_arr(ours, "stoch_k"), fastk)
    _close(_arr(ours, "stoch_d"), fastd)
    _close(_arr(ours, "willr_14"), talib.WILLR(h, lo, c, 14))


def test_bollinger(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    c = _arr(bars, "adj_close")
    upper, mid, lower = talib.BBANDS(c, 20, 2.0, 2.0, matype=0)
    _close(_arr(ours, "bb_pct_b"), (c - lower) / (upper - lower))
    _close(_arr(ours, "bb_bandwidth"), (upper - lower) / mid)


def test_mfi(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    h, lo, c, v = (_arr(bars, k) for k in ("adj_high", "adj_low", "adj_close", "adj_volume"))
    _close(_arr(ours, "mfi_14"), talib.MFI(h, lo, c, v, 14))


def test_obv_change(bars: pl.DataFrame, ours: pl.DataFrame) -> None:
    c, v = _arr(bars, "adj_close"), _arr(bars, "adj_volume")
    obv = talib.OBV(c, v)  # TA-Lib starts at v[0], we start at 0: the offset cancels in a diff
    window = 20
    expected = (obv - np.roll(obv, window)) / talib.SUM(v, window)
    _close(_arr(ours, f"obv_chg_{window}"), expected)


@pytest.mark.parametrize("n", ind.ROC_WINDOWS)
def test_roc(bars: pl.DataFrame, ours: pl.DataFrame, n: int) -> None:
    _close(_arr(ours, f"roc_{n}"), talib.ROC(_arr(bars, "adj_close"), n))
