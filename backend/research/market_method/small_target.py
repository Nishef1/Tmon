"""Small-target swing test: buy a "low", sell at +3%, is it a profit after costs?  (docs/reports/small-target-2026-11.md)

Entry: close of t+1 after the signal day t (never t). Exit: a limit sell at entry*(1+tp) filled when a later day's
high reaches it; a stop at entry*(1-sl) filled when a later day's low reaches it (if both on one day, the stop is
assumed first); otherwise the close of the last allowed day. Prices are adjusted. Net = gross minus the round
trip cost (1.75%). Entries on days where the whole range is one price (locked at the limit) are skipped.
Universe: liquid 60% (median traded value of 20 days). Both halves of time; each signal is compared with every
liquid entry on the same days ("same-day mean"), so a rising market does not look like skill.
Run from backend/ with the live env.  Output: results_small_target.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

C = pl.col
G = "instrument_id"
COST = 0.0175
HERE = Path(__file__).parent
NMAX = 20


def prepare() -> pl.DataFrame:
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    p = p.with_columns(C("date").cast(pl.Date))
    c, h = C("adj_close"), C("adj_high")
    p = p.with_columns(
        vmed=C("value").rolling_median(20, min_samples=20).over(G),
        ret=(c / c.shift(1) - 1).over(G),
        hi20=h.rolling_max(20, min_samples=20).over(G),
        hi252=h.rolling_max(250, min_samples=200).over(G),
        lo60=C("adj_low").rolling_min(60, min_samples=60).over(G),
        hi60=h.rolling_max(60, min_samples=60).over(G),
        locked=(C("adj_high") == C("adj_low")),
    )
    p = p.with_columns(
        red=(C("ret") < 0).cast(pl.Int8),
        dd20=c / C("hi20") - 1,
        dd252=c / C("hi252") - 1,
        pos60=(c - C("lo60")) / (C("hi60") - C("lo60")),
    )
    # consecutive red closes
    p = p.with_columns(
        grp=(C("red") == 0).cum_sum().over(G),
    ).with_columns(reds=C("red").cum_sum().over(G, "grp"))
    # Wilder-style RSI(14)
    d = C("ret")
    up, dn = d.clip(lower_bound=0), (-d).clip(lower_bound=0)
    p = p.with_columns(
        au=up.ewm_mean(alpha=1 / 14, min_samples=14).over(G),
        ad=dn.ewm_mean(alpha=1 / 14, min_samples=14).over(G),
    ).with_columns(rsi=100 - 100 / (1 + C("au") / C("ad")))
    p = p.with_columns(rsi_prev=C("rsi").shift(1).over(G))
    # liquid 60% of the day
    p = p.filter(C("vmed").is_not_null())
    p = p.with_columns(lq=C("vmed").rank("average").over("date") / C("vmed").count().over("date"))
    # future path: entry close t+1, days t+2..t+1+NMAX
    shifts = []
    for k in range(1, NMAX + 2):
        shifts += [
            C("adj_high").shift(-k).over(G).alias(f"h{k}"),
            C("adj_low").shift(-k).over(G).alias(f"l{k}"),
            C("adj_close").shift(-k).over(G).alias(f"c{k}"),
        ]
    p = p.with_columns(*shifts).with_columns(entry_locked=C("locked").shift(-1).over(G))
    return p


def outcomes(d: pl.DataFrame, tp: float, sl: float | None, n: int) -> np.ndarray:
    """Net return per row for the exit rule; NaN where the path is not complete."""
    e = d["c1"].to_numpy()
    hi = np.stack([d[f"h{k}"].to_numpy() for k in range(2, n + 2)], axis=1)
    lo = np.stack([d[f"l{k}"].to_numpy() for k in range(2, n + 2)], axis=1)
    last = d[f"c{n + 1}"].to_numpy()
    hit_tp = hi >= (e * (1 + tp))[:, None]
    hit_sl = lo <= (e * (1 - sl))[:, None] if sl is not None else np.zeros_like(hit_tp)
    any_ev = hit_tp | hit_sl
    first = np.where(any_ev.any(axis=1), any_ev.argmax(axis=1), -1)
    idx = np.arange(len(e))
    stop_first = np.where(first >= 0, hit_sl[idx, np.maximum(first, 0)], False)
    gross = np.where(first < 0, last / e - 1, np.where(stop_first, -(sl or 0.0), tp))
    return gross - COST


def stats(net: np.ndarray, base: np.ndarray) -> dict:
    ok = ~np.isnan(net)
    x = net[ok]
    if x.size == 0:
        return {"n": 0}
    return {
        "n": int(x.size),
        "net": float(x.mean()),
        "median": float(np.median(x)),
        "win": float((x > 0).mean()),
        "p10": float(np.quantile(x, 0.10)),
        "vs_same_day": float((net[ok] - base[ok]).mean()),
    }


def main() -> int:
    p = prepare().filter((C("lq") > 0.4) & C("c1").is_not_null() & (C("entry_locked") == False))  # noqa: E712
    p = p.filter(C("adj_close") > 0)
    mid = p["date"].sort()[p.height // 2]
    out: dict = {"split": str(mid), "rows": p.height}
    signals = {
        "all liquid (random entry)": pl.lit(True),
        "6+ red closes in a row": C("reds") >= 6,
        "10%+ below 20-day high": C("dd20") <= -0.10,
        "bottom 10% of 60-day range": C("pos60") <= 0.10,
        "RSI crossed back above 30": (C("rsi") > 30) & (C("rsi_prev") <= 30),
        "RSI crossed 30 and 30%+ below 52w high": (C("rsi") > 30)
        & (C("rsi_prev") <= 30)
        & (C("dd252") <= -0.30),
        "fell 3%+ today": C("ret") <= -0.03,
        "30%+ below 52w high": C("dd252") <= -0.30,
    }
    configs = [(0.03, 0.05, 10), (0.03, None, 10), (0.05, 0.07, 20), (0.03, 0.03, 5)]
    out["configs"] = [{"tp": a, "sl": b, "n": c} for a, b, c in configs]
    results = []
    for tp, sl, n in configs:
        net_all = outcomes(p, tp, sl, n)
        pp = p.with_columns(pl.Series("net", net_all).fill_nan(None))
        base = pp.group_by("date").agg(C("net").mean().alias("bm"))
        pp = pp.join(base, on="date")
        bm = pp["bm"].fill_null(float("nan")).to_numpy()
        for name, cond in signals.items():
            m = pp.select(cond.alias("m"))["m"].fill_null(False).to_numpy()
            row = {"tp": tp, "sl": sl, "n": n, "signal": name}
            for hlf, sel in (("h1", pp["date"] < mid), ("h2", pp["date"] >= mid)):
                s = sel.to_numpy() & m
                net = pp["net"].fill_null(float("nan")).to_numpy()[s]
                row[hlf] = stats(net, bm[s])
                row[hlf]["days"] = int(pp.filter(pl.Series(s))["date"].n_unique())
                # hit shares (gross-based)
                row[hlf]["tp_share"] = (
                    float(((net + COST) >= tp - 1e-9)[~np.isnan(net)].mean()) if net.size else None
                )
            results.append(row)
    out["results"] = results
    (HERE / "results_small_target.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in results:
        f = lambda h: (  # noqa: E731
            f"n={r[h]['n']:6d} net {100 * r[h]['net']:+5.2f}% win {100 * r[h]['win']:3.0f}% p10 {100 * r[h]['p10']:+6.1f}% "
            f"vs-day {100 * r[h]['vs_same_day']:+5.2f}%"
            if r[h]["n"]
            else "none"
        )
        print(
            f"tp{r['tp']:.2f} sl{r['sl']} N{r['n']:2d} {r['signal'][:38]:38s} H1 {f('h1')} | H2 {f('h2')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
