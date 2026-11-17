"""Monthly withdrawals when the top 10 comes from the site's own ranking (docs/reports/income-model-2026-11.md).

Out-of-sample only: the walk-forward scores of ``fundamental_model.py`` (test period from 2024-07-01):
  V0   the four-signal v2 composite (momentum, flow, volume, volatility rules of ADR 0003)
  F    the statements score (cheap P/E, profit growth, margin change, low leverage)
  VF   the mean of the two percentile ranks
  GBM  LightGBM with the statements; GBM-p the same without
  RND  ten names drawn at random from the same basket;  ALL the equal-weight mean of the whole basket
Every 20 trading days the top 10 by the score is bought at the close of t+1 and held 20 days
(``fwd_20`` of the panel). A name kept from the last hold is not traded. Buy 0.62% / sell 1.13% on what
is traded, a withdrawal is sold too (1.13%). 100 million toman, fixed monthly withdrawal W. All 20 start
offsets are used. Nominal toman.
Run from backend/ with the live env:  python research/market_method/income_model.py
Output: results_income_model.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import fundamental_model as fm  # noqa: E402

C = pl.col
G = fm.G
H = fm.H
TOP = fm.TOP
BUY, SELL = 0.0062, 0.0113
CAP = 100.0
SCORES = {"V0": "composite", "F": "F", "VF": "VF", "GBM": "gbm", "GBM-p": "gbm_p"}


def blocks_for(wf: pl.DataFrame, score: str | None, offset: int, rng: np.random.Generator) -> list:
    """(date, picked ids, mean fwd) for every 20th date from ``offset``; score None = whole basket."""
    dates = wf["date"].unique().sort().to_list()[offset::H]
    out = []
    for d in dates:
        day = wf.filter((C("date") == d) & C(f"fwd_{H}").is_not_null())
        if day.height < TOP * 3:
            continue
        if score == "ALL":
            out.append((d, frozenset(), float(day[f"fwd_{H}"].mean()), 0.0))
            continue
        if score == "RND":
            idx = rng.choice(day.height, TOP, replace=False)
            top = day[idx]
        else:
            ok = day.filter(C(score).is_not_null())
            if ok.height < TOP:
                continue
            top = ok.sort(score, descending=True).head(TOP)
        out.append((d, frozenset(top[G].to_list()), float(top[f"fwd_{H}"].mean()), 1.0))
    return out


def run(blocks: list, b0: int, months: int, w: float) -> dict:
    v = CAP * (1 - BUY)
    prev: frozenset = blocks[b0][1]
    path = []
    rets = []
    for k in range(b0, min(b0 + months, len(blocks))):
        _, names, r, _t = blocks[k]
        if k > b0:
            if names and prev:
                f = len(names - prev) / TOP
                v *= 1 - f * (BUY + SELL)
            elif not names:
                pass
        v *= 1 + r
        rets.append(r)
        if w > 0:
            v -= min(w * (1 + SELL), v)
        path.append(v)
        prev = names
        if v <= 0.5:
            v = 0.0
            break
    return {"path": path, "rets": rets, "dead": bool(path) and path[-1] <= 0.5}


def main() -> None:
    p, _ = fm.build()
    wf = fm.walk_forward(p)
    dates = wf["date"].unique().sort().to_list()
    print("test", dates[0], "->", dates[-1], "days", len(dates))
    rng = np.random.default_rng(3)
    names = list(SCORES) + ["RND", "ALL"]
    res: dict = {"test": [str(dates[0]), str(dates[-1])], "scores": {}}
    for nm in names:
        col = SCORES.get(nm, nm)
        runs_by_w: dict[float, list[dict]] = {w: [] for w in (0.0, 2.0, 4.0, 10.0)}
        mon_h1, mon_h2 = [], []
        for off in range(H):
            bl = blocks_for(wf, col, off, rng)
            half = len(bl) // 2
            mon_h1 += [b[2] for b in bl[:half]]
            mon_h2 += [b[2] for b in bl[half:]]
            for b0 in range(0, len(bl) - 12 + 1):
                for w in runs_by_w:
                    r_ = run(bl, b0, 12, w)
                    r_["late"] = b0 >= (len(bl) - 12 + 1) / 2
                    runs_by_w[w].append(r_)
        allr = np.array([r for run_ in runs_by_w[0.0] for r in run_["rets"]])
        row: dict = {
            "month_mean": float(allr.mean()),
            "month_median": float(np.median(allr)),
            "month_p10": float(np.percentile(allr, 10)),
            "share_ge_10": float(np.mean(allr >= 0.10)),
            "share_lt_0": float(np.mean(allr < 0)),
            "h1_mean": float(np.mean(mon_h1)),
            "h2_mean": float(np.mean(mon_h2)),
            "runs": len(runs_by_w[0.0]),
            "w": {},
        }
        for w, rs in runs_by_w.items():
            fin = np.array([r["path"][-1] if len(r["path"]) == 12 else 0.0 for r in rs])
            row["w"][f"{w:g}"] = {
                "median": float(np.median(fin)),
                "p10": float(np.percentile(fin, 10)),
                "p90": float(np.percentile(fin, 90)),
                "below_start": float(np.mean(fin < CAP)),
                "dead": float(np.mean([r["dead"] for r in rs])),
                "median_early_start": float(
                    np.median([x for x, r in zip(fin, rs) if not r["late"]])
                ),
                "median_late_start": float(np.median([x for x, r in zip(fin, rs) if r["late"]])),
                "dead_early": float(np.mean([r["dead"] for r in rs if not r["late"]])),
                "dead_late": float(np.mean([r["dead"] for r in rs if r["late"]])),
            }
        res["scores"][nm] = row
        f = row["w"]
        print(
            f"{nm:6s} month mean {row['month_mean']:+.1%} med {row['month_median']:+.1%} "
            f"p10 {row['month_p10']:+.1%} >=10% {row['share_ge_10']:.0%} <0 {row['share_lt_0']:.0%} "
            f"| halves {row['h1_mean']:+.1%}/{row['h2_mean']:+.1%} | 12m final W0 {f['0']['median']:.0f} "
            f"W2 {f['2']['median']:.0f} W4 {f['4']['median']:.0f} W10 {f['10']['median']:.0f} "
            f"(W10 dead {f['10']['dead']:.0%}, W4 below start {f['4']['below_start']:.0%}) "
            f"| early/late starts W4 {f['4']['median_early_start']:.0f}/{f['4']['median_late_start']:.0f} "
            f"W10 {f['10']['median_early_start']:.0f}/{f['10']['median_late_start']:.0f} "
            f"dead W10 {f['10']['dead_early']:.0%}/{f['10']['dead_late']:.0%}"
        )
    (HERE / "results_income_model.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
