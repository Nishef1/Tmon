"""Ride a trend: an entry at the start of a move and a trailing exit, against random entries
with the same exit.  (docs/reports/trend-ride-2026-11.md)

Question from the owner: a stock like درازک went +477% in 265 days; can we hint the entry near the
start of such a move and the exit near its top?

Universe: point-in-time top 100 by 20-day median traded value (universe.pit_members), entries in
the last three years. A signal on day t (a member that day) buys at the close of t+1; the signal is
dropped when t+1 is locked up (a buy queue). One open trade per stock and rule pair: a signal while
a trade is open is ignored. An exit rule is checked on each close; the sale is at the next close,
and while that day is locked down (a sell queue) the sale moves to the following day. Every trade
also ends after 250 trading days. A trade still open on the last day is closed at the last close
and counted as censored. Prices are adjusted. Net = gross - 1.75% round trip. Excess = net minus
the equal-weight mean of the day's 100 names over the same days. The null for each exit is the same
exit after random member days (several seeds). Halves split the entry dates in two. The t-statistic
is on monthly means of the excess (trades of one month overlap).
Run from backend/ with the live env:  python research/market_method/trend_ride.py
TREND_TOP=300 widens the universe to the 300 most traded, TREND_START moves the first entry date
and TREND_WAIT=1 waits through a buy queue; each adds a suffix to the output name.
Output: results_trend_ride.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

import universe as uv  # noqa: E402
from fundamentals_study import DB  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
COST = 0.0175
MAX_HOLD = 250
START = date.fromisoformat(os.environ.get("TREND_START", "2023-11-01"))
# 1: a buy queue on t+1 delays the buy to the first day without one (up to 20 days)
WAIT = os.environ.get("TREND_WAIT", "0") == "1"
SEEDS = 5
RANDOM_P = 0.02
TOP = int(os.environ.get("TREND_TOP", "100"))
TAG = ("" if TOP == 100 else f"_top{TOP}") + (
    f"_{START.year}" if "TREND_START" in os.environ else ""
)
OUT = HERE / f"results_trend_ride{TAG}{'_wait' if WAIT else ''}.json"
WATCH = ("درازک", "شکام", "دزاگرس", "شبهرن")

ENTRIES = ("brk60", "brk250", "base_brk", "sma50_cross", "trend_high", "rsi30")
EXITS = ("chand3", "chand5", "sma20", "sma50", "trail15", "trail25", "fixed60", "fixed120")


def load() -> tuple[pl.DataFrame, dict[int, str]]:
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    ids = uv.stock_ids(DB)
    mem = uv.pit_members(prices, ids, top=TOP).with_columns(member=pl.lit(True))
    p = (
        apply_adjustments(prices)
        .filter(C(G).is_in(list(ids)) & ~C("market_halt") & (C("close") > 0))
        .with_columns(C("date").cast(pl.Date))
        .sort(G, "date")
        .join(mem, on=["date", G], how="left")
        .with_columns(C("member").fill_null(False))
    )
    c = C("adj_close")
    p = p.with_columns(
        ret=(c / c.shift(1) - 1).over(G),
        locked=C("adj_high") == C("adj_low"),
        tr=pl.max_horizontal(
            C("adj_high") - C("adj_low"),
            (C("adj_high") - c.shift(1)).abs(),
            (C("adj_low") - c.shift(1)).abs(),
        ).over(G),
    )
    return p, ids


def market_index(p: pl.DataFrame) -> tuple[dict[date, int], np.ndarray, list[date]]:
    """Level of the equal-weight index of the day's members (daily returns clipped at +-30%)."""
    d = (
        p.filter(C("member") & C("ret").is_not_null())
        .group_by("date")
        .agg(r=C("ret").clip(-0.3, 0.3).mean())
        .sort("date")
    )
    days = d["date"].to_list()
    lvl = np.cumprod(1 + d["r"].to_numpy())
    return {x: i for i, x in enumerate(days)}, lvl, days


def roll_max_prev(x: np.ndarray, n: int) -> np.ndarray:
    """max of x[t-n..t-1]; NaN until n values exist."""
    out = np.full_like(x, np.nan)
    if len(x) > n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)[:-1]
        out[n:] = w.max(axis=1)
    return out


def roll_min_prev(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    if len(x) > n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)[:-1]
        out[n:] = w.min(axis=1)
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1 :] = (cs[n:] - cs[:-n]) / n
    return out


def ema(x: np.ndarray, alpha: float) -> np.ndarray:
    out = np.empty_like(x)
    acc = np.nan
    for i, v in enumerate(x):
        acc = v if np.isnan(acc) else acc + alpha * (v - acc)
        out[i] = acc
    return out


