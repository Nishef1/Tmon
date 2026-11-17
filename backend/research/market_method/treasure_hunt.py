"""Wide search for entry rules in the liquid basket, judged out of sample at three bars.
(docs/reports/treasure-hunt-2026-11.md)

Features per stock and day use only data up to that day: drawdown from the all-time and 250-day
peak, drawdown over the stock's own usual depth (median of past episodes deeper than 20%), days
since the peak, returns over 5/20/60/120 days, volatility and its 20/120 ratio, traded value 5/60,
position in the 60-day range, gap to the 60-day mean, individuals' per-capita buy/sell power and net
individual flow (5 and 20 days), down days of the last 10, 20-day return over the stock's sector.
Market state: basket drawdown, basket 20-day return, share of stocks above their 60-day mean.

Target: excess over the basket mean of the H-day return (H = 20, or the first argument), entry at
the close of t+1, cost 1.75% round trip; a day whose next session is a one-price buy queue
(high = low, up) cannot be entered.

Rules: each stock feature in cross-sectional quintiles, market features in terciles with edges from
A only; every single bin and every pair of bins. Periods: O 2019-01 to 2023-03, A 2023-04 to
2024-12, B 2025-01 to the end. Discovery scores each rule on O and A and keeps the weaker t; B is
the holdout. Three bars on the 40 best:
  lenient  holdout mean > 0
  medium   A and B both > 0, holdout t > 2 (t on non-overlapping H-day means, at least 6 of
           them), >= 55% good periods
  strict   medium, also > 0 on O, holdout t above 3 (Bonferroni for 40 rules), and the 10-stock
           portfolio beats the basket after costs in B
Survivors go into a monthly portfolio (up to 10 names, equal weight, renewed every 20 trading days)
and a 100-million account with a 10-million withdrawal every 20 days.
Run from backend/ with the live env:  python research/market_method/treasure_hunt.py
Output: results_treasure_hunt.json
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fundamentals_study import BASKET

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175
H = int(sys.argv[1]) if len(sys.argv) > 1 else 20
CASH = 0.02 * H / 20  # assumed bank deposit return per period (about 27% a year), untested
A0, B0, END_O = "2023-04-01", "2025-01-01", "2023-04-01"
O0 = "2019-01-01"
TOP_FROM_A = 40
MIN_MEMBERS = 3

STOCK = [
    "dd", "dd250", "ddr", "since_peak", "r5", "r20", "r60", "r120", "vol20", "volr", "valr",
    "pos60", "gap60", "pow5", "pow20", "net5", "net20", "down10", "sec_r20",
]  # fmt: skip
MARKET = ["m_dd", "m_r20", "breadth"]


def usual_depth(close: np.ndarray) -> np.ndarray:
    """Median depth of completed episodes (< -20%) known on each day; NaN before two exist."""
    out = np.full(len(close), np.nan)
    done: list[float] = []
    peak, low = close[0], close[0]
    for i in range(1, len(close)):
        if close[i] > peak:
            d = low / peak - 1
            if d <= -0.20:
                done.append(d)
            peak = low = close[i]
        elif close[i] < low:
            low = close[i]
        if len(done) >= 2:
            out[i] = float(np.median(done))
    return out


def basket_ids() -> dict[int, str]:
    import sqlite3

    from fundamentals_study import DB

    syms = json.loads(BASKET.read_text(encoding="utf-8"))["symbols"]
    ids: dict[int, str] = {}
    for iid, sym in sqlite3.connect(DB, uri=True).execute(
        "select id, symbol_fa from instruments where instrument_type='stock' order by id"
    ):
        if sym in syms and sym not in ids.values():
            ids[iid] = sym
    return ids


def panel(drop_queue: bool = True) -> tuple[pl.DataFrame, dict[int, str]]:
    ids = basket_ids()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
    a = apply_adjustments(prices).filter((C("close") > 0) & C(G).is_in(list(ids)))
    a = a.with_columns(C("date").cast(pl.Date)).sort(G, "date")
    cl = clients.with_columns(C("date").cast(pl.Date)).select(
        G, "date", "buy_count_i", "sell_count_i", "buy_volume_i", "sell_volume_i"
    )
    a = a.join(cl, on=[G, "date"], how="left").join(sectors, on=G, how="left")
    parts = []
    for (_iid,), g in a.group_by(G, maintain_order=True):
        parts.append(g.with_columns(usual=pl.Series(usual_depth(g["adj_close"].to_numpy()))))
    a = pl.concat(parts)
    c = C("adj_close")
    ret = c / c.shift(1) - 1
    bpc = C("buy_volume_i") / C("buy_count_i")
    spc = C("sell_volume_i") / C("sell_count_i")
    a = a.with_columns(
        ret=ret.over(G),
        peak=c.cum_max().over(G),
        dd250=(c / c.rolling_max(250, min_samples=60) - 1).over(G),
        r5=(c / c.shift(5) - 1).over(G),
        r20=(c / c.shift(20) - 1).over(G),
        r60=(c / c.shift(60) - 1).over(G),
        r120=(c / c.shift(120) - 1).over(G),
        vol20=ret.rolling_std(20).over(G),
        vol120=ret.rolling_std(120).over(G),
        valr=(C("value").rolling_mean(5) / C("value").rolling_mean(60)).over(G),
        pos60=((c - c.rolling_min(60)) / (c.rolling_max(60) - c.rolling_min(60) + 1e-9)).over(G),
        gap60=(c / c.rolling_mean(60) - 1).over(G),
        pow_d=pl.when((bpc > 0) & (spc > 0)).then((bpc / spc).log()),
        net_d=(C("buy_volume_i") - C("sell_volume_i")) / (C("volume") + 1),
        f20=(c.shift(-H - 1) / c.shift(-1) - 1 - COST).over(G),  # H-day return
        queue_next=(
            (C("high").shift(-1) == C("low").shift(-1)) & (C("close").shift(-1) > C("close"))
        ).over(G),
        # rolling counts of a peak date: index since the running max was set
        is_peak=(c >= c.cum_max()).over(G),
    )
    a = a.with_columns(
        dd=C("adj_close") / C("peak") - 1,
        volr=C("vol20") / C("vol120"),
        pow5=C("pow_d").fill_nan(None).rolling_mean(5, min_samples=3).over(G),
        pow20=C("pow_d").fill_nan(None).rolling_mean(20, min_samples=10).over(G),
        net5=C("net_d").rolling_mean(5, min_samples=3).over(G),
        net20=C("net_d").rolling_mean(20, min_samples=10).over(G),
        down10=(C("ret") < 0).cast(pl.Int8).rolling_sum(10).over(G),
        n=pl.int_range(pl.len()).over(G),
    )
    a = a.with_columns(
        last_peak=pl.when(C("is_peak")).then(C("n")).forward_fill().over(G),
    ).with_columns(since_peak=C("n") - C("last_peak"))
    a = a.with_columns(ddr=pl.when(C("usual") < 0).then(C("dd") / C("usual")))
    a = a.filter(C("date") >= pl.date(2018, 1, 1))
    # market: equal-weight basket index
    m = (
        a.group_by("date")
        .agg(m_ret=C("ret").clip(-0.15, 0.15).mean(), breadth=(C("gap60") > 0).mean())
        .sort("date")
        .with_columns(m_idx=(1 + C("m_ret")).cum_prod())
        .with_columns(
            m_dd=C("m_idx") / C("m_idx").cum_max() - 1,
            m_r20=C("m_idx") / C("m_idx").shift(20) - 1,
        )
    )
    a = a.join(m.select("date", "m_dd", "m_r20", "breadth"), on="date", how="left")
    a = a.with_columns(
        rel_dd=C("dd") - C("dd").mean().over("date"),
        rel_r20=C("r20") - C("m_r20"),
        sec_r20=C("r20") - C("r20").mean().over("date", "sector_code"),
    )
    a = a.filter(C("date") >= pl.date(2019, 1, 1))
    a = a.filter(C("f20").is_not_null()) if drop_queue else a
    a = a.with_columns(x=C("f20") - C("f20").mean().over("date"))
    for f in STOCK:
        a = a.with_columns(
            ((C(f).rank("average").over("date") - 1) / (C(f).count().over("date") - 1) * 5)
            .floor()
            .clip(0, 4)
            .cast(pl.Int8)
            .alias("q_" + f)
        )
    disc = a.filter((C("date") >= pl.date(2023, 4, 1)) & (C("date") < pl.date(2025, 1, 1)))
    for f in MARKET:
        lo, hi = disc[f].quantile(1 / 3), disc[f].quantile(2 / 3)
        a = a.with_columns(
            pl.when(C(f) <= lo).then(0).when(C(f) <= hi).then(1).otherwise(2).cast(pl.Int8)
            .alias("q_" + f)
        )  # fmt: skip
    a = a.with_columns(
        half=pl.when(C("date") < pl.date(2023, 4, 1))
        .then(pl.lit("O"))
        .when(C("date") < pl.date(2025, 1, 1))
        .then(pl.lit("A"))
        .otherwise(pl.lit("B"))
    )
    return (a.filter(~C("queue_next")) if drop_queue else a), ids


def block_stats(daily: pl.DataFrame) -> dict:
    """daily: date, v (mean excess of members). t on 20-day non-overlapping blocks."""
    if daily.height == 0:
        return {"mean": None, "t": None, "n": 0, "good": None}
    d = daily.sort("date").with_row_index("k").with_columns(blk=C("k") // H)
    b = d.group_by("blk").agg(v=C("v").mean())["v"].to_numpy()
    mean = float(d["v"].mean())
    t = (
        float(b.mean() / (b.std(ddof=1) / math.sqrt(len(b))))
        if len(b) > 2 and b.std() > 0
        else None
    )
    return {"mean": mean, "t": t, "n": d.height, "blocks": len(b), "good": float((b > 0).mean())}


def evaluate(a: pl.DataFrame, cond: pl.Expr) -> dict:
    s = a.filter(cond)
    daily = (
        s.group_by("half", "date").agg(v=C("x").mean(), k=pl.len()).filter(C("k") >= MIN_MEMBERS)
    )
    out = {}
    for h in ("O", "A", "B"):
        out[h] = block_stats(daily.filter(C("half") == h).select("date", "v"))
    return out


def discover(a: pl.DataFrame) -> list[dict]:
    """Score every rule on O and on A separately; the score is the weaker t of the two.
    B is never looked at here."""
    qs = ["q_" + f for f in STOCK + MARKET]
    rows: list[dict] = []

    def score(keys: list[str]) -> None:
        per: dict[str, dict] = {}
        for h in ("O", "A"):
            g = (
                a.filter(C("half") == h)
                .group_by(*keys, "date")
                .agg(v=C("x").mean(), k=pl.len())
                .filter(C("k") >= MIN_MEMBERS)
                .with_columns(blk=(C("date").rank("dense") - 1) // H)
            )
            b = g.group_by(*keys, "blk").agg(v=C("v").mean())
            s = b.group_by(*keys).agg(m=C("v").mean(), sd=C("v").std(), nb=pl.len())
            for r in s.iter_rows(named=True):
                if r["nb"] < 6 or not r["sd"]:
                    continue
                key = tuple(r[k] for k in keys)
                per.setdefault(key, {})[h] = (r["m"], r["m"] / (r["sd"] / math.sqrt(r["nb"])))
        for key, v in per.items():
            if len(v) < 2:
                continue
            rows.append(
                {"rule": " & ".join(f"{k}={b}" for k, b in zip(keys, key, strict=True)),
                 "keys": dict(zip(keys, key, strict=True)),
                 "O_t": v["O"][1], "A_t": v["A"][1], "score": min(v["O"][1], v["A"][1])}
            )  # fmt: skip

    for q in qs:
        score([q])
    for q1, q2 in itertools.combinations(qs, 2):
        if q1[2:] in MARKET and q2[2:] in MARKET:
            continue
        score([q1, q2])
    return rows


def expr(keys: dict) -> pl.Expr:
    e = pl.lit(True)
    for k, v in keys.items():
        e = e & (C(k) == v)
    return e


def portfolio(a: pl.DataFrame, cond: pl.Expr, start: str, rank_by: str = "x") -> list[dict]:
    """Every 20 trading days from start: up to 10 members (lowest q_vol20 first, a fixed tie rule),
    equal weight, hold 20 days. Returns per-period absolute and basket returns (after cost)."""
    d = a.filter(C("date") >= pl.lit(start).str.to_date())
    days = d["date"].unique().sort().to_list()[::H]
    base = d.group_by("date").agg(bm=C("f20").mean())
    picks = (
        d.filter(C("date").is_in(days) & cond)
        .sort("date", "valr")
        .group_by("date", maintain_order=True)
        .head(10)
        .group_by("date")
        .agg(r=C("f20").mean(), k=pl.len())
    )
    out = (
        pl.DataFrame({"date": days})
        .join(picks, on="date", how="left")
        .join(base, on="date", how="left")
        .with_columns(r=C("r").fill_null(0.0), k=C("k").fill_null(0))
        .sort("date")
    )
    return out.to_dicts()


def account(periods: list[float], take: float, cap: float = 100.0) -> dict:
    """100 million, `take` million out every period (sold with the 1.13% sell cost)."""
    path = []
    for r in periods:
        cap *= 1 + r
        cap -= take * H / 20 * 1.0113
        path.append(cap)
        if cap <= 0:
            break
    return {"end": round(path[-1], 1), "months": len(path), "broke": path[-1] <= 0}


def main() -> None:
    a, _ids = panel()
    print("rows", a.height, "dates", a["date"].n_unique())
    disc = discover(a)
    disc.sort(key=lambda r: -r["score"])
    n_tests = len(disc)
    top = disc[:TOP_FROM_A]
    bonf = 3.0  # two-sided ~0.05 / 40 rules
    res = []
    for r in top:
        ev = evaluate(a, expr(r["keys"]))
        res.append({**r, **ev})
    # lenient, medium, strict
    for r in res:
        ha, hb, ho = r["A"], r["B"], r["O"]
        r["lenient"] = (hb["mean"] or -1) > 0
        r["medium"] = (
            r["lenient"]
            and (ha["mean"] or -1) > 0
            and (hb["t"] or 0) > 2
            and (hb["good"] or 0) >= 0.55
            and hb.get("blocks", 0) >= 6
        )
        r["strict_pre"] = r["medium"] and (ho["mean"] or -1) > 0 and (hb["t"] or 0) > bonf
    for r in res:
        pb = portfolio(a, expr(r["keys"]), B0)
        ex = [p["r"] - p["bm"] for p in pb if p["k"] > 0]
        r["port_B"] = {
            "periods": len(pb),
            "invested": sum(p["k"] > 0 for p in pb),
            "mean_abs": float(np.mean([p["r"] for p in pb])),
            "mean_basket": float(np.mean([p["bm"] for p in pb])),
            "mean_excess_when_in": float(np.mean(ex)) if ex else None,
        }
        r["strict"] = r["strict_pre"] and (r["port_B"]["mean_excess_when_in"] or -1) > 0
    # basket and accounts
    base = portfolio(a, pl.lit(True), B0)
    accts = {"basket": {t: account([p["bm"] for p in base], t) for t in (0, 2, 4, 6, 10)}}
    for r in res:
        if r["medium"]:
            pb = portfolio(a, expr(r["keys"]), B0)
            accts[r["rule"]] = {t: account([p["r"] for p in pb], t) for t in (0, 2, 4, 6, 10)}
    timing = {}
    for f in MARKET:
        for b in range(3):
            tb = {}
            for h, start, stop in (("O", O0, A0), ("A", A0, B0), ("B", B0, "2100-01-01")):
                d = a.filter(
                    (C("date") >= pl.lit(start).str.to_date())
                    & (C("date") < pl.lit(stop).str.to_date())
                )
                days = d["date"].unique().sort().to_list()[::H]
                p = (
                    d.filter(C("date").is_in(days))
                    .group_by("date")
                    .agg(bm=C("f20").mean(), on=(C("q_" + f) == b).first())
                    .sort("date")
                )
                rs = [r["bm"] if r["on"] else CASH for r in p.iter_rows(named=True)]
                tb[h] = {
                    "timed": float(np.mean(rs)),
                    "basket": float(p["bm"].mean()),
                    "share_in": float(p["on"].mean()),
                }
            timing[f"{f}={b}"] = tb
    out = {
        "horizon": H,
        "cash_per_period": CASH,
        "timing": timing,
        "n_rules_scored_on_A": n_tests,
        "taken_to_B": TOP_FROM_A,
        "bonferroni_t": bonf,
        "results": res,
        "basket_B": {
            "periods": len(base),
            "mean": float(np.mean([p["bm"] for p in base])),
        },
        "accounts": accts,
    }
    (HERE / f"results_treasure_hunt_h{H}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    for r in res:
        f = lambda s: "  ".join(  # noqa: E731
            f"{h}:{(s[h]['mean'] or 0) * 100:+.1f}/t{(s[h]['t'] or 0):.1f}" for h in "OAB"
        )
        tag = "S" if r["strict"] else "M" if r["medium"] else "L" if r["lenient"] else "-"
        print(tag, r["rule"], f(r), f"port {r['port_B']['mean_excess_when_in']}")
    print(json.dumps(accts["basket"]))
    for k, v in timing.items():
        print(k, {h: {kk: round(vv, 3) for kk, vv in x.items()} for h, x in v.items()})


if __name__ == "__main__":
    main()
