"""How close do the trend-ride marks come to the real turns, and which fix brings them closer?

Report: docs/reports/trend-marks-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_marks.py            # last three years
    TRM_SINCE=2011-03-21 TRM_OUT=results_trend_marks_long.json uv run python research/...

Every variant runs the whole ride sequence of each symbol, as the site does (a ride blocks new
signals until it is sold), so a variant that sells earlier can also buy again earlier. Judged on
rides whose signal day was liquid and on or after ``SINCE``:

- per ride: net after the round-trip cost (an open ride at the last close);
- per symbol: the day-by-day money of a person following the marks on that one symbol (cash
  between rides, the cost paid on each buy day), grown separately over each half of calendar time,
  so a long ride counts in the half its days fall in; paired against the current rule, with a 95%
  interval from resampling symbols;
- accuracy: how far the buy sat above the lowest close of the 120 days before it, how much of the
  peak the sale gave back, and how often the price rose more than 20% in the 60 days after a sale.

Both halves are split at the median entry date of the current rule.
"""

from __future__ import annotations

import json
import os
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

SINCE = date.fromisoformat(os.environ.get("TRM_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TRM_OUT", "results_trend_marks.json"))
CACHE = os.environ.get("TRM_PANEL")  # optional parquet of the panel, to rerun quickly
G = "instrument_id"
NO_CAP = 10**9


@dataclass(frozen=True)
class Variant:
    key: str
    near_high: float = 0.05
    trail: float = 0.35
    max_hold: int = 250
    # after the gain from the buy reaches the first number, the trail narrows to the second
    lock: tuple[tuple[float, float], ...] = ()
    # after a sale forced by max_hold, buy again at the next close if the entry state still holds
    rebuy_after_cap: bool = False
    # past max_hold, sell only on a close where the entry state no longer holds (or the trail)
    cap_needs_break: bool = False
    # at max_hold, when the entry state still holds, keep the shares and start the count, the
    # trail peak and the cap again from that day (a rebuy without paying the cost)
    renew_at_cap: bool = False
    # renew needs only the trend part of the state (close over the 50-day average over the 200-day)
    renew_on_trend: bool = False


VARIANTS = [
    Variant("now"),
    Variant("no_cap", max_hold=NO_CAP),
    Variant("rebuy_after_cap", rebuy_after_cap=True),
    Variant("cap_needs_break", cap_needs_break=True),
    Variant("renew_at_cap", renew_at_cap=True),
    Variant("renew_on_trend", renew_at_cap=True, renew_on_trend=True),
    Variant("no_cap_lock100_25", max_hold=NO_CAP, lock=((1.0, 0.25),)),
    Variant("no_cap_lock50_25", max_hold=NO_CAP, lock=((0.5, 0.25),)),
    Variant("no_cap_lock100_25_200_20", max_hold=NO_CAP, lock=((1.0, 0.25), (2.0, 0.20))),
    Variant("no_cap_near10", max_hold=NO_CAP, near_high=0.10),
    Variant("no_cap_trail30", max_hold=NO_CAP, trail=0.30),
    Variant("no_cap_trail40", max_hold=NO_CAP, trail=0.40),
]


def load() -> tuple[pl.DataFrame, float]:
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
    return panel, float(cost)


def run(a: dict[str, np.ndarray], v: Variant) -> list[tuple[int, int, int | None, int, bool]]:
    """(signal, buy, sale or None, peak, sold_by_cap) per ride of one symbol."""
    c = a["close"]
    n = len(c)
    sig = tr.entry_signals(c, a["sma50"], a["sma200"], a["hi250"], v.near_high)
    with np.errstate(invalid="ignore"):
        state = (
            (c > a["sma50"]) & (a["sma50"] > a["sma200"]) & (c >= (1 - v.near_high) * a["hi250"])
        )
        trend = (c > a["sma50"]) & (a["sma50"] > a["sma200"])
    keep = trend if v.renew_on_trend else state
    out: list[tuple[int, int, int | None, int, bool]] = []
    todo = list(map(int, np.flatnonzero(sig)))
    busy = -1
    i = 0
    forced: int | None = None
    while i < len(todo) or forced is not None:
        if forced is not None:
            t, forced = forced, None
        else:
            t = todo[i]
            i += 1
            if t <= busy:
                continue
        e = t + 1
        while e < n and a["up"][e] and e - t <= tr.QUEUE_WAIT:
            e += 1
        if e >= n or a["up"][e]:
            continue
        pk, hit, cap = e, -1, False
        start = e  # the day the cap counts from
        for j in range(e + 1, n):
            if c[j] > c[pk]:
                pk = j
            tl = v.trail
            for g, t2 in v.lock:
                if c[pk] / c[e] - 1 >= g:
                    tl = t2
            if c[j] < (1 - tl) * c[pk]:
                hit = j
                break
            if j - start >= v.max_hold and not (v.cap_needs_break and state[j]):
                if v.renew_at_cap and keep[j]:
                    start, pk = j, j
                    continue
                hit, cap = j, True
                break
        if hit < 0:
            out.append((t, e, None, pk, False))
            break
        x = hit + 1
        while x < n and a["down"][x]:
            x += 1
        if x >= n:
            out.append((t, e, None, pk, False))
            break
        out.append((t, e, x, pk, cap))
        busy = x
        if cap and v.rebuy_after_cap and state[x]:
            forced = x  # the sale and the new buy are at the next closes
    return out


