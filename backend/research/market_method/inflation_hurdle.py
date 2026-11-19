"""Inflation as the bar: how often holding the market, or trading the site's trend-ride rule,
ended ahead of consumer prices, after how many trades and over how long.
(docs/reports/inflation-hurdle-2026-11.md)

Owner's point: a portfolio's result only counts if it beats inflation; taxes and fees are a
detail next to that. So every return here is set against the Statistical Centre's CPI of all
households (monthly index from docs/data/inflation.csv, `cpi_mom` compounded; a day inside a month
is interpolated geometrically). This is ex-post: the CPI of a month is used for that month even
though it is published about a week later, which is right for "did it beat inflation" and is not a
forecast.

Three parts, last three years of entries (and 1399 onward for the indices):
1. Index windows. For each start day and holding period (1, 3, 6, 12, 24 months), the total index
   and the equal-weight index against inflation over the same days. Share of start days that
   ended ahead, and the median real return; by half of the start dates.
2. Trend-ride trades (the rule on each stock page; tmon.backtest.trend_ride with the site's
   numbers and cost). Each trade's net return against inflation over its own holding days.
3. One slot, many trades. A trader with one slot takes, after each sale, a trade picked at random
   among the rule's entries in the next 20 trading days (or waits in cash, earning nothing). After
   N trades: share of paths whose compound net return beat inflation over the elapsed time.
   2,000 paths from each first-half and second-half start.

Run from backend/ with the live env:  python research/market_method/inflation_hurdle.py
Output: results_inflation_hurdle.json
"""

from __future__ import annotations

import csv
import json
import random
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent.parent / "src"))

from tmon.backtest import trend_ride as tr  # noqa: E402
from tmon.backtest import turning as tp  # noqa: E402
from tmon.core.db import session_scope  # noqa: E402
from tmon.core.engine_config import get_engine_config  # noqa: E402
from tmon.domain.rules import CostModel, RuleBook  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402
from tmon.storage.models import MarketIndexDaily  # noqa: E402

TOTAL = "32097828799138957"  # شاخص کل
EQUAL = "67130298613737946"  # شاخص هم‌وزن
MONTHS = (1, 3, 6, 12, 24)
PATHS = 2000
NEXT_WINDOW = 20


def cpi_curve() -> tuple[list[date], list[float]]:
    with (ROOT / "docs" / "data" / "inflation.csv").open(encoding="utf-8") as f:
        rows = sorted(
            (date.fromisoformat(r["ref_period"]), float(r["value"]))
            for r in csv.DictReader(f)
            if r["series"] == "cpi_mom" and r["source"] == "sci"
        )
    days = [rows[0][0] - timedelta(days=30)]
    lvl = [1.0]
    for d, m in rows:
        days.append(d)
        lvl.append(lvl[-1] * (1 + m))
    return days, lvl


DAYS, LVL = cpi_curve()


def cpi(d: date) -> float | None:
    if d < DAYS[0] or d > DAYS[-1]:
        return None
    i = bisect_right(DAYS, d) - 1
    if i == len(DAYS) - 1:
        return LVL[-1]
    a, b = DAYS[i], DAYS[i + 1]
    w = (d - a).days / (b - a).days
    return LVL[i] * (LVL[i + 1] / LVL[i]) ** w


def infl(a: date, b: date) -> float | None:
    x, y = cpi(a), cpi(b)
    return None if x is None or y is None else y / x - 1


def real(nominal: float, a: date, b: date) -> float | None:
    i = infl(a, b)
    return None if i is None else (1 + nominal) / (1 + i) - 1


def add_months(d: date, m: int) -> date:
    y, mo = divmod(d.month - 1 + m, 12)
    day = min(d.day, 28)
    return date(d.year + y, mo + 1, day)


