"""Does the trend rule read trends better on weekly, monthly, three-month or six-month candles?

Report: docs/reports/trend-audit-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_timeframes.py            # last three years
    TTF_SINCE=2011-03-21 TTF_OUT=results_trend_timeframes_long.json uv run python research/...

Candles follow the Persian calendar as the chart does (week from Saturday, month, season, half
year), built from adjusted daily closes. Part 1 runs the trend rule with the same shape on longer
candles: decisions only on a candle's last trading day, at that day's close (a locked day waits
for the next open one, as in the live rule):

- ``daily``: the live rule (engine.yaml numbers).
- ``weekly``: close over its 10-week average over its 40-week one, within 5% of the 52-week high
  close; sell when a weekly close is 35% under the highest weekly close since the buy.
- ``monthly``: close over its 10-month average, within 5% of the 12-month high close; the same
  35% trail on monthly closes.
- ``daily_sell_weekly``: the daily buy, but the line is checked only on the week's last day, so a
  dip inside a week does not sell.
- ``daily_if_month_up``: the daily rule, but a buy only when the last finished month closed over
  its 10-month average.

Judged like docs/reports/trend-marks-2026-11.md: per symbol, the money of following the marks,
grown over each half of calendar time, paired against ``daily`` with a 95% interval over symbols.

Part 2 asks whether a candle's direction carries on: for each candle size, liquid symbols are
split by the last finished candle's return into the upper and lower half of that day, and the
next candle's return is compared (top minus bottom, before cost), per half of time.
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
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs

SINCE = date.fromisoformat(os.environ.get("TTF_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TTF_OUT", "results_trend_timeframes.json"))
CACHE = os.environ.get("TTF_PANEL")
G = "instrument_id"
EPS = tr.EPS


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


def period_ids(days: list[date]) -> dict[str, np.ndarray]:
    """Per day, the id of its Persian week (from Saturday), month, season and half year."""
    import jdatetime  # type: ignore[import-untyped]

    js = [jdatetime.date.fromgregorian(date=d) for d in days]
    # 2000-01-01 was a Saturday, so whole weeks counted from it start on Saturday
    return {
        "1w": np.array([(d - date(2000, 1, 1)).days // 7 for d in days]),
        "1m": np.array([j.year * 12 + j.month - 1 for j in js]),
        "3m": np.array([j.year * 4 + (j.month - 1) // 3 for j in js]),
        "6m": np.array([j.year * 2 + (j.month - 1) // 6 for j in js]),
    }


def last_of_period(pid: np.ndarray) -> np.ndarray:
    """True on each period's last trading day (the newest period counts as unfinished)."""
    out = np.zeros(len(pid), dtype=bool)
    out[:-1] = pid[:-1] != pid[1:]
    return out


def sma_on(close: np.ndarray, ends: np.ndarray, k: int) -> np.ndarray:
    """The k-candle average of candle closes, placed on each candle's last day (nan elsewhere)."""
    idx = np.flatnonzero(ends)
    cc = close[idx]
    out = np.full(len(close), np.nan)
    if len(cc) >= k:
        cs = np.cumsum(np.insert(cc, 0, 0.0))
        out[idx[k - 1 :]] = (cs[k:] - cs[:-k]) / k
    return out


def high_on(close: np.ndarray, ends: np.ndarray, k: int) -> np.ndarray:
    idx = np.flatnonzero(ends)
    cc = close[idx]
    out = np.full(len(close), np.nan)
    for i in range(k - 1, len(cc)):
        out[idx[i]] = cc[i - k + 1 : i + 1].max()
    return out


SPECS = ["daily", "weekly", "monthly", "daily_sell_weekly", "daily_if_month_up"]


