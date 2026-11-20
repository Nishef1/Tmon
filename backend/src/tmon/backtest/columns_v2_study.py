"""Does adding one of the new columns make the daily four-signal ranking better?

``python -m tmon.backtest.columns_v2_study --json docs/data/columns-v2-study.json``.
The ranking is the production one (``walkforward_study.BASE``, equal weight of four ranked signals,
the top tenth is the buy zone). For each new column of ``features/extra.py`` and
``features/relative.py`` (point in time) the test is the add-one of ``walkforward_study``: weights
0.8 x the four equal-weight signals plus 0.2 x the column's cross-sectional rank, whose sign is the
sign of its mean IC over dates whose label (``h + 1`` dates ahead) is already known. Daily IC and
the top-decile excess return over the median stock are read from the 500th date on, for 20 and 60
trading days ahead, over the whole out-of-sample span and again over its first and second half, as
the difference to the plain four-signal ranking. The excess is also read net of costs: re-forming
the top tenth every ``h`` dates costs one round trip on the share of names replaced. A column
passes when IC and net excess improve in both halves. ~90 columns are tried, so the number that
pass is compared with the number that pass when the column's ranks are shuffled across stocks
within each date and its sign is learned from the shuffled ICs the same way (the chance level).
Nothing here changes the production ranking.
"""

# ruff: noqa: N803, N806
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest import walkforward_study as wf
from tmon.backtest.extra_columns_study import load_columns
from tmon.features.builder import KEYS
from tmon.features.extra import EXTRA_COLUMNS
from tmon.features.relative import REL_COLUMNS, build_relative

HORIZONS = (20, 60)
WEIGHT = 0.2
PERMS = 20
COST = 0.0175  # round trip for a stock, as in the market_method studies


def _rank(col: str) -> pl.Expr:
    r = pl.col(col).rank("average").over("date")
    return ((r - 0.5) / pl.col(col).count().over("date") - 0.5).alias(f"n_{col}")


def _daily(
    score: np.ndarray, y: np.ndarray, f: np.ndarray, ids: np.ndarray
) -> tuple[float, float, frozenset[int]]:
    m = np.isfinite(y) & np.isfinite(f)
    if m.sum() < wf.MIN_N:
        return math.nan, math.nan, frozenset()
    s, yy, ff = score[m], y[m], f[m]
    if not np.any(s != s[0]):
        return math.nan, math.nan, frozenset()
    ic = float(np.corrcoef(s, yy)[0, 1])
    sel = s > np.quantile(s, 0.9)
    top = ff[sel]
    ex = float(top.mean() - np.median(ff)) if top.size else math.nan
    return ic, ex, frozenset(ids[m][sel].tolist())


def _turnover(now: frozenset[int], before: frozenset[int]) -> float:
    """Share of today's top tenth that was not in the top tenth ``h`` dates earlier."""
    if not now or not before:
        return math.nan
    return 1.0 - len(now & before) / len(now)