def index_windows(series: list[tuple[date, float]], since: date) -> dict[str, Any]:
    ds = [d for d, _ in series]
    out: dict[str, Any] = {}
    for m in MONTHS:
        res = []
        for i, (d, v) in enumerate(series):
            if d < since:
                continue
            j = bisect_right(ds, add_months(d, m)) - 1
            if j <= i or ds[j] < add_months(d, m) - timedelta(days=7):
                continue
            r = real(series[j][1] / v - 1, d, ds[j])
            if r is not None:
                res.append((d, r))
        if not res:
            continue
        split = res[len(res) // 2][0]

        def blk(x: list[tuple[date, float]]) -> dict[str, Any]:
            v = [r for _, r in x]
            return {"n": len(v), "ahead": sum(r > 0 for r in v) / len(v), "median_real": median(v)}

        out[str(m)] = {
            **blk(res),
            "split": str(split),
            "halves": [
                blk([x for x in res if x[0] < split]),
                blk([x for x in res if x[0] >= split]),
            ],
        }
    return out


def main() -> None:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
        idx = {
            code: sorted(
                (r.date, float(r.close))
                for r in s.query(MarketIndexDaily).filter(MarketIndexDaily.index_code == code)
                if r.close
            )
            for code in (TOTAL, EQUAL)
        }
    panel = tp.build_panel(prices, clients)
    as_of: date = panel["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    rc = cfg.v2.trend_ride
    since = as_of.replace(year=as_of.year - 3)

    out: dict[str, Any] = {
        "as_of": str(as_of),
        "cpi_last": str(DAYS[-1]),
        "round_trip_cost": cost,
        "inflation": {
            "3y": infl(since, DAYS[-1]),
            "per_year_3y": (1 + infl(since, DAYS[-1])) ** (365.25 / (DAYS[-1] - since).days) - 1,  # type: ignore[operator]
            "last_12m": infl(DAYS[-1] - timedelta(days=365), DAYS[-1]),
        },
        "index": {
            "total": index_windows(idx[TOTAL], date(2020, 3, 20)),
            "equal": index_windows(idx[EQUAL], date(2020, 3, 20)),
            "total_3y": index_windows(idx[TOTAL], since),
            "equal_3y": index_windows(idx[EQUAL], since),
        },
    }

    # trend-ride trades, as the stock page's history counts them
    by_symbol = tr.all_rides(panel, rc.near_high, rc.trail, rc.max_hold_days)
    trades = []
    timing: list[dict[str, Any]] = []
    for g, rs in by_symbol.values():
        d, c, liq = g["date"].to_list(), g["close"].to_numpy(), g["liquid"].to_numpy()
        for r in rs:
            if r.entry is None or not liq[r.signal] or d[r.entry] < since:
                continue
            end = len(d) - 1 if r.exit is None else r.exit
            net = float(c[end] / c[r.entry] - 1 - cost)
            rr = real(net, d[r.entry], min(d[end], DAYS[-1]))
            if rr is None:
                continue
            trades.append(
                {
                    "entry": d[r.entry],
                    "end": d[end],
                    "days": end - r.entry,
                    "cal_days": (d[end] - d[r.entry]).days,
                    "net": net,
                    "real": rr,
                    "open": r.exit is None,
                }
            )
            if r.exit is not None and r.peak is not None:
                lo = max(0, r.signal - 250)
                trough = int(lo + c[lo : r.signal + 1].argmin())
                after = c[r.exit : min(len(c), r.exit + 61)]
                timing.append(
                    {
                        "entry": d[r.entry],
                        "above_trough": float(c[r.entry] / c[trough] - 1),
                        "days_from_trough": r.entry - trough,
                        "peak_gain": float(c[r.peak] / c[r.entry] - 1),
                        "given_back": float(1 - c[r.exit] / c[r.peak]),
                        "rise_60d_after_exit": float(after.max() / c[r.exit] - 1),
                        "fall_60d_after_exit": float(1 - after.min() / c[r.exit]),
                        "net": net,
                    }
                )
    trades.sort(key=lambda t: t["entry"])
    split = trades[len(trades) // 2]["entry"]

    def tblk(x: list[dict[str, Any]]) -> dict[str, Any]:
        if not x:
            return {"n": 0}
        return {
            "n": len(x),
            "open": sum(t["open"] for t in x),
            "nominal_win": sum(t["net"] > 0 for t in x) / len(x),
            "real_win": sum(t["real"] > 0 for t in x) / len(x),
            "nominal_gain_real_loss": sum(t["net"] > 0 >= t["real"] for t in x) / len(x),
            "median_net": median(t["net"] for t in x),
            "median_real": median(t["real"] for t in x),
            "median_cal_days": median(t["cal_days"] for t in x),
        }

    buckets = [(0, 30), (30, 90), (90, 180), (180, 400)]
    closed = [t for t in trades if not t["open"]]
    out["trades"] = {
        "all": tblk(trades),
        "closed": tblk(closed),
        "split": str(split),
        "halves": [
            tblk([t for t in trades if t["entry"] < split]),
            tblk([t for t in trades if t["entry"] >= split]),
        ],
        "by_hold_cal_days": {
            f"{a}-{b}": tblk([t for t in closed if a <= t["cal_days"] < b]) for a, b in buckets
        },
    }

    # part (c): where the marks sit against the trough before and the top after
    def q(v: list[float]) -> dict[str, float]:
        v = sorted(v)
        return {
            k: v[int(p * (len(v) - 1))] for k, p in (("p25", 0.25), ("median", 0.5), ("p75", 0.75))
        }

    tsplit = timing[len(timing) // 2]["entry"] if timing else None
    out["timing"] = {
        "n": len(timing),
        **{
            k: q([t[k] for t in timing])
            for k in (
                "above_trough",
                "days_from_trough",
                "peak_gain",
                "given_back",
                "rise_60d_after_exit",
                "fall_60d_after_exit",
            )
        },
        "share_given_back_over_half_of_gain": sum(
            t["peak_gain"] > 0 and (t["given_back"] * (1 + t["peak_gain"])) > t["peak_gain"] / 2
            for t in timing
        )
        / max(1, len(timing)),
        "share_rose_20pct_after_exit": sum(t["rise_60d_after_exit"] > 0.2 for t in timing)
        / max(1, len(timing)),
        "share_fell_10pct_after_exit": sum(t["fall_60d_after_exit"] > 0.1 for t in timing)
        / max(1, len(timing)),
        "split": str(tsplit),
        "halves_median_given_back": [
            median([t["given_back"] for t in timing if t["entry"] < tsplit] or [0]),
            median([t["given_back"] for t in timing if t["entry"] >= tsplit] or [0]),
        ],
    }

    # one slot, chained trades; open trades end at the last close
    days = sorted(set(panel["date"].to_list()))
    pos = {d: i for i, d in enumerate(days)}
    starts: dict[int, list[dict[str, Any]]] = {}
    for t in trades:
        starts.setdefault(pos[t["entry"]], []).append(t)
    rng = random.Random(7)

    def path(first: int) -> list[tuple[int, date, float]]:
        """(trades so far, day, compound net) after each sale."""
        i, acc, n, out_p = first, 1.0, 0, []
        while True:
            pool = [t for k in range(i, min(i + NEXT_WINDOW, len(days))) for t in starts.get(k, [])]
            if not pool:
                return out_p
            t = rng.choice(pool)
            acc *= 1 + t["net"]
            n += 1
            out_p.append((n, t["end"], acc))
            if t["open"]:
                return out_p
            i = pos[t["end"]] + 1

    since_i = pos[min(d for d in days if d >= since)]
    split_i = pos[min(d for d in days if d >= split)]
    chains: dict[str, Any] = {}
    for name, lo, hi in (
        ("first_half", since_i, split_i),
        ("second_half", split_i, len(days) - 60),
    ):
        after: dict[int, list[tuple[float, int]]] = {}
        for _ in range(PATHS):
            first = rng.randrange(lo, hi)
            for n, end, acc in path(first):
                rr = real(acc - 1, days[first], min(end, DAYS[-1]))
                if rr is not None and n <= 10:
                    after.setdefault(n, []).append((rr, (end - days[first]).days))
        chains[name] = {
            str(n): {
                "paths": len(v),
                "ahead": sum(r > 0 for r, _ in v) / len(v),
                "median_real": median(r for r, _ in v),
                "median_cal_days": median(d for _, d in v),
            }
            for n, v in sorted(after.items())
            if len(v) >= 100
        }
    out["chains"] = chains

    # other trailing distances, same entries, against inflation (exits were compared on excess
    # return in docs/reports/trend-ride-2026-11.md; this asks only which beats inflation)
    sweep = {}
    for trail in (0.15, 0.20, 0.25, 0.30, 0.35):
        rows = []
        for g, rs in tr.all_rides(panel, rc.near_high, trail, rc.max_hold_days).values():
            d, c, liq = g["date"].to_list(), g["close"].to_numpy(), g["liquid"].to_numpy()
            for r in rs:
                if r.entry is None or not liq[r.signal] or d[r.entry] < since:
                    continue
                end = len(d) - 1 if r.exit is None else r.exit
                net = float(c[end] / c[r.entry] - 1 - cost)
                rr = real(net, d[r.entry], min(d[end], DAYS[-1]))
                if rr is not None:
                    rows.append(
                        {
                            "entry": d[r.entry],
                            "end": d[end],
                            "net": net,
                            "real": rr,
                            "open": r.exit is None,
                            "cal_days": (d[end] - d[r.entry]).days,
                        }
                    )
        sweep[str(trail)] = {
            "all": tblk(rows),
            "halves": [
                tblk([t for t in rows if t["entry"] < split]),
                tblk([t for t in rows if t["entry"] >= split]),
            ],
        }
    out["trail_sweep"] = sweep

    # the ADR 0004 portfolio study against the same inflation
    inv = json.loads((ROOT / "docs" / "data" / "invested-study.json").read_text(encoding="utf-8"))
    w = inv["windows"]["full"]
    a, b = date.fromisoformat(w["first"]), date.fromisoformat(w["last"])
    i_full = infl(a, min(b, DAYS[-1]))
    yrs = (min(b, DAYS[-1]) - a).days / 365.25
    ann_infl = (1 + i_full) ** (1 / yrs) - 1 if i_full is not None else None
    out["invested_study"] = {
        "first": str(a),
        "last": str(b),
        "inflation_per_year": ann_infl,
        "configs": {
            k: {
                "ann": v["base"]["ann"],
                "real_ann": (1 + v["base"]["ann"]) / (1 + ann_infl) - 1 if ann_infl else None,
            }
            for k, v in inv["configs"].items()
        },
        "refs": {
            k: {
                "ann": v["ann"],
                "real_ann": (1 + v["ann"]) / (1 + ann_infl) - 1 if ann_infl else None,
            }
            for k, v in inv["refs"]["full"].items()
            if isinstance(v, dict) and "ann" in v
        },
    }

    path_out = HERE / "results_inflation_hurdle.json"
    path_out.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