def ride_loop(
    close: np.ndarray,
    up: np.ndarray,
    down: np.ndarray,
    sig: np.ndarray,
    check: np.ndarray,
    trend: np.ndarray,
    trail: float,
    max_hold: int,
) -> list[tuple[int, int, int | None]]:
    """Like tmon.backtest.trend_ride.rides with same-day trades, but the line and the cap are
    looked at only on ``check`` days. (signal, buy, sale or None) per ride."""
    n = len(close)
    out: list[tuple[int, int, int | None]] = []
    busy = -1
    for t in map(int, np.flatnonzero(sig)):
        if t <= busy:
            continue
        e = t if not up[t] else t + 1
        while e < n and up[e] and e - t <= tr.QUEUE_WAIT:
            e += 1
        if e >= n or up[e]:
            continue
        pk, hit, start = e, -1, e
        for j in range(e + 1, n):
            if not check[j]:
                continue
            if close[j] > close[pk]:
                pk = j
            if close[j] < (1 - trail) * close[pk] * (1 - EPS):
                hit = j
                break
            if j - start >= max_hold:
                if trend[j]:
                    start = pk = j
                    continue
                hit = j
                break
        if hit < 0:
            out.append((t, e, None))
            break
        x = hit if not down[hit] else hit + 1
        while x < n and down[x]:
            x += 1
        if x >= n:
            out.append((t, e, None))
            break
        out.append((t, e, x))
        busy = x
    return out


def rides_for(
    key: str, a: dict[str, np.ndarray], pid: dict[str, np.ndarray], p: dict
) -> list[tuple[int, int, int | None]]:
    c = a["close"]
    n = len(c)
    near, trail, cap = p["near_high"], p["trail"], p["max_hold_days"]
    every = np.ones(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        d_trend = tr.trending(c, a["sma50"], a["sma200"])
    d_sig = tr.entry_signals(c, a["sma50"], a["sma200"], a["hi250"], near)
    if key in ("weekly", "monthly"):
        ends = last_of_period(pid["1w" if key == "weekly" else "1m"])
        if key == "weekly":
            s1, s2, hi = sma_on(c, ends, 10), sma_on(c, ends, 40), high_on(c, ends, 52)
            with np.errstate(invalid="ignore"):
                trend = (c > s1 * (1 + EPS)) & (s1 > s2 * (1 + EPS))
        else:
            s1, hi = sma_on(c, ends, 10), high_on(c, ends, 12)
            with np.errstate(invalid="ignore"):
                trend = c > s1 * (1 + EPS)
        with np.errstate(invalid="ignore"):
            on = trend & (c >= (1 - near) * hi * (1 - EPS)) & ends
        # a signal is the first candle end in the state after one out of it
        idx = np.flatnonzero(ends)
        on_e = on[idx]
        first = on_e & ~np.concatenate([[True], on_e[:-1]])
        sig = np.zeros(n, dtype=bool)
        sig[idx[first]] = True
        return ride_loop(c, a["up"], a["down"], sig, ends, trend & ends, trail, cap)
    if key == "daily_sell_weekly":
        ends = last_of_period(pid["1w"])
        return ride_loop(c, a["up"], a["down"], d_sig, ends, d_trend, trail, cap)
    if key == "daily_if_month_up":
        ends = last_of_period(pid["1m"])
        s10 = sma_on(c, ends, 10)
        idx = np.flatnonzero(ends)
        ok = np.zeros(n, dtype=bool)
        # each day takes the state of the last finished month before it
        state = np.full(n, np.nan)
        with np.errstate(invalid="ignore"):
            state[idx] = (c[idx] > s10[idx]).astype(float)
        last = np.nan
        for i in range(n):
            ok[i] = last == 1.0
            if not np.isnan(state[i]):
                last = state[i]
        return ride_loop(c, a["up"], a["down"], d_sig & ok, every, d_trend, trail, cap)
    return ride_loop(c, a["up"], a["down"], d_sig, every, d_trend, trail, cap)


def persistence(syms: list, split: date) -> dict:
    """Top-half minus bottom-half next-candle return, by candle size and half of time."""
    out = {}
    for tf in ("1w", "1m", "3m", "6m"):
        recs = []
        for _iid, d, liq, a, pid in syms:
            ends = np.flatnonzero(last_of_period(pid[tf]))
            c = a["close"]
            for k in range(1, len(ends) - 1):
                i0, i1, i2 = ends[k - 1], ends[k], ends[k + 1]
                if d[i1] < SINCE or not liq[i1]:
                    continue
                recs.append((d[i1], pid[tf][i1], c[i1] / c[i0] - 1, c[i2] / c[i1] - 1))
        if not recs:
            continue
        df = pl.DataFrame(recs, schema=["date", "pid", "past", "next"], orient="row")
        df = df.with_columns(
            top=pl.col("past") >= pl.col("past").median().over("pid"),
            n=pl.len().over("pid"),
        ).filter(pl.col("n") >= 20)
        per = (
            df.group_by("pid")
            .agg(
                pl.col("date").min(),
                (
                    pl.col("next").filter(pl.col("top")).mean()
                    - pl.col("next").filter(~pl.col("top")).mean()
                ).alias("spread"),
            )
            .sort("pid")
        )
        halves = []
        for h in (0, 1):
            s = per.filter((pl.col("date") >= split) == bool(h))["spread"].drop_nans().to_numpy()
            halves.append(
                {
                    "periods": len(s),
                    "spread_mean": float(s.mean()) if len(s) else None,
                    "t": float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))
                    if len(s) > 2
                    else None,
                    "positive_share": float((s > 0).mean()) if len(s) else None,
                }
            )
        out[tf] = halves
        print(
            "persist",
            tf,
            [
                (
                    x["periods"],
                    x["spread_mean"] and round(x["spread_mean"], 4),
                    x["t"] and round(x["t"], 2),
                )
                for x in halves
            ],
        )
    return out


