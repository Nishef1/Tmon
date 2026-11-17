"""The ~400-day mega winners: what did they look like on the day we could have bought them?
(docs/reports/mega-winners-2026-11.md)

Question: some stocks gained +300% to +1000% in about 400 days. Is it knowable at entry?
Entry = close of t+1, exit = last close on or before t+1+400 calendar days (adjusted prices), liquid top
60% of the day. A "mega" winner is a gain of +300% or more; "super" is +900% or more. All entries
from the last 3 years that have a full 400-day outcome are used. Features are the ones known at t:
liquidity rank, 12-1 and 3-month return, distance to the 252-day high, 60-day volatility,
20-day real-money net flow, liquidity surge, and the sector. Each is judged by the cross-section
rank on its own day, in both halves of the entry dates. The entries overlap heavily (one stock gives
many), so the lifts are descriptive, not tests.
Run from backend/ with the live env:  python research/market_method/mega_winners.py
Output: results_mega_winners.json
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import numpy as np
import polars as pl

import small_target as st

C = pl.col
G = st.G
HERE = Path(__file__).parent
DB = "D:/Data/Tmon/data/tmon-live.sqlite3"
HOLD_DAYS = 400
MEGA, SUPER = 3.0, 9.0
FEATS = {
    "lq": "liquidity rank (high = more traded)",
    "mom252": "12-1 month return",
    "mom60": "3-month return",
    "dd252": "closeness to the 252-day high",
    "rv60": "60-day volatility",
    "flow20": "20-day real-money net flow / traded value",
    "surge": "liquidity surge (20d median value vs 120 days ago)",
}


def build() -> pl.DataFrame:
    p = st.prepare().select("date", G, "adj_close", "vmed", "lq", "ret", "value", "locked")
    c = C("adj_close")
    p = p.with_columns(
        mom252=(c.shift(21) / c.shift(252) - 1).over(G),
        mom60=(c / c.shift(60) - 1).over(G),
        dd252=(c / c.rolling_max(250, min_samples=200) - 1).over(G),
        rv60=C("ret").rolling_std(60, min_samples=40).over(G),
        surge=(C("vmed") / C("vmed").shift(120) - 1).over(G),
        entry=c.shift(-1).over(G),
    )
    con = sqlite3.connect(DB)
    ct = pl.read_database(
        "select instrument_id, date, buy_value_i - sell_value_i as net, buy_value_i + sell_value_i as tot "
        "from client_types_daily",
        con,
    ).with_columns(C("date").str.to_date())
    ct = ct.sort(G, "date").with_columns(
        flow20=(
            C("net").rolling_sum(20, min_samples=15) / C("tot").rolling_sum(20, min_samples=15)
        ).over(G)
    )
    p = p.join(ct.select("date", G, "flow20"), on=["date", G], how="left")
    right = p.select(C("date").alias("xd"), G, C("adj_close").alias("exit_px")).sort("xd")
    end = p["date"].max()
    left = (
        p.filter(C("date") <= end - dt.timedelta(days=HOLD_DAYS + 12))
        .with_columns(target=C("date") + pl.duration(days=HOLD_DAYS + 1))
        .sort("target")
    )
    j = left.join_asof(right, left_on="target", right_on="xd", by=G, strategy="backward")
    j = j.filter((C("target") - C("xd")).dt.total_days() <= 10)
    j = j.with_columns(fwd=C("exit_px") / C("entry") - 1)
    return j


def main() -> None:
    con = sqlite3.connect(DB)
    names = dict(con.execute("select id, symbol_fa from instruments").fetchall())
    sector = dict(con.execute("select id, sector_code from instruments").fetchall())
    sname = dict(con.execute("select code, name from sector_names").fetchall())
    j = build()
    start = j["date"].max().replace(year=j["date"].max().year - 3)
    j = j.filter((C("date") >= start) & (C("lq") > 0.4) & C("fwd").is_not_null() & ~C("locked"))
    j = j.filter(C("entry").is_not_null() & (C("ret").abs() < 0.5))
    j = j.with_columns(
        top5=(C("fwd").rank("average").over("date") / C("fwd").count().over("date") >= 0.95)
    )
    mid = j["date"].unique().sort()[j["date"].n_unique() // 2]
    base_mean = j["fwd"].mean()
    out: dict = {
        "entries": j.height,
        "stocks": j[G].n_unique(),
        "entry_dates": [str(j["date"].min()), str(j["date"].max())],
        "split": str(mid),
        "base_mean": base_mean,
        "base_median": j["fwd"].median(),
    }
    for nm, thr in (("mega", MEGA), ("super", SUPER)):
        out[f"share_{nm}"] = float((j["fwd"] >= thr).mean())
        out[f"stocks_{nm}"] = int(j.filter(C("fwd") >= thr)[G].n_unique())
    print(
        f"entries {j.height}, stocks {j[G].n_unique()}, mean {base_mean:+.0%} median "
        f"{j['fwd'].median():+.0%}, share>=+300% {out['share_mega']:.1%}, >=+900% {out['share_super']:.2%}"
    )

    # the super winners, one line per stock
    sup = (
        j.filter(C("fwd") >= SUPER)
        .sort("fwd", descending=True)
        .group_by(G, maintain_order=True)
        .first()
    )
    rows = []
    for r in sup.iter_rows(named=True):
        rows.append(
            {
                "symbol": names.get(r[G]),
                "sector": sname.get(sector.get(r[G]), None),
                "best_entry": str(r["date"]),
                "gain": r["fwd"],
                "liq": r["lq"],
                "mom252": r["mom252"],
                "dd252": r["dd252"],
                "flow20": r["flow20"],
            }
        )
    out["super_stocks"] = rows
    print(f"{len(rows)} stocks had a +900% entry; first 25:")
    for r in rows[:25]:
        print(
            f"  {r['symbol']:10s} {r['best_entry']} {r['gain']:+.0%} liq {r['liq']:.2f} "
            f"mom {r['mom252'] if r['mom252'] is not None else float('nan'):+.0%} "
            f"dd {r['dd252'] if r['dd252'] is not None else float('nan'):+.0%} | {r['sector']}"
        )

    # by entry quarter: market and mega share
    q = (
        j.with_columns(qtr=C("date").dt.strftime("%Y-%m"))
        .group_by("qtr")
        .agg(
            mean=C("fwd").mean(),
            med=C("fwd").median(),
            mega=(C("fwd") >= MEGA).mean(),
            sup=(C("fwd") >= SUPER).mean(),
            n=pl.len(),
        )
        .sort("qtr")
    )
    out["by_entry_month"] = q.to_dicts()
    print(
        q.filter(C("qtr").str.ends_with("-01") | C("qtr").str.ends_with("-07"))
        .to_pandas()
        .round(3)
        .to_string()
    )

    # sector view
    sec = (
        j.with_columns(
            sector=C(G).replace_strict(sector, default=None).replace_strict(sname, default=None)
        )
        .group_by("sector")
        .agg(
            n=pl.len(),
            stocks=C(G).n_unique(),
            mega=(C("fwd") >= MEGA).mean(),
            med=C("fwd").median(),
        )
        .filter(C("stocks") >= 5)
        .sort("mega", descending=True)
    )
    out["sectors"] = sec.to_dicts()
    print("sectors with the highest mega share (base %.1f%%):" % (100 * out["share_mega"]))
    for r in sec.head(8).iter_rows(named=True):
        print(
            f"  {r['sector']:28s} stocks {r['stocks']:3d} mega {r['mega']:.1%} median {r['med']:+.0%}"
        )

    # feature lift, both halves: top decile vs bottom decile of the day's rank
    out["features"] = {}
    for f in FEATS:
        d = j.filter(C(f).is_not_null() & C(f).is_finite())
        d = d.with_columns(r=C(f).rank("average").over("date") / C(f).count().over("date"))
        res = {}
        cohort = dt.date(2025, 7, 1)
        for hn, sel in (
            ("h1", C("date") < mid),
            ("h2", C("date") >= mid),
            ("c25", C("date") >= cohort),
        ):
            x = d.filter(sel)
            allm = float(x["top5"].mean())
            top = x.filter(C("r") > 0.9)
            bot = x.filter(C("r") <= 0.1)
            res[hn] = {
                "base_mega": allm,
                "top_mega": float(top["top5"].mean()),
                "bot_mega": float(bot["top5"].mean()),
                "top_mega300": float((top["fwd"] >= MEGA).mean()),
                "bot_mega300": float((bot["fwd"] >= MEGA).mean()),
                "base_mega300": float((x["fwd"] >= MEGA).mean()),
                "top_median": float(top["fwd"].median()),
                "bot_median": float(bot["fwd"].median()),
                "base_median": float(x["fwd"].median()),
            }
        out["features"][f] = res
        h1, h2, c25 = res["h1"], res["h2"], res["c25"]
        print(
            f"{f:7s} P(top5% of the day) top/bottom decile  h1 {h1['top_mega']:.1%}/{h1['bot_mega']:.1%} "
            f"(base {h1['base_mega']:.1%}) | h2 {h2['top_mega']:.1%}/{h2['bot_mega']:.1%} "
            f"(base {h2['base_mega']:.1%}) | median top/bot h1 {h1['top_median']:+.0%}/{h1['bot_median']:+.0%} "
            f"h2 {h2['top_median']:+.0%}/{h2['bot_median']:+.0%} | cohort2025-07+: P(>=+300%) "
            f"{c25['top_mega300']:.1%}/{c25['bot_mega300']:.1%} (base {c25['base_mega300']:.1%})"
        )
    (HERE / "results_mega_winners.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str)
    )


if __name__ == "__main__":
    main()