def signals(c: np.ndarray, ret: np.ndarray, tr: np.ndarray) -> dict[str, np.ndarray]:
    hi60, lo60 = roll_max_prev(c, 60), roll_min_prev(c, 60)
    hi250 = roll_max_prev(c, 250)
    s50, s200 = sma(c, 50), sma(c, 200)
    r = np.nan_to_num(ret)
    au, ad = ema(np.clip(r, 0, None), 1 / 14), ema(np.clip(-r, 0, None), 1 / 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + au / ad)
    rsi[:15] = np.nan

    def fresh(cond: np.ndarray) -> np.ndarray:
        prev = np.concatenate([[True], cond[:-1]])
        return cond & ~prev

    with np.errstate(invalid="ignore"):
        brk60 = c > hi60
        brk250 = c > hi250
        base = (hi60 / lo60 - 1) < 0.25
        s50_up = s50 > np.concatenate([np.full(10, np.nan), s50[:-10]])
        above = c > s50
        trend = (c > s50) & (s50 > s200) & (c >= 0.95 * hi250)
        rsi_prev = np.concatenate([[np.nan], rsi[:-1]])
    return {
        "brk60": fresh(brk60),
        "brk250": fresh(brk250),
        "base_brk": fresh(brk60) & base,
        "sma50_cross": fresh(above) & s50_up,
        "trend_high": fresh(trend),
        "rsi30": (rsi_prev < 30) & (rsi >= 30),
    }


def exit_lines(c: np.ndarray, tr: np.ndarray) -> dict[str, np.ndarray]:
    return {"atr": sma(tr, 22), "sma20": sma(c, 20), "sma50": sma(c, 50)}


def simulate(
    t_sig: np.ndarray,
    rule: str,
    c: np.ndarray,
    ret: np.ndarray,
    locked: np.ndarray,
    lines: dict[str, np.ndarray],
) -> list[tuple[int, int, bool, float]]:
    """(entry index, exit index, censored, peak close / entry - 1) per trade."""
    n = len(c)
    out = []
    busy_until = -1
    for t in t_sig:
        e = t + 1
        if t <= busy_until or e >= n:
            continue
        if WAIT:
            while e < min(n - 1, t + 21) and locked[e] and ret[e] > 0:
                e += 1
        if locked[e] and ret[e] > 0:
            continue
        peak = c[e]
        x = -1
        for j in range(e + 1, n):
            peak = max(peak, c[j])
            held = j - e
            hit = held >= MAX_HOLD
            if rule == "chand3":
                hit |= c[j] < peak - 3 * lines["atr"][j]
            elif rule == "chand5":
                hit |= c[j] < peak - 5 * lines["atr"][j]
            elif rule == "sma20":
                hit |= c[j] < lines["sma20"][j]
            elif rule == "sma50":
                hit |= c[j] < lines["sma50"][j]
            elif rule == "trail15":
                hit |= c[j] < 0.85 * peak
            elif rule == "trail25":
                hit |= c[j] < 0.75 * peak
            elif rule == "fixed60":
                hit |= held >= 60
            elif rule == "fixed120":
                hit |= held >= 120
            if hit:
                x = j + 1
                while x < n and locked[x] and ret[x] < 0:
                    x += 1
                break
        censored = x < 0 or x >= n
        if censored:
            x = n - 1
        out.append((e, x, censored, float(c[e : x + 1].max() / c[e] - 1)))
        busy_until = x
    return out


def summarize(rows: pl.DataFrame, mid: date) -> dict[str, object]:
    if rows.height == 0:
        return {"n": 0}

    def half(d: pl.DataFrame) -> float | None:
        return round(float(d["excess"].mean()), 4) if d.height else None

    monthly = (
        rows.group_by(C("entry").dt.truncate("1mo")).agg(C("excess").mean())["excess"].to_numpy()
    )
    t = (
        float(monthly.mean() / (monthly.std(ddof=1) / np.sqrt(len(monthly))))
        if len(monthly) > 2
        else None
    )
    big = rows.filter(C("runup") >= 0.5)
    return {
        "n": rows.height,
        "net": round(float(rows["net"].mean()), 4),
        "net_median": round(float(rows["net"].median()), 4),  # type: ignore[arg-type]
        "excess": round(float(rows["excess"].mean()), 4),
        "excess_h1": half(rows.filter(C("entry") < mid)),
        "excess_h2": half(rows.filter(C("entry") >= mid)),
        "win": round(float((rows["net"] > 0).mean()), 3),
        "hold": round(float(rows["hold"].mean()), 1),
        "censored": int(rows["censored"].sum()),
        "t_monthly": round(t, 2) if t is not None else None,
        "months": len(monthly),
        "share_runup50": round(big.height / rows.height, 3),
        "kept_of_runup": round(float((big["gross"] / big["runup"]).median()), 3)
        if big.height
        else None,  # type: ignore[arg-type]
    }


