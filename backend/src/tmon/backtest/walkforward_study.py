"""Walk-forward study of the ranking signals, the way a language model is trained: every date is
predicted using only what was known before it (causal mask), and the coefficients are re-learned as
the data grows.

What it measures, for the horizons 1, 5, 20, 60 and 120 trading days (day, week, month, three
months, six months):

* A. each candidate signal's cross-sectional IC (rank correlation with the later return), t, and
  the same split in two halves of the history (discover on the first 60%, check on the last 40%);
* B. how the signals relate to one another (rank correlation of the signals, and of the days on
  which they work), and how the horizons relate to one another (correlation of the later returns
  across horizons, and of the composite's daily IC across horizons);
* C. out-of-sample comparison of weighting schemes, each refit only on the past with a purge gap of
  the horizon (a label that ends after the refit date is never used):
  ``equal`` (the production composite), ``ic_weight`` (weights from past mean IC), ``ridge4`` (ridge
  on the four production signals) and ``ridge_all`` (ridge on every candidate);
* D. drop-one ablation of the four production signals and add-one of each extra candidate (its sign
  is learned from the past only).

Nothing here changes the production model; it only reports. ``python -m
tmon.backtest.walkforward_study`` writes ``docs/data/walkforward-study.json``.
"""

# ruff: noqa: N806  (X, Y, G, ... are matrix names)
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.signal_decay import SIGNALS, adjusted_close, forward_returns
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS, build_features
from tmon.features.store import load_inputs

HORIZONS = (1, 5, 20, 60, 120)
BASE = list(SIGNALS)  # the four production signals, sign-adjusted so higher is better
EXTRA = [
    "ret_5",
    "ret_20",
    "roc_20",
    "sma_50_dist",
    "sma_200_dist",
    "rsi_14",
    "rel_volume",
    "ind_net_flow_z",
    "inst_to_ind",
    "rel_ret_sector",
    "atr_14_pct",
    "bb_pct_b",
    "mfi_14",
    "mom_6_1",
]
CANDS = BASE + EXTRA
MIN_N = 30
WARMUP = 500  # dates before the first out-of-sample prediction
REFIT = 21  # trading days between refits
RIDGE = 0.5


def _pct_rank(col: str) -> pl.Expr:
    r = pl.col(col).rank("average").over("date")
    return (r - 0.5) / pl.col(col).count().over("date") - 0.5


def build_panel(horizons: tuple[int, ...] = HORIZONS) -> pl.DataFrame:
    cfg = get_engine_config()
    with session_scope() as sess:
        prices, clients, sectors = load_inputs(sess)
        rules = RuleBook.from_session(sess)
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    fwd = forward_returns(adj, horizons).select(*KEYS, "mom_12_1", *[f"fwd_{h}" for h in horizons])
    c = pl.col("adj_close")
    mom6 = (
        adj.sort(KEYS)
        .with_columns((c.shift(21) / c.shift(126) - 1.0).over("instrument_id").alias("mom_6_1"))
        .select(*KEYS, "mom_6_1")
    )
    extra_in_feats = [e for e in EXTRA if e != "mom_6_1"]
    d = feats.filter(~pl.col("market_halt")).select(
        *KEYS, "eligible", "queue_state", "ind_buy_power", "rv_20", "dist_high_52w", *extra_in_feats
    )
    d = d.join(fwd, on=list(KEYS), how="left").join(mom6, on=list(KEYS), how="left")
    d = d.filter(
        pl.col("eligible") & ~pl.col("queue_state").is_in(cfg.universe.exclude_queue_states)
    )
    d = d.filter(pl.all_horizontal([pl.col(s).is_not_null() & pl.col(s).is_finite() for s in BASE]))
    ranks = []
    for s in CANDS:
        sign = SIGNALS.get(s, 1)
        r = _pct_rank(s)
        ranks.append((r if sign > 0 else -r).alias(f"r_{s}"))
    d = d.with_columns(*ranks)
    # extras may be missing for a name: neutral (0) instead of dropping the row
    d = d.with_columns([pl.col(f"r_{s}").fill_null(0.0).fill_nan(0.0) for s in EXTRA])
    ys = [_pct_rank(f"fwd_{h}").alias(f"y_{h}") for h in horizons]
    return d.with_columns(*ys).sort("date")


