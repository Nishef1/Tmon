"""Synthetic markets for pipeline checks and tests. **Never a source of market results.**

``edge = 0`` is a pure random walk: no honest strategy can earn more than it pays in costs, so
the backtester reporting a profit there would mean a leak or a costing bug (see
``tests/test_backtest.py``). ``edge > 0`` plants a genuine, learnable relation: a latent
"informed buying" variable that shows up in same-day real-investor flow and moves the *next*
day's return by ``edge`` per unit.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

LIMIT = 0.03
CLIENT_COLS = [
    f"{s}_{m}_{k}"
    for s in ("buy", "sell")
    for m in ("count", "volume", "value")
    for k in ("i", "n")
]


def trading_days(start: date, n: int) -> list[date]:
    """``n`` consecutive Saturday-to-Wednesday dates (Thursday and Friday are closed)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() not in (3, 4):
            out.append(d)
        d += timedelta(days=1)
    return out


def _flat(a: np.ndarray) -> np.ndarray:
    return a.reshape(-1)


def make_market(
    n_days: int = 600,
    n_inst: int = 30,
    *,
    seed: int = 7,
    edge: float = 0.0,
    start: date = date(2022, 3, 19),
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Return ``(prices, client_types, sectors)`` in the shapes the feature builder expects."""
    rng = np.random.default_rng(seed)
    dates = trading_days(start, n_days)
    z = rng.normal(size=(n_days, n_inst))  # informed-buying latent, observed through flow
    sigma = rng.uniform(0.010, 0.020, size=n_inst)
    shock = rng.normal(size=(n_days, n_inst)) * sigma
    r = shock.copy()
    r[1:] += edge * z[:-1]  # yesterday's informed buying moves today
    r = np.clip(r, -LIMIT, LIMIT)
    px = 10_000.0 * np.cumprod(1.0 + r, axis=0)
    close = np.round(px)
    prev = np.vstack([np.full((1, n_inst), 10_000.0), close[:-1]])
    gap = 0.2 * r
    open_ = np.round(prev * (1 + gap))
    wick = rng.uniform(0.0, 0.006, size=(2, n_days, n_inst))
    high = np.round(np.maximum(open_, close) * (1 + wick[0]))
    low = np.round(np.minimum(open_, close) * (1 - wick[1]))
    base_vol = 5_000_000.0
    vol = np.round(base_vol * np.exp(rng.normal(0, 0.4, size=(n_days, n_inst))))
    vwap = low + (high - low) * rng.uniform(0.2, 0.8, size=(n_days, n_inst))
    value = vol * vwap

    ids = np.arange(1, n_inst + 1)
    inst = np.tile(ids, n_days)
    dts = np.repeat(np.array(dates, dtype="datetime64[D]"), n_inst)
    prices = pl.DataFrame(
        {
            "instrument_id": inst,
            "date": dts,
            "open": _flat(open_), "high": _flat(high), "low": _flat(low), "close": _flat(close),
            "last": _flat(close), "prev_close": _flat(prev), "volume": _flat(vol),
            "value": _flat(value), "base_volume": np.full(n_days * n_inst, base_vol),
            "market_halt": np.zeros(n_days * n_inst, dtype=bool),
        }
    )  # fmt: skip

    fi = np.clip(0.5 + 0.15 * z, 0.05, 0.95)  # real investors' share of the buy side
    bi = vol * fi
    cols = {
        "buy_count_i": np.full_like(vol, 300.0), "sell_count_i": np.full_like(vol, 300.0),
        "buy_count_n": np.full_like(vol, 3.0), "sell_count_n": np.full_like(vol, 3.0),
        "buy_volume_i": bi, "buy_volume_n": vol - bi,
        "sell_volume_i": vol - bi, "sell_volume_n": bi,
        "buy_value_i": bi * close, "buy_value_n": (vol - bi) * close,
        "sell_value_i": (vol - bi) * close, "sell_value_n": bi * close,
    }  # fmt: skip
    clients = pl.DataFrame(
        {"instrument_id": inst, "date": dts, **{k: _flat(v) for k, v in cols.items()}}
    )
    sectors = pl.DataFrame({"instrument_id": ids, "sector_code": [f"s{i % 5}" for i in ids]})
    return prices.cast({"date": pl.Date}), clients.cast({"date": pl.Date}), sectors
