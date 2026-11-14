"""Return ranges of a portfolio and of each holding for a week, a month, 3, 6 and 12 months.

Method (filtered historical simulation, Barone-Adesi et al. 1999):

1. adjusted daily log returns of every holding on the union of their trading days (a day without
   trades is a zero return, so a halt and the jump after it stay in the history);
2. each return is divided by its EWMA volatility of the day before (RiskMetrics, lambda 0.94):
   the standardized shocks carry the shape of the moves without the volatility regime;
3. future paths draw whole rows of shocks (all holdings of one day together, so their
   correlation, including crashes that hit everything at once, is kept) in random-length blocks
   with ``arch``'s stationary bootstrap (Politis & Romano 1994; block length from
   ``optimal_block_length``), and scale them with today's volatility decaying toward its long-run
   level;
4. the drift of each symbol is shrunk halfway to the average of the holdings, so one lucky year
   does not become a forecast.

The bands are then checked against history: a rolling-origin backtest forecasts from past days
with only the data known then and counts how often the real outcome fell inside the 80% and 90%
bands. When that coverage is off, the bands are widened or narrowed by the factor that would have
made them right (split-conformal calibration, Romano et al. 2019), and both numbers are reported.
"""

from __future__ import annotations

import datetime as dt
import math
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from arch.bootstrap import StationaryBootstrap, optimal_block_length
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.storage.models import PriceAdjustment, PriceDaily

HORIZONS: dict[str, int] = {"week": 5, "month": 20, "quarter": 60, "half": 120, "year": 240}
HORIZON_FA = {
    "week": "یک هفته",
    "month": "یک ماه",
    "quarter": "سه ماه",
    "half": "شش ماه",
    "year": "یک سال",
}
LAMBDA = 0.94
VOL_DECAY = 0.985  # per day: today's volatility halves its gap to the long-run level in ~46 days
MIN_DAYS = 120
HISTORY_DAYS = 5 * 245
N_PATHS = 4000
BACKTEST_PATHS = 800
BACKTEST_STEP = 20
BACKTEST_MIN_FIT = 250
ROUND_TRIP = 0.017512
QS = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


@dataclass(frozen=True)
class Position:
    instrument_id: int
    symbol: str
    shares: float
    price: float  # latest close, rial
    avg_price: float


def closes_matrix(
    session: Session, ids: list[int], days: int = HISTORY_DAYS
) -> tuple[list[dt.date], np.ndarray]:
    """Adjusted closes (dates x ids), forward-filled; NaN before a symbol's first trade."""
    from tmon.api.routers.picks import _closes

    series = {i: dict(_closes(session, i)[-days:]) for i in ids}
    dates = sorted({d for s in series.values() for d in s})[-days:]
    m = np.full((len(dates), len(ids)), np.nan)
    for j, i in enumerate(ids):
        last = np.nan
        s = series[i]
        for t, d in enumerate(dates):
            if d in s:
                last = s[d]
            m[t, j] = last
    return dates, m


def _ewma_vol(r: np.ndarray) -> np.ndarray:
    """sigma[t] is the volatility known at the end of day t (uses returns up to t)."""
    var = np.empty_like(r)
    seed = np.nanvar(r[: min(40, len(r))], axis=0)
    seed = np.where(np.isfinite(seed) & (seed > 0), seed, 1e-4)
    v = seed
    for t in range(len(r)):
        x = np.nan_to_num(r[t], nan=0.0)
        v = LAMBDA * v + (1 - LAMBDA) * x * x
        var[t] = v
    return np.asarray(np.sqrt(np.maximum(var, 1e-10)))


@dataclass
class Model:
    shocks: np.ndarray  # T x N standardized
    sigma_now: np.ndarray  # N
    sigma_long: np.ndarray  # N
    block: float


def fit(log_returns: np.ndarray, seed: int = 11) -> Model:
    missing = np.isnan(log_returns)
    r = np.nan_to_num(log_returns, nan=0.0)
    sig = _ewma_vol(r)
    prev = np.vstack([sig[:1], sig[:-1]])
    z = r / prev
    z = np.clip(z, -8, 8)
    if missing.any():  # days before a listing: shocks of the symbol's own history
        rng = np.random.default_rng(seed)
        for j in np.flatnonzero(missing.any(axis=0)):
            own = z[~missing[:, j], j]
            if own.size:
                z[missing[:, j], j] = rng.choice(own, size=int(missing[:, j].sum()))
    mean = z.mean(axis=0)
    z = z - mean + (0.5 * mean + 0.5 * mean.mean())  # drift shrunk halfway to the group's
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            bl = optimal_block_length(z[:, z.std(axis=0) > 0])["stationary"].to_numpy()
        block = float(np.clip(np.nanmedian(bl), 3, 40))
    except Exception:
        block = 10.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        long = np.nan_to_num(np.nanstd(log_returns, axis=0), nan=0.02)
    return Model(z, sig[-1], long + 1e-6, block)


