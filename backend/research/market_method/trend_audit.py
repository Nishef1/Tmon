"""Why do the trend-ride marks buy at a top and sell while the price still rises; does a fix help?

Report: docs/reports/trend-audit-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_audit.py            # last three years
    TRA_SINCE=2011-03-21 TRA_OUT=results_trend_audit_long.json uv run python research/...

Part 1 counts, over every liquid ride, the two mistakes the owner saw on the chart: a buy right
after a big run that then loses (the run before the signal), and a sale after which the price
rose more than 20% within 60 days, split by the reason of the sale (the trail or the hold cap).

Part 2 runs the live ride function (``tmon.backtest.trend_ride.rides``) with changed inputs and
judges each change the way docs/reports/trend-marks-2026-11.md does: the day-by-day money of a
person following the marks on one symbol, grown over each half of calendar time, paired against
the current rule, with a 95% interval from resampling symbols.

- ``skipN``: no buy when the close rose more than N% in the 20 trading days before the signal; the
  signal is lost until the state breaks and forms again.
- ``waitN``: the same, but the buy comes on the first later day in the entry state whose 20-day
  rise is at most N%.
- ``cap_trail_only``: at the hold cap the ride is always renewed, so only the trail sells.
- ``cap_off``: no hold cap at all (the same as the line above, kept as a check).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs

SINCE = date.fromisoformat(os.environ.get("TRA_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TRA_OUT", "results_trend_audit.json"))
CACHE = os.environ.get("TRA_PANEL")  # optional parquet of the panel, to rerun quickly
G = "instrument_id"
LOOK = 20


@dataclass(frozen=True)
class Variant:
    key: str
    max_run: float | None = None  # largest 20-day rise before a buy
    wait: bool = False  # True: buy later when the rise cools; False: drop the signal
    renew_always: bool = False
    max_hold: int | None = None


VARIANTS = [
    Variant("now"),
    *(Variant(f"skip{int(x * 100)}", max_run=x) for x in (0.15, 0.20, 0.30, 0.40)),
    *(Variant(f"wait{int(x * 100)}", max_run=x, wait=True) for x in (0.15, 0.20, 0.30, 0.40)),
    Variant("cap_trail_only", renew_always=True),
    Variant("cap_off", max_hold=10**9),
]


def load() -> tuple[pl.DataFrame, float, dict]:
    cfg = get_engine_config()
    with session_scope() as s:
        rules = RuleBook.from_session(s)
        if CACHE and Path(CACHE).exists():
            panel = pl.read_parquet(CACHE)
        else:
            prices, clients, _ = load_inputs(s)
            panel = tp.build_panel(prices, clients)
    as_of = panel["date"].max()
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip  # type: ignore[arg-type]
    return panel, float(cost), cfg.v2.trend_ride.model_dump()


def run20(c: np.ndarray) -> np.ndarray:
    out = np.full(len(c), np.nan)
    out[LOOK:] = c[LOOK:] / c[:-LOOK] - 1
    return out


def signals(a: dict[str, np.ndarray], near: float, v: Variant) -> np.ndarray:
    c = a["close"]
    sig = tr.entry_signals(c, a["sma50"], a["sma200"], a["hi250"], near)
    if v.max_run is None:
        return sig
    r = run20(c)
    calm = ~(r > v.max_run)  # nan (short history) counts as calm, as the live rule has no run
    if not v.wait:
        return sig & calm
    with np.errstate(invalid="ignore"):
        on = tr.trending(c, a["sma50"], a["sma200"]) & (c >= (1 - near) * a["hi250"] * (1 - tr.EPS))
    ok = on & calm
    # the first calm day of each stretch in the state
    start = np.cumsum(sig)  # stretch id, counted from each fresh entry signal
    out = np.zeros(len(c), dtype=bool)
    seen = -1
    for i in np.flatnonzero(ok):
        if start[i] != seen and start[i] > 0:
            out[i] = True
            seen = start[i]
    return out


def main() -> None:
    panel, cost, p = load()
    near, trail, cap = p["near_high"], p["trail"], p["max_hold_days"]
    syms = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        a = tr._symbol_arrays(g)
        syms.append((int(iid), g["date"].to_list(), g["liquid"].to_numpy(), a))
    per: dict[str, list[dict]] = {}
    for v in VARIANTS:
        rows = []
        for iid, d, liq, a in syms:
            c = a["close"]
            with np.errstate(invalid="ignore"):
                trend = tr.trending(c, a["sma50"], a["sma200"])
            if v.renew_always:
                trend = np.ones(len(c), dtype=bool)
            rs = tr.rides(
                c, a["up"], a["down"], signals(a, near, v), trail, v.max_hold or cap, trend, True
            )
            r20 = run20(c)
            last = len(c) - 1
            for r in rs:
                if r.entry is None or not liq[r.signal] or d[r.signal] < SINCE:
                    continue
                e, x = r.entry, r.exit
                end = last if x is None else x
                after = c[x + 1 : x + 61] if x is not None else np.array([])
                sold_cap = (
                    x is not None
                    and r.exit_signal is not None
                    and r.peak is not None
                    and c[r.exit_signal] >= (1 - trail) * c[r.peak] * (1 - tr.EPS)
                )
                rows.append(
                    {
                        "iid": iid,
                        "path": (d, c, e, end),
                        "entry": d[e],
                        "net": float(c[end] / c[e] - 1 - cost),
                        "run20": None if np.isnan(r20[r.signal]) else float(r20[r.signal]),
                        "sold": x is not None,
                        "cap": bool(sold_cap),
                        "missed": None
                        if x is None or len(after) < 60
                        else bool(after.max() / c[x] - 1 > 0.20),
                    }
                )
        per[v.key] = rows

    split = sorted(r["entry"] for r in per["now"])[len(per["now"]) // 2]
    res: dict = {"since": str(SINCE), "split": str(split), "cost": cost, "params": p}

    # part 1: where the current rule goes wrong
    now = per["now"]
    bins = [(-9, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 9)]
    by_run = []
    for lo, hi in bins:
        rs = [r for r in now if r["run20"] is not None and lo < r["run20"] <= hi]
        halves = []
        for h in (0, 1):
            hs = [r for r in rs if (r["entry"] >= split) == bool(h)]
            nets = np.array([r["net"] for r in hs]) if hs else np.array([np.nan])
            halves.append(
                {
                    "n": len(hs),
                    "net_mean": float(np.nanmean(nets)),
                    "net_median": float(np.nanmedian(nets)),
                    "win": float(np.nanmean(nets > 0)),
                }
            )
        by_run.append({"run20": [lo, hi], "n": len(rs), "halves": halves})
    sales = []
    for cap_sale in (False, True):
        rs = [r for r in now if r["sold"] and r["cap"] == cap_sale and r["missed"] is not None]
        sales.append(
            {
                "reason": "cap" if cap_sale else "trail",
                "n": len(rs),
                "rose_20_after": float(np.mean([r["missed"] for r in rs])) if rs else None,
            }
        )
    res["now_by_run20"] = by_run
    res["now_sales"] = sales
    for b in by_run:
        print("run20", b["run20"], b["n"], [(x["n"], round(x["net_mean"], 3)) for x in b["halves"]])
    print("sales", sales)

    # part 2: the changes, per symbol money paired against the current rule
    ids = sorted({r["iid"] for rows in per.values() for r in rows})

    def chained(rows: list[dict], half: int) -> np.ndarray:
        m = dict.fromkeys(ids, 1.0)
        for r in rows:
            d, c, e, end = r["path"]
            for j in range(e, end + 1):
                if (d[j] >= split) != bool(half):
                    continue
                m[r["iid"]] *= (1 - cost) if j == e else c[j] / c[j - 1]
        return np.array([m[i] - 1 for i in ids])

    base = [chained(per["now"], h) for h in (0, 1)]
    rng = np.random.default_rng(1)
    pick: Callable[[np.ndarray], float] = lambda x: float(np.mean(x))  # noqa: E731
    res["variants"] = {}
    for v in VARIANTS:
        rows = per[v.key]
        pair = []
        for h in (0, 1):
            ch = chained(rows, h)
            dlt = ch - base[h]
            bs = [pick(dlt[rng.integers(0, len(dlt), len(dlt))]) for _ in range(2000)]
            pair.append(
                {
                    "chain_mean": float(ch.mean()),
                    "chain_median": float(np.median(ch)),
                    "diff_mean": float(dlt.mean()),
                    "diff_ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                    "better_share": float((dlt > 1e-9).mean()),
                    "worse_share": float((dlt < -1e-9).mean()),
                }
            )
        nets = np.array([r["net"] for r in rows])
        miss = [r["missed"] for r in rows if r["missed"] is not None]
        out = {
            "n": len(rows),
            "net_mean": float(nets.mean()),
            "win": float((nets > 0).mean()),
            "missed_20_share": float(np.mean(miss)) if miss else None,
            "cap_sales": sum(1 for r in rows if r["cap"]),
            "per_symbol": pair,
        }
        res["variants"][v.key] = out
        print(
            f"{v.key:15s} n={out['n']:5d} net={out['net_mean']:+.3f} win={out['win']:.2f} "
            f"chain={[round(q['chain_mean'], 3) for q in pair]} "
            f"diff={[round(q['diff_mean'], 3) for q in pair]} "
            f"ci={[[round(z, 3) for z in q['diff_ci95']] for q in pair]} "
            f"miss={out['missed_20_share']} cap={out['cap_sales']}"
        )
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