def summarise(rows: list[dict], split: date) -> dict:
    def block(rs: list[dict]) -> dict:
        if not rs:
            return {"n": 0}
        net = np.array([r["net"] for r in rs])
        closed = [r for r in rs if r["sold"]]
        give = np.array([r["giveback"] for r in closed]) if closed else np.array([np.nan])
        miss = np.array([r["missed"] for r in closed if r["missed"] is not None])
        return {
            "n": len(rs),
            "open": sum(1 for r in rs if not r["sold"]),
            "net_mean": float(net.mean()),
            "net_median": float(np.median(net)),
            "win": float((net > 0).mean()),
            "p10": float(np.quantile(net, 0.1)),
            "hold_median": float(np.median([r["hold"] for r in rs])),
            "above_low_median": float(np.median([r["above_low"] for r in rs])),
            "giveback_median": float(np.nanmedian(give)),
            "missed_20_share": float(miss.mean()) if len(miss) else None,
            "cap_sales": sum(1 for r in rs if r["cap"]),
        }

    return {
        **block(rows),
        "halves": [
            block([r for r in rows if r["entry"] < split]),
            block([r for r in rows if r["entry"] >= split]),
        ],
    }


def main() -> None:
    panel, cost = load()
    syms = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        syms.append((int(iid), g["date"].to_list(), g["liquid"].to_numpy(), tr._symbol_arrays(g)))
    per: dict[str, list[dict]] = {}
    for v in VARIANTS:
        rows = []
        for iid, d, liq, a in syms:
            c = a["close"]
            last = len(c) - 1
            for t, e, x, pk, cap in run(a, v):
                if not liq[t] or d[t] < SINCE:
                    continue
                end = last if x is None else x
                lo = c[max(0, e - 120) : e + 1].min()
                after = c[x + 1 : x + 61] if x is not None else np.array([])
                rows.append(
                    {
                        "iid": iid,
                        "path": (d, c, e, end),
                        "entry": d[e],
                        "net": float(c[end] / c[e] - 1 - cost),
                        "sold": x is not None,
                        "cap": cap,
                        "hold": end - e,
                        "above_low": float(c[e] / lo - 1),
                        "giveback": float(1 - c[x] / c[pk]) if x is not None else None,
                        "missed": None
                        if x is None or len(after) < 60
                        else bool(after.max() / c[x] - 1 > 0.20),
                    }
                )
        per[v.key] = rows
    split = sorted(r["entry"] for r in per["now"])[len(per["now"]) // 2]
    res: dict = {"since": str(SINCE), "split": str(split), "cost": cost, "variants": {}}
    # per symbol: daily money following the marks, grown over each half of calendar time
    ids = sorted({r["iid"] for rows in per.values() for r in rows})

    def chained(rows: list[dict], half: int) -> np.ndarray:
        m = dict.fromkeys(ids, 1.0)
        for r in rows:
            d, c, e, end = r["path"]
            for j in range(e, end + 1):
                if (d[j] >= split) != bool(half):
                    continue
                if j == e:
                    m[r["iid"]] *= 1 - cost
                else:
                    m[r["iid"]] *= c[j] / c[j - 1]
        return np.array([m[i] - 1 for i in ids])

    base = [chained(per["now"], h) for h in (0, 1)]
    rng = np.random.default_rng(1)
    for v in VARIANTS:
        out = summarise(per[v.key], split)
        pair = []
        for h in (0, 1):
            ch = chained(per[v.key], h)
            dlt = ch - base[h]
            bs = [dlt[rng.integers(0, len(dlt), len(dlt))].mean() for _ in range(2000)]
            pair.append(
                {
                    "symbol_chain_mean": float(ch.mean()),
                    "symbol_chain_median": float(np.median(ch)),
                    "diff_mean": float(dlt.mean()),
                    "diff_ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                    "better_share": float((dlt > 1e-9).mean()),
                    "worse_share": float((dlt < -1e-9).mean()),
                }
            )
        out["per_symbol"] = pair
        res["variants"][v.key] = out
        b = out["halves"]
        print(
            f"{v.key:26s} n={out['n']:5d} net={out['net_mean']:+.3f}/{out['net_median']:+.3f} "
            f"halves={[round(x.get('net_mean', 0), 3) for x in b]} "
            f"chain={[round(p['symbol_chain_mean'], 3) for p in pair]} "
            f"diff={[round(p['diff_mean'], 3) for p in pair]} "
            f"ci={[[round(q, 3) for q in p['diff_ci95']] for p in pair]} "
            f"low={out['above_low_median']:.2f} give={out['giveback_median']:.2f} "
            f"miss={out['missed_20_share']} cap={out['cap_sales']}"
        )
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