def paired(df: pl.DataFrame, rnd: pl.DataFrame, mid: date) -> dict[str, object]:
    """Excess over random entries month by month (t over months), and on closed trades only."""

    def monthly(d: pl.DataFrame) -> pl.DataFrame:
        return d.group_by(m=C("entry").dt.truncate("1mo")).agg(x=C("excess").mean())

    j = monthly(df).join(monthly(rnd), on="m", suffix="_r").with_columns(d=C("x") - C("x_r"))
    dd = j["d"].to_numpy()
    t = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))) if len(dd) > 2 else None
    closed, rclosed = df.filter(~C("censored")), rnd.filter(~C("censored"))
    out: dict[str, object] = {
        "vs_random_t": round(t, 2) if t is not None else None,
        "months_better": round(float((dd > 0).mean()), 3),
        "closed_n": closed.height,
    }
    if closed.height and rclosed.height:
        out["closed_vs_random"] = round(
            float(closed["excess"].mean() - rclosed["excess"].mean()), 4
        )
        for name, f in (("h1", C("entry") < mid), ("h2", C("entry") >= mid)):
            a, b = closed.filter(f), rclosed.filter(f)
            if a.height and b.height:
                out[f"closed_vs_random_{name}"] = round(
                    float(a["excess"].mean() - b["excess"].mean()), 4
                )
    return out


SHOWN = ("n", "excess", "excess_h1", "excess_h2", "vs_random", "vs_random_h1", "vs_random_h2")
SHOWN2 = ("vs_random_t", "closed_vs_random", "closed_vs_random_h1", "closed_vs_random_h2", "hold")


def show(name: str, st: dict[str, object]) -> None:
    print(name, *(f"{k}={st.get(k)}" for k in SHOWN + SHOWN2), flush=True)


def main() -> None:
    p, ids = load()
    pos, lvl, days = market_index(p)
    last = days[-1]
    mid = START + (last - START) / 2
    rng = np.random.default_rng(7)
    trades: dict[tuple[str, str], list[dict[str, object]]] = {}
    for (iid,), g in p.group_by([G], maintain_order=True):
        c = g["adj_close"].to_numpy().astype(float)
        if len(c) < 300:
            continue
        ret = g["ret"].fill_null(0.0).to_numpy()
        locked = g["locked"].to_numpy()
        tr = g["tr"].fill_null(0.0).to_numpy().astype(float)
        dts = g["date"].to_list()
        member = g["member"].to_numpy()
        live = member & (np.array(dts) >= START)
        sig = signals(c, ret, tr)
        lines = exit_lines(c, tr)
        sets = {k: np.flatnonzero(v & live) for k, v in sig.items()}
        for s in range(SEEDS):
            sets[f"random{s}"] = np.flatnonzero(live & (rng.random(len(c)) < RANDOM_P))
        for ent, t_sig in sets.items():
            for rule in EXITS:
                for e, x, cens, runup in simulate(t_sig, rule, c, ret, locked, lines):
                    if dts[e] not in pos or dts[x] not in pos:
                        continue
                    gross = c[x] / c[e] - 1
                    mkt = lvl[pos[dts[x]]] / lvl[pos[dts[e]]] - 1
                    trades.setdefault((ent, rule), []).append(
                        {
                            "sym": ids[iid],
                            "entry": dts[e],
                            "exit": dts[x],
                            "gross": gross,
                            "net": gross - COST,
                            "excess": gross - COST - mkt,
                            "hold": x - e,
                            "censored": cens,
                            "runup": runup,
                        }
                    )
    res: dict[str, object] = {"start": str(START), "last": str(last), "mid": str(mid), "cost": COST}
    table: dict[str, dict[str, object]] = {}
    for rule in EXITS:
        rnd = pl.concat([pl.DataFrame(trades[(f"random{s}", rule)]) for s in range(SEEDS)])
        base = summarize(rnd, mid)
        base["n"] = rnd.height // SEEDS
        table[f"random|{rule}"] = base
        for ent in ENTRIES:
            df = pl.DataFrame(trades.get((ent, rule), []))
            st = summarize(df, mid)
            if st["n"]:
                st["vs_random"] = round(float(st["excess"]) - float(base["excess"]), 4)  # type: ignore[arg-type]
                st["vs_random_h1"] = round(float(st["excess_h1"]) - float(base["excess_h1"]), 4)  # type: ignore[arg-type]
                st["vs_random_h2"] = round(float(st["excess_h2"]) - float(base["excess_h2"]), 4)  # type: ignore[arg-type]
            if st["n"]:
                st.update(paired(df, rnd, mid))
            table[f"{ent}|{rule}"] = st
            show(f"{ent} {rule}", st)
        show(f"random {rule}", base)
    res["table"] = table
    watch: dict[str, list[dict[str, object]]] = {}
    for (ent, rule), rows in trades.items():
        if ent.startswith("random"):
            continue
        for r in rows:
            if r["sym"] in WATCH:
                watch.setdefault(str(r["sym"]), []).append(
                    {
                        "rule": f"{ent}|{rule}",
                        "entry": str(r["entry"]),
                        "exit": str(r["exit"]),
                        "net": round(float(r["net"]), 3),  # type: ignore[arg-type]
                        "runup": round(float(r["runup"]), 3),  # type: ignore[arg-type]
                        "censored": r["censored"],
                    }
                )
    res["watch"] = watch
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
