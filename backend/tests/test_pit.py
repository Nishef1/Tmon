"""Point-in-time (anti look-ahead) tests for the feature builder.

Two independent checks:

* **Truncation**: features for dates ``<= T`` computed from data cut at ``T`` must equal the
  features computed from the full history. This also covers future price adjustments: a
  capital event after ``T`` rescales historical adjusted prices, and no feature may change.
* **Perturbation**: overwriting every raw value after ``T`` with garbage must not change any
  feature at dates ``<= T``.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from tests.test_features import RULES, synthetic_market
from tmon.features.builder import build_features

CUTOFF_DAY = 280  # before the capital event of instrument 2 (day 300)
START = date(2023, 1, 1)
# raw rial ATR is the only column expressed in adjusted price units; everything else is a
# ratio, an oscillator or a raw-exchange quantity.
SCALE_DEPENDENT = {"atr_14"}


def _compare(a: pl.DataFrame, b: pl.DataFrame) -> None:
    assert a.height == b.height
    a = a.sort("instrument_id", "date")
    b = b.sort("instrument_id", "date")
    for name in a.columns:
        if name in SCALE_DEPENDENT:
            continue
        x, y = a[name], b[name]
        if x.dtype.is_float():
            xs, ys = x.to_numpy(), y.to_numpy()
            both_nan = np.isnan(xs) & np.isnan(ys)
            ok = both_nan | np.isclose(xs, ys, rtol=1e-9, atol=1e-9, equal_nan=True)
            assert ok.all(), f"column {name} differs (first bad row {int(np.argmin(ok))})"
        else:
            assert x.to_list() == y.to_list(), f"column {name} differs"


@pytest.fixture(scope="module")
def market() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    prices, clients = synthetic_market(n_days=340, n_inst=5)
    sectors = pl.DataFrame({"instrument_id": [1, 2, 3, 4, 5], "sector_code": list("aabbb")})
    return prices, clients, sectors


def test_features_up_to_t_do_not_depend_on_later_data(market):
    prices, clients, sectors = market
    cutoff = START + timedelta(days=CUTOFF_DAY)
    full = build_features(prices, clients, RULES, sectors=sectors).filter(pl.col("date") <= cutoff)
    cut = build_features(
        prices.filter(pl.col("date") <= cutoff),
        clients.filter(pl.col("date") <= cutoff),
        RULES,
        sectors=sectors,
    )
    _compare(full, cut)


def test_garbage_after_t_does_not_change_features_up_to_t(market):
    prices, clients, sectors = market
    cutoff = START + timedelta(days=CUTOFF_DAY)
    rng = np.random.default_rng(99)

    def scramble(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
        future = pl.col("date") > cutoff
        return df.with_columns(
            [
                pl.when(future)
                .then(pl.Series(rng.uniform(1, 1e6, df.height)))
                .otherwise(pl.col(c))
                .alias(c)
                for c in cols
            ]
        )

    price_cols = ["open", "high", "low", "close", "last", "prev_close", "volume", "value"]
    client_cols = [c for c in clients.columns if c not in ("instrument_id", "date")]
    base = build_features(prices, clients, RULES, sectors=sectors).filter(pl.col("date") <= cutoff)
    noisy = build_features(
        scramble(prices, price_cols), scramble(clients, client_cols), RULES, sectors=sectors
    ).filter(pl.col("date") <= cutoff)
    _compare(base, noisy)


def test_detector_catches_an_intentional_leak(market):
    """Guard against a vacuous test: a feature that peeks one day ahead must be flagged."""
    prices, clients, sectors = market
    cutoff = START + timedelta(days=CUTOFF_DAY)
    full = build_features(prices, clients, RULES, sectors=sectors).with_columns(
        leak=pl.col("ret_1").shift(-1).over("instrument_id")
    )
    cut = build_features(
        prices.filter(pl.col("date") <= cutoff),
        clients.filter(pl.col("date") <= cutoff),
        RULES,
        sectors=sectors,
    ).with_columns(leak=pl.col("ret_1").shift(-1).over("instrument_id"))
    with pytest.raises(AssertionError):
        _compare(full.filter(pl.col("date") <= cutoff), cut)