class Panel:
    """Per-date dense arrays: X (n x k signal ranks), Y (n x H return ranks, NaN missing), F (raw
    forward returns, NaN missing)."""

    def __init__(self, df: pl.DataFrame):
        self.dates: list[Any] = []
        self.X: list[np.ndarray] = []
        self.Y: list[np.ndarray] = []
        self.F: list[np.ndarray] = []
        xc = [f"r_{s}" for s in CANDS]
        yc = [f"y_{h}" for h in HORIZONS]
        fc = [f"fwd_{h}" for h in HORIZONS]
        for part in df.partition_by("date", maintain_order=True):
            if part.height < MIN_N:
                continue
            self.dates.append(part["date"][0])
            self.X.append(part.select(xc).to_numpy().astype(np.float64))
            self.Y.append(part.select(yc).to_numpy().astype(np.float64))
            self.F.append(part.select(fc).to_numpy().astype(np.float64))
        self.D = len(self.dates)
        self.k = len(CANDS)
        self.H = len(HORIZONS)
        self._prep()

    def _prep(self) -> None:
        D, H, k = self.D, self.H, self.k
        self.ic = np.full((D, H, k), np.nan)
        self.G = np.zeros((D, H, k, k))
        self.b = np.zeros((D, H, k))
        for t in range(D):
            X, Y = self.X[t], self.Y[t]
            for hi in range(H):
                m = np.isfinite(Y[:, hi])
                if m.sum() < MIN_N:
                    continue
                Xm, ym = X[m], Y[m, hi]
                self.G[t, hi] = Xm.T @ Xm
                self.b[t, hi] = Xm.T @ ym
                xs = Xm - Xm.mean(0)
                ys = ym - ym.mean()
                den = np.sqrt((xs**2).sum(0) * (ys**2).sum())
                with np.errstate(invalid="ignore", divide="ignore"):
                    self.ic[t, hi] = (xs.T @ ys) / den
        self.cG = np.cumsum(self.G, axis=0)
        self.cb = np.cumsum(self.b, axis=0)
        z = np.nan_to_num(self.ic)
        self.cIC = np.cumsum(z, axis=0)
        self.cN = np.cumsum(np.isfinite(self.ic[:, :, 0]).astype(float), axis=0)

    def score_stats(self, t: int, hi: int, w: np.ndarray) -> tuple[float, float]:
        """IC (Pearson of score and return rank) and top-decile excess of date ``t``."""
        Y = self.Y[t][:, hi]
        m = np.isfinite(Y)
        if m.sum() < MIN_N:
            return math.nan, math.nan
        s = self.X[t][m] @ w
        if not np.any(s != s[0]):
            return math.nan, math.nan
        y = Y[m]
        ic = float(np.corrcoef(s, y)[0, 1])
        f = self.F[t][m, hi]
        cut = np.quantile(s, 0.9)
        top = f[s > cut]
        ex = float(top.mean() - np.median(f)) if top.size else math.nan
        return ic, ex


WeightFn = Callable[[Panel, int, int], np.ndarray]


def _train_idx(t: int, h: int) -> int:
    """Last date index whose label (ending ``1 + h`` dates later) is known at ``t``."""
    return t - h - 1


def equal(cols: list[str]) -> WeightFn:
    w = np.zeros(len(CANDS))
    for c in cols:
        w[CANDS.index(c)] = 1.0 / len(cols)

    def fn(_p: Panel, _t: int, _hi: int) -> np.ndarray:
        return w

    return fn


def ic_weight(cols: list[str]) -> WeightFn:
    idx = [CANDS.index(c) for c in cols]

    def fn(p: Panel, t: int, hi: int) -> np.ndarray:
        h = HORIZONS[hi]
        j = _train_idx(t, h)
        w = np.zeros(len(CANDS))
        if j < 50:
            return w
        mean = p.cIC[j, hi, idx] / max(p.cN[j, hi], 1.0)
        mean = np.clip(mean, 0.0, None)
        if mean.sum() <= 0:
            w[idx] = 1.0 / len(idx)
        else:
            w[idx] = mean / mean.sum()
        return w

    return fn


def ridge(cols: list[str]) -> WeightFn:
    idx = np.array([CANDS.index(c) for c in cols])

    def fn(p: Panel, t: int, hi: int) -> np.ndarray:
        h = HORIZONS[hi]
        j = _train_idx(t, h)
        w = np.zeros(len(CANDS))
        if j < 50:
            return w
        G = p.cG[j, hi][np.ix_(idx, idx)]
        b = p.cb[j, hi][idx]
        lam = RIDGE * float(np.mean(np.diag(G)))
        w[idx] = np.linalg.solve(G + lam * np.eye(len(idx)), b)
        return w

    return fn


def base_plus(extra: str) -> WeightFn:
    """Equal-weight four plus one extra signal, whose sign is the sign of its past mean IC."""
    e = CANDS.index(extra)
    base = equal(BASE)

    def fn(p: Panel, t: int, hi: int) -> np.ndarray:
        h = HORIZONS[hi]
        j = _train_idx(t, h)
        w = base(p, t, hi).copy() * 0.8
        if j < 50:
            return base(p, t, hi)
        sign = 1.0 if p.cIC[j, hi, e] >= 0 else -1.0
        w[e] = 0.2 * sign
        return w

    return fn


def run_scheme(p: Panel, fn: WeightFn, hi: int, start: int) -> dict[str, np.ndarray]:
    """Daily IC and top-decile excess from ``start`` on, weights refit every ``REFIT`` dates."""
    ics = np.full(p.D, np.nan)
    exs = np.full(p.D, np.nan)
    w = np.zeros(p.k)
    for t in range(start, p.D):
        if (t - start) % REFIT == 0:
            w = fn(p, t, hi)
        if not np.any(w):
            continue
        ics[t], exs[t] = p.score_stats(t, hi, w)
    return {"ic": ics, "ex": exs}


