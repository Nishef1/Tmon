"""How early can the trend ride warn that a buy or a sale is near, and how often is it right?

Report: docs/reports/trend-warn-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_warn.py              # last three years
    TRM_SINCE=2011-03-21 TRM_OUT=results_trend_warn_long.json uv run python research/...

The rule buys and sells at the close of the day the line is crossed (same_day). Each evening two
prices are known for the next day: the entry trigger (``trend_ride.trigger_line``, when no ride
is held) and the sell line (``trend_ride.stop_line``, while one is held). The distance from
today's close to that price is the warning: a buy is near when the needed rise is small, a sale
is near when the close is little above the line.

For every liquid day in the window, by distance bucket and for each half of calendar time: how
often the signal came within 1, 3 and 5 trading days. For every signal: how far the price was
1, 3 and 5 days before it, so how many signals a band of a given width would have warned of
(coverage) and how many warning days were followed by a signal (hit rate).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.core.db import session_scope
from tmon.features.store import load_inputs

SINCE = date.fromisoformat(os.environ.get("TRM_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TRM_OUT", "results_trend_warn.json"))
CACHE = os.environ.get("TRM_PANEL")
G = "instrument_id"
NEAR, TRAIL, CAP = 0.05, 0.35, 250
EDGES = [0.0, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.25]
BANDS = [0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15]
HORIZONS = (1, 3, 5)


def load() -> pl.DataFrame:
    if CACHE and Path(CACHE).exists():
        return pl.read_parquet(CACHE)
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    return tp.build_panel(prices, clients)


def symbol(g: pl.DataFrame) -> dict[str, list]:
    """Rows (date, half-free side, distance, days to the next event or None) of one symbol."""
    a = tr._symbol_arrays(g)
    c = a["close"]
    n = len(c)
    sig = tr.entry_signals(c, a["sma50"], a["sma200"], a["hi250"], NEAR)
    trend = tr.trending(c, a["sma50"], a["sma200"])
    rs = tr.rides(c, a["up"], a["down"], sig, TRAIL, CAP, trend, same_day=True)
    trig = tr.trigger_line(c, NEAR)
    stop = tr.stop_line(c, rs, TRAIL, CAP, trend)
    free = np.ones(n, dtype=bool)
    sell_ev = np.zeros(n, dtype=bool)
    for r in rs:
        end = n - 1 if r.exit is None else r.exit
        free[r.signal : end + 1] = False
        if r.exit_signal is not None:
            sell_ev[r.exit_signal] = True
    buy_ev = sig.copy()

    def next_event(ev: np.ndarray) -> np.ndarray:
        """Days from each row to the next event row after it; a large number when none."""
        out = np.full(n, 10**6)
        nxt = 10**9
        for i in range(n - 1, -1, -1):
            out[i] = nxt - i
            if ev[i]:
                nxt = i
        return out

    with np.errstate(invalid="ignore", divide="ignore"):
        db = trig / c - 1
        ds = c / stop - 1
    nb, ns = next_event(buy_ev), next_event(sell_ev)
    d, liq = g["date"].to_list(), g["liquid"].to_numpy()
    rows: dict[str, list] = {"buy": [], "sell": []}
    for t in range(n - 1):
        if not liq[t] or d[t] < SINCE:
            continue
        if free[t] and np.isfinite(db[t]):
            # a buy event counts while the symbol stays free; it is the next signal
            rows["buy"].append((d[t], float(db[t]), int(nb[t])))
        if np.isfinite(ds[t]):
            rows["sell"].append((d[t], float(ds[t]), int(ns[t])))
    # per event: the distance k days before it
    ev_rows: dict[str, list] = {"buy": [], "sell": []}
    for side, ev, dist in (("buy", buy_ev, db), ("sell", sell_ev, ds)):
        for u in map(int, np.flatnonzero(ev)):
            if u < 6 or not liq[u] or d[u] < SINCE:
                continue
            if side == "buy" and not free[u - 1]:
                continue
            ev_rows[side].append((d[u], [float(dist[u - k]) for k in HORIZONS]))
    return {"rows_buy": rows["buy"], "rows_sell": rows["sell"],
            "ev_buy": ev_rows["buy"], "ev_sell": ev_rows["sell"]}  # fmt: skip


def main() -> None:
    panel = load()
    acc: dict[str, list] = {"rows_buy": [], "rows_sell": [], "ev_buy": [], "ev_sell": []}
    for _, g in panel.sort(G, "date").group_by([G], maintain_order=True):
        for k, v in symbol(g).items():
            acc[k].extend(v)
    last = panel["date"].max()
    split = SINCE + (last - SINCE) / 2  # type: ignore[operator]
    out: dict = {"since": str(SINCE), "last": str(last), "split": str(split)}
    for side in ("buy", "sell"):
        rows = pl.DataFrame(acc[f"rows_{side}"], schema=["date", "dist", "next"], orient="row")
        rows = rows.with_columns(half=(pl.col("date") >= split).cast(pl.Int8))
        buckets = []
        for lo, hi in zip([-1.0, *EDGES], [*EDGES, 99.0], strict=True):
            b: dict = {"lo": lo, "hi": hi}
            for h in (0, 1):
                x = rows.filter(
                    (pl.col("half") == h) & (pl.col("dist") > lo) & (pl.col("dist") <= hi)
                )
                b[f"n{h}"] = x.height
                for k in HORIZONS:
                    b[f"p{k}_{h}"] = float((x["next"] <= k).mean()) if x.height else None  # type: ignore[arg-type]
            buckets.append(b)
        bands = []
        ev = acc[f"ev_{side}"]
        for w in BANDS:
            r: dict = {"band": w}
            for h in (0, 1):
                e = [dist for dd, dist in ev if (dd >= split) == bool(h)]
                for i, k in enumerate(HORIZONS):
                    r[f"cover{k}_{h}"] = float(np.mean([x[i] <= w for x in e])) if e else None
                x = rows.filter((pl.col("half") == h) & (pl.col("dist") <= w))
                r[f"days_{h}"] = x.height
                for k in HORIZONS:
                    r[f"hit{k}_{h}"] = float((x["next"] <= k).mean()) if x.height else None  # type: ignore[arg-type]
                # warning days per event: how long a warning stands before its signal
                r[f"days_per_event_{h}"] = x.height / max(1, len(e))
            r["events"] = [sum((dd >= split) == bool(h) for dd, _ in ev) for h in (0, 1)]
            bands.append(r)
        out[side] = {"buckets": buckets, "bands": bands}
        print(side)
        for b in buckets:
            print(f"  ({b['lo']:+.3f},{b['hi']:+.3f}] n={b['n0']:6d}/{b['n1']:6d} "
                  + " ".join(f"p{k}={b[f'p{k}_0'] or 0:.3f}/{b[f'p{k}_1'] or 0:.3f}" for k in HORIZONS))  # fmt: skip
        for r in bands:
            print(f"  band {r['band']:.3f} ev={r['events']} "
                  + " ".join(f"cov{k}={r[f'cover{k}_0'] or 0:.2f}/{r[f'cover{k}_1'] or 0:.2f}" for k in HORIZONS)
                  + " " + " ".join(f"hit{k}={r[f'hit{k}_0'] or 0:.3f}/{r[f'hit{k}_1'] or 0:.3f}" for k in HORIZONS)
                  + f" days/ev={r['days_per_event_0']:.1f}/{r['days_per_event_1']:.1f}")  # fmt: skip
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