def simulate(model: Model, horizon: int, n_paths: int, seed: int = 7) -> np.ndarray:
    """Cumulative log returns, paths x horizon x N."""
    rng = np.random.default_rng(seed)
    t_len = model.shocks.shape[0]
    # the expected block length may be fractional; the stub says int
    bs = StationaryBootstrap(model.block, np.arange(t_len), seed=rng)  # type: ignore[arg-type]
    idx = np.empty((n_paths, horizon), dtype=np.int64)
    k = 0
    while k < n_paths:
        ind = bs.update_indices()
        ind = np.asarray(ind[0] if isinstance(ind, tuple) else ind).ravel()
        for start in range(0, len(ind) - horizon + 1, horizon):
            if k >= n_paths:
                break
            idx[k] = ind[start : start + horizon]
            k += 1
    steps = np.arange(1, horizon + 1)[:, None]
    var = model.sigma_long**2 + (model.sigma_now**2 - model.sigma_long**2) * VOL_DECAY**steps
    sig = np.sqrt(np.maximum(var, 1e-10))  # horizon x N
    daily = model.shocks[idx] * sig[None, :, :]
    return np.cumsum(daily, axis=1)


def _band(x: np.ndarray) -> dict[str, float]:
    q = np.quantile(x, QS)
    out = {f"q{round(p * 100):02d}": float(v) for p, v in zip(QS, q, strict=True)}
    out["mean"] = float(x.mean())
    out["p_gain"] = float((x > 0).mean())
    out["p_gain_net"] = float((x > ROUND_TRIP).mean())
    return out


