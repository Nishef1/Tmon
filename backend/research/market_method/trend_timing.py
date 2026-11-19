"""Can the trend ride buy and sell earlier, before a buy or sell queue blocks it?

Report: docs/reports/trend-timing-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_timing.py            # last three years
    TRM_SINCE=2011-03-21 TRM_OUT=results_trend_timing_long.json uv run python research/...

The site's rule signals on the close of day t and buys at the close of t+1; a sale follows the
close that broke the trailing line, at the next close. When that next day is locked (high equals
low, a queue), the order waits. This study measures what the waits cost, and tests:

- buying or selling at the close of the signal day itself (an order placed in the last minutes of
  the session, when the line is already crossed by the live price), unless that day is locked;
- waiting for a buy queue without the 20-day limit;
- earlier entries (a 60-day breakout, a surge day with heavy volume before a queue forms);
- an early exit on the first heavy-volume down day with real-money selling («هشدار»), once the
  price is already below its peak.

A flat price (a halted or locked stock) makes the 50-day average equal the close; a rounding error
of 1e-16 then decides "above the average". Every comparison here uses a 1e-9 relative margin.

Judging is that of trend_marks.py: per-symbol day-by-day money over each half of calendar time,
paired against the current rule, with a 95% interval from resampling symbols, round-trip cost
included. A fill at the close of a day is the official close (a volume-weighted price); the
robustness check repeats the same-day fills at the last trade price instead.
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
OUT = Path(__file__).with_name(os.environ.get("TRM_OUT", "results_trend_timing.json"))
CACHE = os.environ.get("TRM_PANEL")
G = "instrument_id"
EPS = 1e-9
NEAR, TRAIL, CAP = 0.05, 0.35, 250


@dataclass(frozen=True)
class Variant:
    key: str
    entry: str = "near_high"  # near_high | breakout60 | surge
    same_buy: bool = False  # buy at the close of the signal day when it is not locked
    same_sell: bool = False  # sell at the close of the day that broke the line when not locked
    wait: int = tr.QUEUE_WAIT  # trading days a buy waits for a buy queue
    warn_exit: float | None = None  # sell after a warning day once this far below the peak
    fill: str = "close"  # close | last, the price of a same-day fill
    eps: float = EPS


VARIANTS = [
    Variant("now_raw", eps=0.0),  # the site before the margin fix
    Variant("now"),
    Variant("wait_any", wait=10**6),
    Variant("same_buy", same_buy=True),
    Variant("same_sell", same_sell=True),
    Variant("same_both", same_buy=True, same_sell=True),
    Variant("same_both_wait_any", same_buy=True, same_sell=True, wait=10**6),
    Variant("same_both_last", same_buy=True, same_sell=True, fill="last"),
    Variant("breakout60", entry="breakout60"),
    Variant("surge", entry="surge"),
    Variant("warn_exit_10", warn_exit=0.10),
    Variant("warn_exit_20", warn_exit=0.20),
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


def arrays(g: pl.DataFrame) -> dict[str, np.ndarray]:
    a = tr._symbol_arrays(g)
    last = g["adj_last"].fill_null(0.0).to_numpy().astype(float)
    a["last"] = np.where(last > 0, last, a["close"])
    a["warn"] = g["warn"].fill_null(False).to_numpy()
    a["ret1"] = g["ret1"].fill_null(0.0).to_numpy()
    vol, v20 = g["volume"].to_numpy().astype(float), g["vol20"].to_numpy().astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a["vr"] = np.nan_to_num(vol / v20)
    c = a["close"]
    prev = pl.Series(c).shift(1).rolling_max(60, min_samples=60).to_numpy()
    a["hi60_prev"] = np.nan_to_num(prev, nan=np.inf)
    return a


def signals(a: dict[str, np.ndarray], v: Variant) -> tuple[np.ndarray, np.ndarray]:
    """(signal flags, trend flags) with the relative margin ``v.eps``."""
    c, s50, s200, hi = a["close"], a["sma50"], a["sma200"], a["hi250"]
    k = 1 + v.eps
    with np.errstate(invalid="ignore"):
        trend = (c > s50 * k) & (s50 > s200 * k)
        if v.entry == "near_high":
            on = trend & (c >= (1 - NEAR) * hi)
        elif v.entry == "breakout60":
            on = trend & (c > a["hi60_prev"] * k)
        else:  # surge: a strong traded up day on heavy volume, near the high, before a queue
            on = trend & (c >= 0.90 * hi) & (a["ret1"] >= 0.025) & (a["vr"] >= 2.0) & ~a["up"]
    prev = np.concatenate([[True], on[:-1]])
    return on & ~prev, trend


def run(a: dict[str, np.ndarray], v: Variant) -> list[dict]:
    c, up, down = a["close"], a["up"], a["down"]
    px = a["last"] if v.fill == "last" else c
    n = len(c)
    sig, trend = signals(a, v)
    out: list[dict] = []
    busy = -1
    for t in map(int, np.flatnonzero(sig)):
        if t <= busy:
            continue
        if v.same_buy and not up[t]:
            e, bpx = t, px[t]
        else:
            e = t + 1
            while e < n and up[e] and e - t <= v.wait:
                e += 1
            if e >= n:
                break
            if up[e]:
                out.append({"t": t, "dropped": True})
                continue
            bpx = c[e]
        pk, hit, start = e, -1, e
        for j in range(e + 1, n):
            if c[j] > c[pk]:
                pk = j
            if c[j] < (1 - TRAIL) * c[pk]:
                hit = j
                break
            if v.warn_exit is not None and a["warn"][j] and c[j] < (1 - v.warn_exit) * c[pk]:
                hit = j
                break
            if j - start >= CAP:
                if trend[j]:
                    start = pk = j
                    continue
                hit = j
                break
        rec = {"t": t, "e": e, "bpx": float(bpx), "pk": pk, "dropped": False,
               "buy_wait": e - t - (0 if v.same_buy and e == t else 1)}  # fmt: skip
        if hit < 0:
            out.append({**rec, "x": None, "spx": None, "sell_wait": 0})
            break
        if v.same_sell and not down[hit]:
            x, spx = hit, px[hit]
        else:
            x = hit + 1
            while x < n and down[x]:
                x += 1
            if x >= n:
                out.append({**rec, "x": None, "spx": None, "sell_wait": 0})
                break
            spx = c[x]
        sw = x - hit - (0 if v.same_sell and x == hit else 1)
        out.append({**rec, "x": x, "spx": float(spx), "sell_wait": sw, "hit": hit})
        busy = x
    return out


def main() -> None:
    panel, cost = load()
    syms = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        syms.append((int(iid), g["date"].to_list(), g["liquid"].to_numpy(), arrays(g)))
    per: dict[str, list[dict]] = {}
    for v in VARIANTS:
        rows = []
        for iid, d, liq, a in syms:
            c = a["close"]
            last = len(c) - 1
            for r in run(a, v):
                t = r["t"]
                if not liq[t] or d[t] < SINCE:
                    continue
                if r["dropped"]:
                    # a buy queue that never opened in time: what the price did meanwhile
                    rows.append({"iid": iid, "dropped": True,
                                 "gain_missed": float(c[min(t + 1 + v.wait, last)] / c[t] - 1)})  # fmt: skip
                    continue
                e, x = r["e"], r["x"]
                end = last if x is None else x
                spx = c[last] if x is None else r["spx"]
                lo = c[max(0, e - 120) : e + 1].min()
                rows.append(
                    {
                        "iid": iid,
                        "dropped": False,
                        "path": (d, c, e, end, r["bpx"], spx),
                        "entry": d[e],
                        "net": float(spx / r["bpx"] - 1 - cost),
                        "sold": x is not None,
                        "hold": end - e,
                        "above_low": float(r["bpx"] / lo - 1),
                        "giveback": None if x is None else float(1 - spx / c[r["pk"]]),
                        "buy_wait": r["buy_wait"],
                        "buy_slip": float(r["bpx"] / c[t] - 1),  # paid over the signal close
                        "sell_wait": r["sell_wait"],
                        "sell_slip": None if x is None else float(spx / c[r["hit"]] - 1),
                    }
                )
        per[v.key] = rows
    base_rows = [r for r in per["now"] if not r["dropped"]]
    split = sorted(r["entry"] for r in base_rows)[len(base_rows) // 2]
    ids = sorted({r["iid"] for rows in per.values() for r in rows})

    def chained(rows: list[dict], half: int) -> np.ndarray:
        m = dict.fromkeys(ids, 1.0)
        for r in rows:
            if r["dropped"]:
                continue
            d, c, e, end, bpx, spx = r["path"]
            for j in range(e, end + 1):
                if (d[j] >= split) != bool(half):
                    continue
                f = (1 - cost) * c[e] / bpx if j == e else c[j] / c[j - 1]
                if j == end:
                    f *= spx / c[end]
                m[r["iid"]] *= f
        return np.array([m[i] - 1 for i in ids])

    base = [chained(per["now"], h) for h in (0, 1)]
    rng = np.random.default_rng(1)
    res: dict = {"since": str(SINCE), "split": str(split), "cost": cost, "variants": {}}
    for v in VARIANTS:
        rows = per[v.key]
        ok = [r for r in rows if not r["dropped"]]
        drop = [r for r in rows if r["dropped"]]
        net = np.array([r["net"] for r in ok])
        sold = [r for r in ok if r["sold"]]
        out = {
            "n": len(ok),
            "dropped": len(drop),
            "dropped_gain_median": float(np.median([r["gain_missed"] for r in drop]))
            if drop
            else None,
            "net_mean": float(net.mean()),
            "net_median": float(np.median(net)),
            "win": float((net > 0).mean()),
            "p10": float(np.quantile(net, 0.1)),
            "above_low_median": float(np.median([r["above_low"] for r in ok])),
            "giveback_median": float(np.median([r["giveback"] for r in sold])),
            "buy_waited_share": float(np.mean([r["buy_wait"] > 0 for r in ok])),
            "buy_slip_mean": float(np.mean([r["buy_slip"] for r in ok])),
            "buy_slip_when_waited": float(np.mean([r["buy_slip"] for r in ok if r["buy_wait"]]))
            if any(r["buy_wait"] for r in ok)
            else None,
            "sell_waited_share": float(np.mean([r["sell_wait"] > 0 for r in sold])),
            "sell_slip_mean": float(np.mean([r["sell_slip"] for r in sold])),
            "sell_slip_when_waited": float(
                np.mean([r["sell_slip"] for r in sold if r["sell_wait"]])
            )
            if any(r["sell_wait"] for r in sold)
            else None,
            "halves": [
                {"n": len(h), "net_mean": float(np.mean([r["net"] for r in h])) if h else None}
                for h in ([r for r in ok if r["entry"] < split], [r for r in ok if r["entry"] >= split])
            ],
        }
        pair = []
        for h in (0, 1):
            ch = chained(rows, h)
            dlt = ch - base[h]
            bs = [dlt[rng.integers(0, len(dlt), len(dlt))].mean() for _ in range(2000)]
            pair.append(
                {
                    "symbol_chain_mean": float(ch.mean()),
                    "diff_mean": float(dlt.mean()),
                    "diff_ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                    "better_share": float((dlt > 1e-9).mean()),
                    "worse_share": float((dlt < -1e-9).mean()),
                }
            )
        out["per_symbol"] = pair
        res["variants"][v.key] = out
        print(
            f"{v.key:20s} n={out['n']:5d} drop={out['dropped']:3d} "
            f"net={out['net_mean']:+.3f}/{out['net_median']:+.3f} win={out['win']:.2f} "
            f"chain={[round(p['symbol_chain_mean'], 3) for p in pair]} "
            f"diff={[round(p['diff_mean'], 3) for p in pair]} "
            f"ci={[[round(q, 3) for q in p['diff_ci95']] for p in pair]} "
            f"low={out['above_low_median']:.2f} give={out['giveback_median']:.2f} "
            f"bw={out['buy_waited_share']:.2f}/{out['buy_slip_mean']:+.3f} "
            f"sw={out['sell_waited_share']:.2f}/{out['sell_slip_mean']:+.3f}"
        )
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
