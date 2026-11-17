"""Monthly-withdrawal study on the last three years only (docs/reports/income-3y-2026-11.md).

Question: 100 million toman in an equal-weight basket of the N most liquid stocks, a fixed amount taken out
every 20 trading days. How long does the capital last, what does the monthly return look like, and how often
is a month at +10% or more?

Conventions: basket re-picked and re-weighted every 20 trading days from the liquidity rank of the day
before; trade at the close; buy 0.62% / sell 1.13% (commission + tax verified, slippage 0.5% assumed);
a withdrawal is paid out of a sale so it also pays 1.13%; daily returns clipped at +-15%; a symbol with no
row on a day returns 0. Nominal toman: inflation is not removed. Runs start every 5 trading days and are
cut at the end of the data.
Run from backend/ with the live env:  python research/market_method/income_3y.py
Output: results_income_3y.json
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import polars as pl

import small_target as st

C = pl.col
G = st.G
HERE = Path(__file__).parent
BUY, SELL = 0.0062, 0.0113
STEP = 20
CAP = 100.0  # million toman


def matrices(years: int = 3) -> tuple[list[dt.date], np.ndarray, np.ndarray]:
    p = st.prepare().select("date", G, "ret", "vmed")
    end = p["date"].max()
    start = end.replace(year=end.year - years) - dt.timedelta(days=45)
    p = p.filter(C("date") >= start).with_columns(C("ret").clip(-0.15, 0.15).fill_null(0.0))
    r = p.pivot(on=G, index="date", values="ret").sort("date")
    v = p.pivot(on=G, index="date", values="vmed").sort("date")
    cols = [c for c in r.columns if c != "date"]
    dates = r["date"].to_list()
    return dates, r.select(cols).fill_null(0.0).to_numpy(), v.select(cols).fill_null(0.0).to_numpy()


def simulate(ret: np.ndarray, vmed: np.ndarray, k0: int, k1: int, n: int, w: float) -> dict:
    """Run days k0..k1-1. Returns the path of the value after each STEP block."""
    h = np.zeros(ret.shape[1])
    v = CAP
    idx = np.argsort(-vmed[k0 - 1])[:n]
    h[idx] = v / n * (1 - BUY)
    v = float(h.sum())
    blocks = []
    last = v
    dead = None
    for k in range(k0, k1):
        h *= 1 + ret[k]
        if (k - k0 + 1) % STEP == 0:
            tot = float(h.sum())
            gross_ret = tot / last - 1  # month before withdrawal and rebalance
            if w > 0:
                out = min(w * (1 + SELL), tot)
                h *= 1 - out / tot
                tot -= out
            if tot <= 0.5:
                dead = len(blocks) + 1
                blocks.append((gross_ret, 0.0))
                break
            target = np.zeros_like(h)
            target[np.argsort(-vmed[k - 1])[:n]] = tot / n
            buys = np.maximum(target - h, 0).sum()
            sells = np.maximum(h - target, 0).sum()
            cost = BUY * buys + SELL * sells
            tot -= cost
            h = target * (tot / target.sum())
            blocks.append((gross_ret, tot))
            last = tot
    return {"blocks": blocks, "dead": dead}


def summarize(runs: list[dict], months: int) -> dict:
    fin = [
        r["blocks"][months - 1][1] if len(r["blocks"]) >= months else (0.0 if r["dead"] else None)
        for r in runs
    ]
    fin = [x for x in fin if x is not None]
    rets = np.array([b[0] for r in runs for b in r["blocks"]])
    dead = sum(1 for r in runs if r["dead"] is not None and r["dead"] <= months)
    return {
        "runs": len(runs),
        "final_median": float(np.median(fin)) if fin else None,
        "final_p10": float(np.percentile(fin, 10)) if fin else None,
        "final_p90": float(np.percentile(fin, 90)) if fin else None,
        "share_below_start": float(np.mean(np.array(fin) < CAP)) if fin else None,
        "share_dead": dead / len(runs) if runs else None,
        "month_mean": float(rets.mean()),
        "month_median": float(np.median(rets)),
        "month_p10": float(np.percentile(rets, 10)),
        "month_p90": float(np.percentile(rets, 90)),
        "share_month_ge_10": float(np.mean(rets >= 0.10)),
        "share_month_lt_0": float(np.mean(rets < 0)),
    }


def main() -> None:
    dates, ret, vmed = matrices(3)
    first = next(i for i, d in enumerate(dates) if d >= dates[-1].replace(year=dates[-1].year - 3))
    print(f"data {dates[0]}..{dates[-1]}, symbols {ret.shape[1]}, 3y window starts {dates[first]}")
    out: dict = {"window": [str(dates[first]), str(dates[-1])], "results": {}}
    for n in (10, 20):
        for w in (0.0, 2.0, 4.0, 6.0, 10.0):
            for months in (12, 24):
                runs = []
                for k0 in range(first, len(dates) - months * STEP, 5):
                    runs.append(simulate(ret, vmed, k0, k0 + months * STEP, n, w))
                if not runs:
                    continue
                s = summarize(runs, months)
                out["results"][f"N{n}_W{w:g}_M{months}"] = s
                print(
                    f"N={n:2d} W={w:4.1f}  {months}m  runs={s['runs']:3d}  final med {s['final_median']:6.1f} "
                    f"p10 {s['final_p10']:6.1f} p90 {s['final_p90']:6.1f}  <start {s['share_below_start']:.0%}  "
                    f"dead {s['share_dead']:.0%} | month mean {s['month_mean']:+.1%} med {s['month_median']:+.1%} "
                    f"p10 {s['month_p10']:+.1%} p90 {s['month_p90']:+.1%} >=10% {s['share_month_ge_10']:.0%} "
                    f"<0 {s['share_month_lt_0']:.0%}"
                )
    # one full-window path, no withdrawal, with the per-half view
    for n in (10, 20):
        r = simulate(ret, vmed, first, len(dates) - 1, n, 0.0)
        b = r["blocks"]
        v = [x[1] for x in b]
        half = len(v) // 2
        out["results"][f"N{n}_full_path"] = {
            "months": len(v),
            "final": v[-1],
            "at_half": v[half - 1],
            "first_half_ret": v[half - 1] / CAP - 1,
            "second_half_ret": v[-1] / v[half - 1] - 1,
        }
        print(f"N={n} full {len(v)} months: {CAP:.0f} -> {v[-1]:.1f}; half {v[half - 1]:.1f}")
    (HERE / "results_income_3y.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