def _ics(N: list[np.ndarray], Y: list[np.ndarray], D: int, k: int) -> np.ndarray:
    """Per-date IC of every column with the later return rank (the past mean sets its sign)."""
    ic = np.full((D, k), np.nan)
    for t in range(D):
        m = np.isfinite(Y[t])
        if m.sum() < wf.MIN_N:
            continue
        xs = N[t][m] - N[t][m].mean(0)
        ys = Y[t][m] - Y[t][m].mean()
        den = np.sqrt((xs**2).sum(0) * (ys**2).sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            ic[t] = (xs.T @ ys) / den
    return np.cumsum(np.nan_to_num(ic), axis=0)


def _one_column(
    k: int,
    h: int,
    B: list[np.ndarray],
    N: list[np.ndarray],
    Y: list[np.ndarray],
    F: list[np.ndarray],
    ids: list[np.ndarray],
    cum: np.ndarray,
    base: tuple[np.ndarray, np.ndarray, np.ndarray],
    start: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Daily IC and top-tenth excess (gross, and net of the turnover cost of re-forming the
    top tenth every ``h`` dates) minus the plain ranking's; the column's sign is learned
    walk-forward."""
    D = len(B)
    base_ic, base_ex, base_tau = base
    dic, dex, dnet = (np.full(D, np.nan) for _ in range(3))
    tops: list[frozenset[int]] = [frozenset()] * D
    sign = 1.0
    for t in range(start, D):
        if (t - start) % wf.REFIT == 0:
            j = wf._train_idx(t, h)
            sign = 1.0 if j >= 50 and cum[j, k] >= 0 else (-1.0 if j >= 50 else 0.0)
        s = 0.8 * B[t].mean(1) + WEIGHT * sign * N[t][:, k]
        i2, e2, tops[t] = _daily(s, Y[t], F[t], ids[t])
        dic[t], dex[t] = i2 - base_ic[t], e2 - base_ex[t]
        tau = _turnover(tops[t], tops[t - h]) if t - h >= start else math.nan
        dnet[t] = dex[t] - COST * (tau - base_tau[t])
    return dic, dex, dnet


def _both(x: np.ndarray, start: int, mid: int) -> bool:
    with np.errstate(invalid="ignore"):
        a, b = np.nanmean(x[start:mid]), np.nanmean(x[mid:])
    return bool(np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0)


def run(cols: list[str], df: pl.DataFrame, perms: int) -> dict[str, Any]:
    parts = [p for p in df.partition_by("date", maintain_order=True) if p.height >= wf.MIN_N]
    D = len(parts)
    dates = [p["date"][0] for p in parts]
    base_c = [f"r_{s}" for s in wf.BASE]
    B = [p.select(base_c).to_numpy().astype(float) for p in parts]
    N = [p.select([f"n_{c}" for c in cols]).to_numpy().astype(float) for p in parts]
    ids = [p[KEYS[0]].to_numpy() for p in parts]
    out: dict[str, Any] = {
        "first": str(dates[0]),
        "last": str(dates[-1]),
        "n_dates": D,
        "round_trip_cost": COST,
    }
    start = wf.WARMUP
    out["oos_from"] = str(dates[start])
    rng = np.random.default_rng(11)
    res: dict[str, dict[str, Any]] = {c: {} for c in cols}
    null: dict[str, list[int]] = {}
    for h in HORIZONS:
        Y = [p[f"y_{h}"].to_numpy().astype(float) for p in parts]
        F = [p[f"fwd_{h}"].to_numpy().astype(float) for p in parts]
        cum = _ics(N, Y, D, len(cols))
        base_ic, base_ex, base_tau = (np.full(D, np.nan) for _ in range(3))
        base_top: list[frozenset[int]] = [frozenset()] * D
        for t in range(start, D):
            base_ic[t], base_ex[t], base_top[t] = _daily(B[t].mean(1), Y[t], F[t], ids[t])
            if t - h >= start:
                base_tau[t] = _turnover(base_top[t], base_top[t - h])
        base = (base_ic, base_ex, base_tau)
        out[f"base_turnover_h{h}"] = float(np.nanmean(base_tau))
        mid = start + (D - start) // 2
        halves = {"first": (start, mid), "second": (mid, D), "all": (start, D)}
        passed = 0
        for k, c in enumerate(cols):
            dic, dex, dnet = _one_column(k, h, B, N, Y, F, ids, cum, base, start)
            res[c][str(h)] = {
                name: {
                    "ic": wf.summ(dic[a:b], h),
                    "excess": wf.summ(dex[a:b], h),
                    "excess_net": wf.summ(dnet[a:b], h),
                }
                for name, (a, b) in halves.items()
            }
            passed += _both(dic, start, mid) and _both(dnet, start, mid)
        out[f"better_in_both_halves_h{h}"] = passed
        # chance level: each column's ranks shuffled across stocks per date, its sign learned from
        # the shuffled ICs exactly as for the real column, the same net-of-cost test
        counts = []
        for _ in range(perms):
            Np = [x[rng.permutation(x.shape[0])] for x in N]
            cum_p = _ics(Np, Y, D, len(cols))
            n_pass = 0
            for k in range(len(cols)):
                dic, _dex, dnet = _one_column(k, h, B, Np, Y, F, ids, cum_p, base, start)
                n_pass += _both(dic, start, mid) and _both(dnet, start, mid)
            counts.append(n_pass)
        null[str(h)] = counts
    out["chance_h"] = {
        h: {"mean": float(np.mean(v)), "p95": float(np.percentile(v, 95)), "max": int(max(v))}
        for h, v in null.items()
    }
    out["columns"] = res
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-columns-v2-study")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--perms", type=int, default=PERMS)
    args = ap.parse_args(argv)
    w = load_columns()
    rel = build_relative(
        w["prices"], w["clients"], w["extra"], sectors=w["sectors"], index_close=w["ix"]
    )
    cols = [*EXTRA_COLUMNS, *REL_COLUMNS]
    new = w["extra"].join(rel, on=list(KEYS), how="left")
    df = wf.build_panel(HORIZONS).join(new, on=list(KEYS), how="left")
    df = df.with_columns(*[_rank(c) for c in cols])
    df = df.with_columns([pl.col(f"n_{c}").fill_null(0.0).fill_nan(0.0) for c in cols])
    out = run(cols, df, args.perms)
    text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print({k: v for k, v in out.items() if k != "columns"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