def _portfolio_returns(cum: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Simple return of the whole portfolio per path (weights at the start)."""
    return np.asarray((np.exp(cum) * w[None, :]).sum(axis=-1) - 1.0)


def backtest(
    log_returns: np.ndarray, w: np.ndarray, horizons: dict[str, int]
) -> dict[str, dict[str, Any]]:
    """Coverage of the 80% / 90% bands when forecasting from past days, and the factor that
    would have made each band right."""
    t_len = log_returns.shape[0]
    hmax = max(horizons.values())
    scores: dict[str, list[tuple[float, float, bool, bool]]] = {k: [] for k in horizons}
    for origin in range(BACKTEST_MIN_FIT, t_len - min(horizons.values()), BACKTEST_STEP):
        model = fit(log_returns[:origin])
        h_here = min(hmax, t_len - origin)
        cum = simulate(model, h_here, BACKTEST_PATHS, seed=origin)
        for key, h in horizons.items():
            if h > h_here:
                continue
            sim = _portfolio_returns(cum[:, h - 1, :], w)
            real = float(
                (np.exp(np.nan_to_num(log_returns[origin : origin + h]).sum(axis=0)) * w).sum() - 1
            )
            q05, q10, q50, q90, q95 = np.quantile(sim, (0.05, 0.10, 0.50, 0.90, 0.95))
            up = real >= q50
            s80 = (real - q50) / max(q90 - q50, 1e-9) if up else (q50 - real) / max(q50 - q10, 1e-9)
            s90 = (real - q50) / max(q95 - q50, 1e-9) if up else (q50 - real) / max(q50 - q05, 1e-9)
            scores[key].append((s80, s90, bool(q10 <= real <= q90), bool(q05 <= real <= q95)))
    out: dict[str, dict[str, Any]] = {}
    for key, rows in scores.items():
        n = len(rows)
        if n == 0:
            out[key] = {"n": 0}
            continue
        arr = np.array([(a, b) for a, b, _, _ in rows])
        # overlapping windows: the effective sample is smaller than n
        n_eff = max(1, int(n * BACKTEST_STEP / max(horizons[key], BACKTEST_STEP)))
        k80 = float(np.quantile(arr[:, 0], 0.80)) if n >= 12 else 1.0
        k90 = float(np.quantile(arr[:, 1], 0.90)) if n >= 12 else 1.0
        out[key] = {
            "n": n,
            "n_effective": n_eff,
            "coverage80": float(np.mean([r[2] for r in rows])),
            "coverage90": float(np.mean([r[3] for r in rows])),
            "scale80": float(np.clip(k80, 0.6, 3.0)),
            "scale90": float(np.clip(k90, 0.6, 3.0)),
            "reliable": n_eff >= 10,
        }
    return out


def _calibrated(b: dict[str, float], cal: dict[str, Any]) -> dict[str, float]:
    if not cal.get("n") or cal["n"] < 12:
        return {}
    m = b["q50"]
    k80, k90 = cal["scale80"], cal["scale90"]
    return {
        "q05": m - k90 * (m - b["q05"]),
        "q10": m - k80 * (m - b["q10"]),
        "q90": m + k80 * (b["q90"] - m),
        "q95": m + k90 * (b["q95"] - m),
    }


def forecast(positions: list[Position], dates: list[dt.date], closes: np.ndarray) -> dict[str, Any]:
    """The full answer for the API (pure: data in, document out)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.diff(np.log(closes), axis=0)
    lr = np.where(np.isfinite(lr), lr, np.nan)
    have = np.sum(~np.isnan(lr), axis=0)
    usable = [j for j in range(len(positions)) if have[j] >= MIN_DAYS]
    skipped = [positions[j].symbol for j in range(len(positions)) if have[j] < MIN_DAYS]
    if not usable:
        return {
            "available": False,
            "reason": "سابقهٔ قیمتی کافی برای هیچ نمادی نیست",
            "skipped": skipped,
        }
    pos = [positions[j] for j in usable]
    lr = lr[:, usable]
    # start where at least half of the holdings trade; a younger listing's missing days get
    # shocks drawn from its own history in ``fit``
    covered = (~np.isnan(lr)).sum(axis=1) >= max(1, math.ceil(lr.shape[1] / 2))
    first = int(np.argmax(covered))
    lr = lr[first:]
    values = np.array([p.shares * p.price for p in pos])
    w = values / values.sum()
    model = fit(lr)
    hmax = max(HORIZONS.values())
    cum = simulate(model, hmax, N_PATHS)
    cal = backtest(lr, w, HORIZONS)
    total = float(values.sum())
    horizons: list[dict[str, Any]] = []
    for key, h in HORIZONS.items():
        port = _band(_portfolio_returns(cum[:, h - 1, :], w))
        c = cal.get(key, {"n": 0})
        horizons.append(
            {
                "key": key,
                "label": HORIZON_FA[key],
                "days": h,
                "portfolio": port,
                "calibrated": _calibrated(port, c),
                "value": {k: total * (1 + v) for k, v in port.items() if k.startswith("q")},
                "backtest": c,
                "symbols": [
                    {
                        "instrument_id": p.instrument_id,
                        "symbol": p.symbol,
                        **_band(np.expm1(cum[:, h - 1, j])),
                    }
                    for j, p in enumerate(pos)
                ],
            }
        )
    vol_now = float(np.sqrt(w @ (model.sigma_now**2)) * math.sqrt(245))
    return {
        "available": True,
        "as_of": dates[-1].isoformat() if dates else None,
        "history_days": int(lr.shape[0]),
        "first_day": dates[first + 1].isoformat() if len(dates) > first + 1 else None,
        "paths": N_PATHS,
        "block_length": model.block,
        "value": total,
        "weights": [
            {"instrument_id": p.instrument_id, "symbol": p.symbol, "weight": float(x)}
            for p, x in zip(pos, w, strict=True)
        ],
        "annual_vol_now": vol_now,
        "skipped": skipped,
        "horizons": horizons,
        "method": (
            "شبیه‌سازی تاریخی فیلترشده: شوک‌های روزانهٔ استانداردشدهٔ همهٔ نمادها با هم و در "
            "بلوک‌هایی با طول تصادفی (bootstrap ایستا) بازنمونه‌گیری و با نوسان امروز که به سطح "
            "بلندمدت برمی‌گردد مقیاس می‌شوند. بازه‌ها با پیش‌بینی از روزهای گذشته آزموده و "
            "در صورت خطا اصلاح شده‌اند."
        ),
    }


# Results are kept per data fingerprint (holdings, last price day, adjustments), never by time:
# a new price or a changed holding gives a new key at once.
_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_CACHE_MAX = 64


def fingerprint(session: Session, positions: list[Position]) -> tuple[Any, ...]:
    ids = [p.instrument_id for p in positions]
    last = session.scalar(
        select(func.max(PriceDaily.date)).where(PriceDaily.instrument_id.in_(ids))
    )
    adj = session.scalar(
        select(func.count())
        .select_from(PriceAdjustment)
        .where(PriceAdjustment.instrument_id.in_(ids))
    )
    return (
        tuple(sorted((p.instrument_id, round(p.shares, 4), round(p.price, 4)) for p in positions)),
        last,
        adj,
    )


def portfolio_forecast(session: Session, positions: list[Position]) -> dict[str, Any]:
    if not positions:
        return {"available": False, "reason": "پرتفوی خالی است", "skipped": []}
    key = fingerprint(session, positions)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    dates, closes = closes_matrix(session, [p.instrument_id for p in positions])
    doc = forecast(positions, dates, closes)
    _CACHE[key] = doc
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return doc