def summ(x: np.ndarray, h: int) -> dict[str, float | int | None]:
    v = x[np.isfinite(x)]
    n = int(v.size)
    if n < 20:
        return {"n": n, "mean": None, "t": None, "pos": None}
    sd = float(v.std(ddof=1))
    eff = max(n / h, 1.0)
    return {
        "n": n,
        "mean": float(v.mean()),
        "t": float(v.mean() / (sd / math.sqrt(eff))) if sd > 0 else None,
        "pos": float((v > 0).mean()),
    }


def paired(a: np.ndarray, b: np.ndarray, h: int) -> dict[str, float | int | None]:
    return summ(a - b, h)


def study(p: Panel) -> dict[str, Any]:
    out: dict[str, Any] = {
        "first": str(p.dates[0]),
        "last": str(p.dates[-1]),
        "n_dates": p.D,
        "oos_from": str(p.dates[WARMUP]),
        "horizons": list(HORIZONS),
        "candidates": CANDS,
    }
    split = int(p.D * 0.6)
    # A. IC per signal x horizon, whole sample and the two halves
    A: dict[str, Any] = {}
    for ki, s in enumerate(CANDS):
        A[s] = {}
        for hi, h in enumerate(HORIZONS):
            x = p.ic[:, hi, ki]
            A[s][str(h)] = {
                "all": summ(x, h),
                "discover": summ(x[:split], h),
                "check": summ(x[split:], h),
            }
    out["A_ic"] = A
    # B1. rank correlation of the signals (mean over dates)
    sc = np.zeros((p.k, p.k))
    cnt = 0
    for t in range(0, p.D, 5):
        sc += np.corrcoef(p.X[t].T)
        cnt += 1
    out["B_signal_corr"] = (sc / cnt).tolist()
    # B2. do signals win on the same days? correlation of daily IC series at h=20
    h20 = HORIZONS.index(20)
    z = np.nan_to_num(p.ic[:, h20, :])
    out["B_ic_series_corr_h20"] = np.corrcoef(z.T).tolist()
    # B3. horizons vs horizons: rank correlation of later returns, and composite IC across horizons
    hc = np.zeros((p.H, p.H))
    cnt = 0
    for t in range(0, p.D - 130, 5):
        Y = p.Y[t]
        m = np.all(np.isfinite(Y), axis=1)
        if m.sum() < MIN_N:
            continue
        hc += np.corrcoef(Y[m].T)
        cnt += 1
    out["B_return_corr"] = (hc / max(cnt, 1)).tolist()
    comp = equal(BASE)(p, 0, 0)
    comp_ic = np.full((p.D, p.H), np.nan)
    for t in range(p.D):
        for hi in range(p.H):
            comp_ic[t, hi] = p.score_stats(t, hi, comp)[0]
    z2 = np.nan_to_num(comp_ic)
    out["B_composite_ic_corr_across_horizons"] = np.corrcoef(z2.T).tolist()
    # C. schemes out of sample
    schemes: dict[str, WeightFn] = {
        "equal": equal(BASE),
        "ic_weight": ic_weight(BASE),
        "ridge4": ridge(BASE),
        "ridge_all": ridge(CANDS),
    }
    C: dict[str, Any] = {}
    base_runs: dict[int, dict[str, np.ndarray]] = {}
    for hi, h in enumerate(HORIZONS):
        C[str(h)] = {}
        for name, fn in schemes.items():
            r = run_scheme(p, fn, hi, WARMUP)
            if name == "equal":
                base_runs[hi] = r
            C[str(h)][name] = {
                "ic": summ(r["ic"], h),
                "excess": summ(r["ex"], h),
                "ic_vs_equal": paired(r["ic"], base_runs[hi]["ic"], h) if name != "equal" else None,
                "excess_vs_equal": (
                    paired(r["ex"], base_runs[hi]["ex"], h) if name != "equal" else None
                ),
            }
    out["C_schemes"] = C
    # D. ablation
    D: dict[str, Any] = {}
    for hi, h in enumerate(HORIZONS):
        D[str(h)] = {}
        base = base_runs[hi]
        for s in BASE:
            cols = [c for c in BASE if c != s]
            r = run_scheme(p, equal(cols), hi, WARMUP)
            D[str(h)][f"drop_{s}"] = {
                "ic": summ(r["ic"], h),
                "ic_vs_equal": paired(r["ic"], base["ic"], h),
                "excess_vs_equal": paired(r["ex"], base["ex"], h),
            }
        for s in EXTRA:
            r = run_scheme(p, base_plus(s), hi, WARMUP)
            D[str(h)][f"add_{s}"] = {
                "ic": summ(r["ic"], h),
                "ic_vs_equal": paired(r["ic"], base["ic"], h),
                "excess_vs_equal": paired(r["ex"], base["ex"], h),
            }
    out["D_ablation"] = D
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-walkforward-study")
    ap.add_argument("--out", default=str(Path("docs/data/walkforward-study.json")))
    args = ap.parse_args()
    df = build_panel()
    p = Panel(df)
    res = study(p)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote", path, "dates", p.D)


if __name__ == "__main__":
    main()
