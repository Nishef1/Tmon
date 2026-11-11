"""Indicators vs. independent loop-based references and a published worked example."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from tests import reference as ref
from tmon.features import indicators as ind

# StockCharts "RSI" worked example (14 periods): RSI at bar 15 = 70.53, then 66.32, 66.55,
# 69.41, 66.36, 57.97.
SC_CLOSE = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826,
    45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439,
]  # fmt: skip
SC_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]


def make_frame(seed: int, n: int = 320, ids: tuple[int, ...] = (1, 2)) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    dates = pl.date_range(
        pl.date(2024, 1, 1), pl.date(2024, 1, 1) + pl.duration(days=n - 1), eager=True
    )
    for iid in ids:
        close = 1000 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
        parts.append(
            pl.DataFrame(
                {
                    "instrument_id": iid,
                    "date": dates,
                    "adj_open": close,
                    "adj_high": close * (1 + rng.uniform(0, 0.03, n)),
                    "adj_low": close * (1 - rng.uniform(0, 0.03, n)),
                    "adj_close": close,
                    "adj_volume": rng.integers(1_000, 100_000, n).astype(float),
                }
            )
        )
    return pl.concat(parts)


def col(df: pl.DataFrame, name: str, iid: int) -> list[float | None]:
    return df.filter(pl.col("instrument_id") == iid)[name].to_list()


def vals(df: pl.DataFrame, iid: int, name: str) -> list[float]:
    return col(df, name, iid)  # type: ignore[return-value]


def assert_close(got: list[float | None], want: list[float | None], tol: float = 1e-8) -> None:
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        if w is None:
            assert g is None or (isinstance(g, float) and np.isnan(g)), (
                f"row {i}: want null, got {g}"
            )
        else:
            assert g is not None, f"row {i}: want {w}, got null"
            assert g == pytest.approx(w, rel=tol, abs=tol), f"row {i}"


def test_rsi_matches_stockcharts_worked_example():
    df = pl.DataFrame(
        {
            "instrument_id": 1,
            "date": pl.date_range(pl.date(2024, 1, 1), pl.date(2024, 1, 20), eager=True),
            "adj_close": SC_CLOSE,
        }
    )
    out = ind.add_rsi(df)["rsi_14"].to_list()
    assert out[:14] == [None] * 14
    for got, want in zip(out[14:], SC_RSI, strict=True):
        assert got == pytest.approx(want, abs=0.01)


def test_rsi_extremes():
    dates = pl.date_range(pl.date(2024, 1, 1), pl.date(2024, 2, 5), eager=True)
    up = pl.DataFrame(
        {"instrument_id": 1, "date": dates, "adj_close": [float(i) for i in range(1, 37)]}
    )
    assert ind.add_rsi(up)["rsi_14"][-1] == 100.0
    assert ind.add_rsi(up.with_columns(adj_close=pl.lit(5.0)))["rsi_14"][-1] == 50.0


@pytest.fixture(scope="module")
def data() -> pl.DataFrame:
    return make_frame(7)


@pytest.fixture(scope="module")
def full(data: pl.DataFrame) -> pl.DataFrame:
    return ind.add_trend_momentum_volatility_volume(data)


@pytest.mark.parametrize("iid", [1, 2])
def test_sma_ema_distance(data, full, iid):
    c = vals(data, iid, "adj_close")
    for n in ind.SMA_WINDOWS:
        s, e = ref.sma(c, n), ref.ema(c, n)
        assert_close(
            col(full, f"sma_{n}_dist", iid),
            [None if v is None else c[i] / v - 1 for i, v in enumerate(s)],
        )
        assert_close(
            col(full, f"ema_{n}_dist", iid),
            [None if v is None else c[i] / v - 1 for i, v in enumerate(e)],
        )


@pytest.mark.parametrize("iid", [1, 2])
def test_macd(data, full, iid):
    c = vals(data, iid, "adj_close")
    fast, slow = ref.ema(c, 12), ref.ema(c, 26)
    macd = [None if a is None or b is None else a - b for a, b in zip(fast, slow, strict=True)]
    valid = [m for m in macd if m is not None]
    sig: list[float | None] = [None] * (len(macd) - len(valid)) + ref.ema(valid, 9)
    assert_close(
        col(full, "macd_pct", iid), [None if m is None else m / c[i] for i, m in enumerate(macd)]
    )
    assert_close(
        col(full, "macd_hist_pct", iid),
        [
            None if m is None or s is None else (m - s) / c[i]
            for i, (m, s) in enumerate(zip(macd, sig, strict=True))
        ],
    )


@pytest.mark.parametrize("iid", [1, 2])
def test_rsi_vs_reference(data, full, iid):
    assert_close(col(full, "rsi_14", iid), ref.rsi(vals(data, iid, "adj_close")))


@pytest.mark.parametrize("iid", [1, 2])
def test_atr_and_bollinger(data, full, iid):
    h, lo, c = (vals(data, iid, k) for k in ("adj_high", "adj_low", "adj_close"))
    a = ref.atr(h, lo, c)
    assert_close(col(full, "atr_14", iid), a)
    assert_close(
        col(full, "atr_14_pct", iid), [None if v is None else v / c[i] for i, v in enumerate(a)]
    )
    pct_b, bw = ref.bollinger(c)
    assert_close(col(full, "bb_pct_b", iid), pct_b)
    assert_close(col(full, "bb_bandwidth", iid), bw)


@pytest.mark.parametrize("iid", [1, 2])
def test_adx(data, full, iid):
    h, lo, c = (vals(data, iid, k) for k in ("adj_high", "adj_low", "adj_close"))
    a, pdi, mdi = ref.adx(h, lo, c)
    assert_close(col(full, "adx_14", iid), a)
    assert_close(col(full, "plus_di", iid), pdi)
    assert_close(col(full, "minus_di", iid), mdi)


@pytest.mark.parametrize("iid", [1, 2])
def test_stochastic_williams(data, full, iid):
    h, lo, c = (vals(data, iid, k) for k in ("adj_high", "adj_low", "adj_close"))
    k, d, wr = ref.stochastic(h, lo, c)
    assert_close(col(full, "stoch_k", iid), k)
    assert_close(col(full, "stoch_d", iid), d)
    assert_close(col(full, "willr_14", iid), wr)


@pytest.mark.parametrize("iid", [1, 2])
def test_obv_and_mfi(data, full, iid):
    h, lo, c, v = (vals(data, iid, k) for k in ("adj_high", "adj_low", "adj_close", "adj_volume"))
    assert_close(col(full, "obv_chg_20", iid), ref.obv_change(c, v))
    assert_close(col(full, "mfi_14", iid), ref.mfi(h, lo, c, v))


@pytest.mark.parametrize("iid", [1, 2])
def test_ichimoku_cloud(data, full, iid):
    h, lo, c = (vals(data, iid, k) for k in ("adj_high", "adj_low", "adj_close"))
    assert_close(col(full, "ichi_cloud_top_dist", iid), ref.ichimoku_cloud_top_dist(h, lo, c))


@pytest.mark.parametrize("iid", [1, 2])
def test_returns_roc_realized_vol(data, full, iid):
    c = vals(data, iid, "adj_close")
    r5 = [None if i < 5 else c[i] / c[i - 5] - 1 for i in range(len(c))]
    assert_close(col(full, "ret_5", iid), r5)
    assert_close(col(full, "roc_5", iid), [None if v is None else v * 100 for v in r5])
    lr = [float(np.log(c[i] / c[i - 1])) for i in range(1, len(c))]
    want: list[float | None] = [None] * 20 + [
        float(np.std(lr[i - 19 : i + 1], ddof=1)) for i in range(19, len(lr))
    ]
    assert_close(col(full, "rv_20", iid), want)


def test_instruments_do_not_bleed(data, full):
    single = ind.add_trend_momentum_volatility_volume(data.filter(pl.col("instrument_id") == 2))
    both = full.filter(pl.col("instrument_id") == 2)
    for name in ("rsi_14", "adx_14", "macd_pct", "ichi_cloud_top_dist", "mfi_14", "sma_200_dist"):
        assert_close(both[name].to_list(), single[name].to_list())


def test_features_are_scale_free(data):
    """Multiplying prices by a constant (what a future adjustment does) changes no feature."""
    base = ind.add_trend_momentum_volatility_volume(data)
    scaled = ind.add_trend_momentum_volatility_volume(
        data.with_columns(
            *[
                (pl.col(c) * 0.37).alias(c)
                for c in ("adj_open", "adj_high", "adj_low", "adj_close")
            ],
            (pl.col("adj_volume") / 0.37).alias("adj_volume"),
        )
    )
    for name in base.columns:
        if name in ("instrument_id", "date") or name.startswith("adj_") or name == "atr_14":
            continue
        assert_close(scaled[name].to_list(), base[name].to_list(), tol=1e-9)