def main() -> None:
    panel, cost, p = load()
    syms = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        d = g["date"].to_list()
        syms.append((int(iid), d, g["liquid"].to_numpy(), tr._symbol_arrays(g), period_ids(d)))
    per: dict[str, list[dict]] = {}
    for key in SPECS:
        rows = []
        for iid, d, liq, a, pid in syms:
            c = a["close"]
            last = len(c) - 1
            for t, e, x in rides_for(key, a, pid, p):
                if not liq[t] or d[t] < SINCE:
                    continue
                end = last if x is None else x
                after = c[x + 1 : x + 61] if x is not None else np.array([])
                lo = c[max(0, e - 120) : e + 1].min()
                rows.append(
                    {
                        "iid": iid,
                        "path": (d, c, e, end),
                        "entry": d[e],
                        "net": float(c[end] / c[e] - 1 - cost),
                        "hold": end - e,
                        "above_low": float(c[e] / lo - 1),
                        "missed": None
                        if x is None or len(after) < 60
                        else bool(after.max() / c[x] - 1 > 0.20),
                    }
                )
        per[key] = rows
    split = sorted(r["entry"] for r in per["daily"])[len(per["daily"]) // 2]
    res: dict = {"since": str(SINCE), "split": str(split), "cost": cost, "variants": {}}
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

    base = [chained(per["daily"], h) for h in (0, 1)]
    rng = np.random.default_rng(1)
    for key in SPECS:
        rows = per[key]
        pair = []
        for h in (0, 1):
            ch = chained(rows, h)
            dlt = ch - base[h]
            bs = [dlt[rng.integers(0, len(dlt), len(dlt))].mean() for _ in range(2000)]
            pair.append(
                {
                    "chain_mean": float(ch.mean()),
                    "chain_median": float(np.median(ch)),
                    "diff_mean": float(dlt.mean()),
                    "diff_ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                }
            )
        nets = np.array([r["net"] for r in rows]) if rows else np.array([np.nan])
        miss = [r["missed"] for r in rows if r["missed"] is not None]
        out = {
            "n": len(rows),
            "net_mean": float(np.nanmean(nets)),
            "net_median": float(np.nanmedian(nets)),
            "win": float(np.nanmean(nets > 0)),
            "hold_median": float(np.median([r["hold"] for r in rows])) if rows else None,
            "above_low_median": float(np.median([r["above_low"] for r in rows])) if rows else None,
            "missed_20_share": float(np.mean(miss)) if miss else None,
            "per_symbol": pair,
        }
        res["variants"][key] = out
        print(
            f"{key:18s} n={out['n']:5d} net={out['net_mean']:+.3f}/{out['net_median']:+.3f} "
            f"win={out['win']:.2f} hold={out['hold_median']} low={out['above_low_median']:.2f} "
            f"chain={[round(q['chain_mean'], 3) for q in pair]} "
            f"diff={[round(q['diff_mean'], 3) for q in pair]} "
            f"ci={[[round(z, 3) for z in q['diff_ci95']] for q in pair]} "
            f"miss={out['missed_20_share']}"
        )
    res["persistence"] = persistence(syms, split)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
