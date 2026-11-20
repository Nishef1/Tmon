"""Does adding one of the new columns make the daily four-signal ranking better?

``python -m tmon.backtest.columns_v2_study --json docs/data/columns-v2-study.json``.
The ranking is the production one (``walkforward_study.BASE``, equal weight of four ranked signals,
the top tenth is the buy zone). For each new column of ``features/extra.py`` and
``features/relative.py`` (point in time) the test is the add-one of ``walkforward_study``: weights
0.8 x the four equal-weight signals plus 0.2 x the column's cross-sectional rank, whose sign is the
sign of its mean IC over dates whose label (``h + 1`` dates ahead) is already known. Daily IC and
the top-decile excess return over the median stock are read from the 500th date on, for 20 and 60
trading days ahead, over the whole out-of-sample span and again over its first and second half, as
the difference to the plain four-signal ranking. ~90 columns are tried, so the number that improve
in both halves is compared with the number that do the same when the column's ranks are shuffled
across stocks within each date (the chance level). Nothing here changes the production ranking.
"""

# ruff: noqa: N806
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


def _rank(col: str) -> pl.Expr:
    r = pl.col(col).rank("average").over("date")
    return ((r - 0.5) / pl.col(col).count().over("date") - 0.5).alias(f"n_{col}")


def _daily(score: np.ndarray, y: np.ndarray, f: np.ndarray) -> tuple[float, float]:
    m = np.isfinite(y) & np.isfinite(f)
    if m.sum() < wf.MIN_N:
        return math.nan, math.nan
    s, yy, ff = score[m], y[m], f[m]
    if not np.any(s != s[0]):
        return math.nan, math.nan
    ic = float(np.corrcoef(s, yy)[0, 1])
    top = ff[s > np.quantile(s, 0.9)]
    return ic, float(top.mean() - np.median(ff)) if top.size else math.nan


def run(cols: list[str], df: pl.DataFrame, perms: int) -> dict[str, Any]:
    parts = [p for p in df.partition_by("date", maintain_order=True) if p.height >= wf.MIN_N]
    D = len(parts)
    dates = [p["date"][0] for p in parts]
    base_c = [f"r_{s}" for s in wf.BASE]
    B = [p.select(base_c).to_numpy().astype(float) for p in parts]
    N = [p.select([f"n_{c}" for c in cols]).to_numpy().astype(float) for p in parts]
    out: dict[str, Any] = {"first": str(dates[0]), "last": str(dates[-1]), "n_dates": D}
    start = wf.WARMUP
    out["oos_from"] = str(dates[start])
    rng = np.random.default_rng(11)
    res: dict[str, dict[str, Any]] = {c: {} for c in cols}
    null: dict[str, list[int]] = {}
    for h in HORIZONS:
        Y = [p[f"y_{h}"].to_numpy().astype(float) for p in parts]
        F = [p[f"fwd_{h}"].to_numpy().astype(float) for p in parts]
        # per-date IC of every column with the later return rank: the past mean sets its sign
        ic = np.full((D, len(cols)), np.nan)
        for t in range(D):
            m = np.isfinite(Y[t])
            if m.sum() < wf.MIN_N:
                continue
            xs = N[t][m] - N[t][m].mean(0)
            ys = Y[t][m] - Y[t][m].mean()
            den = np.sqrt((xs**2).sum(0) * (ys**2).sum())
            with np.errstate(invalid="ignore", divide="ignore"):
                ic[t] = (xs.T @ ys) / den
        cum = np.cumsum(np.nan_to_num(ic), axis=0)
        base_ic = np.full(D, np.nan)
        base_ex = np.full(D, np.nan)
        for t in range(start, D):
            base_ic[t], base_ex[t] = _daily(B[t].mean(1), Y[t], F[t])
        mid = start + (D - start) // 2
        passed = 0
        for k, c in enumerate(cols):
            dic = np.full(D, np.nan)
            dex = np.full(D, np.nan)
            sign = 1.0
            for t in range(start, D):
                if (t - start) % wf.REFIT == 0:
                    j = wf._train_idx(t, h)
                    sign = 1.0 if j >= 50 and cum[j, k] >= 0 else (-1.0 if j >= 50 else 0.0)
                s = 0.8 * B[t].mean(1) + WEIGHT * sign * N[t][:, k]
                i2, e2 = _daily(s, Y[t], F[t])
                dic[t], dex[t] = i2 - base_ic[t], e2 - base_ex[t]
            halves = {
                "first": (start, mid),
                "second": (mid, D),
            }
            row: dict[str, Any] = {}
            for name, (a, b) in halves.items():
                row[name] = {
                    "ic": wf.summ(dic[a:b], h),
                    "excess": wf.summ(dex[a:b], h),
                }
            row["all"] = {"ic": wf.summ(dic, h), "excess": wf.summ(dex, h)}
            res[c][str(h)] = row
            if (
                (row["first"]["ic"]["mean"] or 0) > 0
                and (row["second"]["ic"]["mean"] or 0) > 0
                and (row["first"]["excess"]["mean"] or 0) > 0
                and (row["second"]["excess"]["mean"] or 0) > 0
            ):
                passed += 1
        out[f"better_in_both_halves_h{h}"] = passed
        # chance level: the same test with each column's ranks shuffled across stocks per date
        counts = []
        for _ in range(perms):
            Np = [x[rng.permutation(x.shape[0])] for x in N]
            n_pass = 0
            for k in range(len(cols)):
                dic = np.full(D, np.nan)
                dex = np.full(D, np.nan)
                for t in range(start, D):
                    s = 0.8 * B[t].mean(1) + WEIGHT * Np[t][:, k]
                    i2, e2 = _daily(s, Y[t], F[t])
                    dic[t], dex[t] = i2 - base_ic[t], e2 - base_ex[t]
                a1 = np.nanmean(dic[start:mid]) > 0 and np.nanmean(dic[mid:]) > 0
                a2 = np.nanmean(dex[start:mid]) > 0 and np.nanmean(dex[mid:]) > 0
                n_pass += bool(a1 and a2)
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
