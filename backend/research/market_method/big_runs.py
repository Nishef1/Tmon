"""Big runs of the last three years: what they shared at the start and at the top, and whether
any of it makes the trend-ride entry or exit better out of sample
(docs/reports/big-runs-2026-11.md)

1. Runs: legs of the adjusted close with a 25% reversal (zigzag). A big run is a leg up of at least
   +100% whose low is on or after START and on a day the stock was in the point-in-time top 300.
   For each: length, gain, start month, industry, and what the trend-ride rule (trend_research,
   trail 25%, buy-queue wait) caught of it.
2. Signals: every trend_high signal of a top-300 member since START, ridden with the 25% trailing
   exit. Features on the signal day (price, queue, value, real-investor flow, market breadth,
   monthly sales growth). Cut points are the terciles of the first half; each feature reports the
   share of rides that became a big run (run-up >= +100%) and the mean net in its top and bottom
   third, in each half. A filter is picked on the first half only and judged on the second.
3. Exits: the same entries with other exits (tighter trail after a big gain, sell queue, investor
   outflow, value climax), net after the round trip, in each half.

Descriptive and in-sample except where marked "picked on half 1". Not advice.
Run from backend/ with the live env:  python research/market_method/big_runs.py
Output: results_big_runs.json
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

os.environ.setdefault("TREND_TOP", "300")
os.environ.setdefault("TREND_WAIT", "1")

import numpy as np
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import trend_ride as tr  # noqa: E402
from fundamentals_study import DB  # noqa: E402

C = pl.col
G = "instrument_id"
START = date.fromisoformat(os.environ.get("BIG_START", "2023-11-01"))
REV = 0.25
BIG = 1.0
COST = tr.COST
OUT = HERE / f"results_big_runs{'_' + str(START.year) if 'BIG_START' in os.environ else ''}.json"


def zigzag(c: np.ndarray, rev: float) -> list[tuple[int, int]]:
    """(low, high) index pairs of every up leg with a `rev` reversal on both ends."""
    legs = []
    lo = hi = 0
    up = False
    for i in range(1, len(c)):
        if up:
            if c[i] > c[hi]:
                hi = i
            elif c[i] < (1 - rev) * c[hi]:
                legs.append((lo, hi))
                up, lo = False, i
        elif c[i] < c[lo]:
            lo = i
        elif c[i] > (1 + rev) * c[lo]:
            up, hi = True, i
    if up:
        legs.append((lo, hi))
    return legs


def flows() -> pl.DataFrame:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select instrument_id, date, buy_value_i - sell_value_i from client_types_daily"
        ).fetchall()
    return pl.DataFrame(rows, schema=[G, "date", "flow_i"], orient="row").with_columns(
        C("date").str.to_date()
    )


def sectors() -> dict[int, str]:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select i.id, coalesce(s.name, i.sector_code) from instruments i"
            " left join sector_names s on s.code = i.sector_code"
        ).fetchall()
    return {int(a): str(b or "?") for a, b in rows}


def sales_yoy(ids: dict[int, str]) -> pl.DataFrame:
    import csv

    by_sym = {v: k for k, v in ids.items()}
    with Path("D:/Data/Tmon/data/monthly-sales.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    s = pl.DataFrame(
        [
            {
                "symbol": r["symbol"],
                "jy": int(r["jy"]),
                "jm": int(r["jm"]),
                "pub": r["published_at"],
                "month": float(r["month"]),
            }
            for r in rows
        ]
    ).with_columns(C("pub").str.to_date())
    prev = s.select("symbol", (C("jy") + 1).alias("jy"), "jm", C("month").alias("m_prev"))
    s = s.join(prev, on=["symbol", "jy", "jm"]).filter((C("month") > 0) & (C("m_prev") > 0))
    s = s.with_columns(typ=C("month").median().over("symbol")).filter(C("m_prev") >= 0.2 * C("typ"))
    s = s.filter(C("symbol").is_in(list(by_sym))).with_columns(
        C("symbol").replace_strict(by_sym, return_dtype=pl.Int64).alias(G),
        yoy=C("month") / C("m_prev") - 1,
    )
    return s.select(G, "pub", "yoy").sort(G, "pub")


def trail_exit(c, ret, locked, e, rule, aux) -> int:
    """Index of the sale for one exit rule, -1 while still open."""
    n = len(c)
    pk = c[e]
    for j in range(e + 1, n):
        pk = max(pk, c[j])
        gain = pk / c[e] - 1
        hit = j - e >= tr.MAX_HOLD or c[j] < 0.75 * pk
        if rule == "trail15":
            hit |= c[j] < 0.85 * pk
        elif rule == "tier":  # 25% below the top, 15% once the run-up passed +100%
            hit |= gain >= 1.0 and c[j] < 0.85 * pk
        elif rule == "sellq":  # first sell-queue day after a +50% run-up
            hit |= gain >= 0.5 and locked[j] and ret[j] < 0
        elif rule == "outflow":  # investors sold over 5 days, after a +50% run-up
            hit |= gain >= 0.5 and aux["flow5"][j] < -0.1
        elif rule == "climax":  # 5-day value over 4x the 120-day mean after +100%, then a red close
            hit |= gain >= 1.0 and aux["vr5"][j - 1] > 4 and ret[j] < 0
        elif rule == "sma20_big":  # close under the 20-day mean once the run-up passed +100%
            hit |= gain >= 1.0 and c[j] < aux["sma20"][j]
        if hit:
            x = j + 1
            while x < n and locked[x] and ret[x] < 0:
                x += 1
            return x if x < n else -1
    return -1


EXITS = ("trail25", "trail15", "tier", "sellq", "outflow", "climax", "sma20_big")


def roll_sum(x: np.ndarray, n: int) -> np.ndarray:
    cs = np.cumsum(np.insert(np.nan_to_num(x), 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1 :] = cs[n:] - cs[:-n]
    return out


def main() -> None:
    p, ids = tr.load()
    pos, lvl, days = tr.market_index(p)
    last = days[-1]
    mid = START + (last - START) / 2
    sec = sectors()
    fl = flows()
    p = p.join(fl, on=[G, "date"], how="left")
    # market breadth: share of the day's members closing above their own 60-day mean
    p = p.with_columns(above60=(C("adj_close") > C("adj_close").rolling_mean(60).over(G)))
    breadth = dict(
        p.filter(C("member"))
        .group_by("date")
        .agg(C("above60").mean())
        .select("date", "above60")
        .iter_rows()
    )
    sy = sales_yoy(ids)
    sy_by: dict[int, tuple[list[date], list[float]]] = {}
    for (iid,), g in sy.group_by([G]):
        sy_by[int(iid)] = (g["pub"].to_list(), g["yoy"].to_list())

    runs, sigs = [], []
    univ_sec: Counter[str] = Counter()
    for (iid,), g in p.group_by([G], maintain_order=True):
        iid = int(iid)
        c = g["adj_close"].to_numpy().astype(float)
        if len(c) < 300:
            continue
        dts = g["date"].to_list()
        darr = np.array(dts)
        ret = g["ret"].fill_null(0.0).to_numpy()
        locked = g["locked"].to_numpy()
        member = g["member"].to_numpy()
        trr = g["tr"].fill_null(0.0).to_numpy().astype(float)
        val = g["value"].fill_null(0).to_numpy().astype(float)
        fi = g["flow_i"].to_numpy().astype(float)
        if (member & (darr >= START)).any():
            univ_sec[sec.get(iid, "?")] += 1
        qup = (locked & (ret > 0)).astype(float)
        aux = {
            "flow5": roll_sum(fi, 5) / np.maximum(roll_sum(val, 5), 1),
            "vr5": (roll_sum(val, 5) / 5) / np.maximum(roll_sum(val, 120) / 120, 1),
            "sma20": tr.sma(c, 20),
        }
        q20 = roll_sum(qup, 20) / 20
        vr20 = (roll_sum(val, 20) / 20) / np.maximum(roll_sum(val, 120) / 120, 1)
        flow20 = roll_sum(fi, 20) / np.maximum(roll_sum(val, 20), 1)
        hi250, lo250 = tr.roll_max_prev(c, 250), tr.roll_min_prev(c, 250)
        sig = tr.signals(c, ret, trr)["trend_high"] & member & (darr >= START)

        # rides of the trend rule with the 25% trail (the site's rule), to see what it caught
        rides = []
        busy = -1
        for t in map(int, np.flatnonzero(tr.signals(c, ret, trr)["trend_high"])):
            if t <= busy or t + 1 >= len(c):
                continue
            e = t + 1
            while e < min(len(c) - 1, t + 21) and locked[e] and ret[e] > 0:
                e += 1
            if locked[e] and ret[e] > 0:
                continue
            x = trail_exit(c, ret, locked, e, "trail25", aux)
            rides.append((t, e, x))
            busy = x if x >= 0 else len(c)

        for lo, hi in zigzag(c, REV):
            if dts[lo] < START or not member[max(0, lo - 5) : lo + 6].any():
                continue
            gain = c[hi] / c[lo] - 1
            if gain < BIG:
                continue
            caught = [r for r in rides if lo <= r[1] <= hi]
            r = caught[0] if caught else None
            exit_px = None if r is None or r[2] < 0 else float(c[r[2]])
            runs.append(
                {
                    G: iid,
                    "symbol": ids[iid],
                    "sector": sec.get(iid, "?"),
                    "low_date": str(dts[lo]),
                    "high_date": str(dts[hi]),
                    "days": hi - lo,
                    "gain": round(gain, 3),
                    "open": hi == len(c) - 1 or c[-1] > 0.75 * c[hi],
                    "queue_share": round(float(qup[lo : hi + 1].mean()), 3),
                    "entry_late": None if r is None else round(float(c[r[1]] / c[lo] - 1), 3),
                    "entry_days": None if r is None else r[1] - lo,
                    "exit_vs_high": None if exit_px is None else round(exit_px / c[hi] - 1, 3),
                    "ride_open": r is not None and r[2] < 0,
                }
            )

        for t in map(int, np.flatnonzero(sig)):
            e = t + 1
            while e < min(len(c) - 1, t + 21) and locked[e] and ret[e] > 0:
                e += 1
            if e >= len(c) or (locked[e] and ret[e] > 0) or dts[e] not in pos:
                continue
            pubs, yoys = sy_by.get(iid, ([], []))
            k = int(np.searchsorted(np.array(pubs, dtype=object), dts[t], side="right")) - 1
            syoy = yoys[k] if k >= 0 and (dts[t] - pubs[k]).days <= 60 else None
            row = {
                G: iid,
                "date": dts[t],
                "sector": sec.get(iid, "?"),
                "q20": q20[t],
                "vr20": vr20[t],
                "flow20": flow20[t],
                "ret60": c[t] / c[t - 60] - 1 if t >= 60 else np.nan,
                "fall250": lo250[t] / hi250[t] - 1,
                "breadth": breadth.get(dts[t], np.nan),
                "mkt60": lvl[pos[dts[t]]] / lvl[max(0, pos[dts[t]] - 60)] - 1
                if dts[t] in pos
                else np.nan,
                "sales_yoy": syoy,
            }
            for rule in EXITS:
                x = trail_exit(c, ret, locked, e, rule, aux)
                end = len(c) - 1 if x < 0 else x
                if dts[end] not in pos:
                    continue
                gross = c[end] / c[e] - 1
                mkt = lvl[pos[dts[end]]] / lvl[pos[dts[e]]] - 1
                row[f"net_{rule}"] = gross - COST
                row[f"ex_{rule}"] = gross - COST - mkt
                row[f"open_{rule}"] = x < 0
                if rule == "trail25":
                    row["runup"] = float(c[e : end + 1].max() / c[e] - 1)
                    row["hold"] = end - e
            sigs.append(row)

    out: dict[str, object] = {"start": str(START), "last": str(last), "mid": str(mid)}

    # 1. runs
    runs_df = pl.DataFrame(runs)
    out["runs"] = {
        "n": runs_df.height,
        "stocks": runs_df[G].n_unique(),
        "gain_median": runs_df["gain"].median(),
        "days_median": runs_df["days"].median(),
        "days_q": [runs_df["days"].quantile(q) for q in (0.25, 0.75)],
        "queue_share_median": runs_df["queue_share"].median(),
        "by_start_month": dict(Counter(d[:7] for d in runs_df["low_date"].to_list()).most_common()),
        "caught": int(runs_df["entry_late"].is_not_null().sum()),
        "entry_late_median": runs_df["entry_late"].median(),
        "entry_days_median": runs_df["entry_days"].median(),
        "exit_vs_high_median": runs_df["exit_vs_high"].median(),
        "exit_known": int(runs_df["exit_vs_high"].is_not_null().sum()),
    }
    rs = Counter(runs_df["sector"].to_list())
    tot = sum(univ_sec.values())
    out["run_sectors"] = [
        {
            "sector": s,
            "runs": k,
            "share_runs": round(k / runs_df.height, 3),
            "share_universe": round(univ_sec[s] / tot, 3),
        }
        for s, k in rs.most_common(12)
    ]
    out["run_list"] = runs_df.sort("gain", descending=True).head(40).to_dicts()
    print(json.dumps(out["runs"], ensure_ascii=False, default=str, indent=1))
    for s in out["run_sectors"]:  # type: ignore[attr-defined]
        print(s)

    # 2. signal features
    sig = pl.DataFrame(sigs, infer_schema_length=None).with_columns(
        big=C("runup") >= BIG, half=pl.when(C("date") < mid).then(1).otherwise(2)
    )
    h1 = sig.filter(C("half") == 1)
    feats = ("q20", "vr20", "flow20", "ret60", "fall250", "breadth", "mkt60", "sales_yoy")
    ftab = {}
    for f in feats:
        v1 = h1[f].drop_nulls().drop_nans()
        if v1.len() < 30:
            continue
        lo_c, hi_c = float(v1.quantile(1 / 3)), float(v1.quantile(2 / 3))
        d: dict[str, object] = {"cut": [round(lo_c, 4), round(hi_c, 4)]}
        for h in (1, 2):
            x = sig.filter((C("half") == h) & C(f).is_not_null() & C(f).is_not_nan())
            for name, cond in (("low", C(f) <= lo_c), ("high", C(f) > hi_c)):
                y = x.filter(cond)
                d[f"h{h}_{name}"] = {
                    "n": y.height,
                    "big": round(float(y["big"].mean()), 3) if y.height else None,
                    "net": round(float(y["net_trail25"].mean()), 3) if y.height else None,
                    "ex": round(float(y["ex_trail25"].mean()), 3) if y.height else None,
                }
        ftab[f] = d
        print(f, d)
    out["features"] = ftab

    def paired(cond: pl.Expr, h: int) -> dict[str, object]:
        x = sig.filter(C("half") == h).with_columns(m=C("date").dt.truncate("1mo"))
        allm = x.group_by("m").agg(a=C("ex_trail25").mean())
        sub = x.filter(cond).group_by("m").agg(b=C("ex_trail25").mean(), k=pl.len())
        j = sub.join(allm, on="m").filter(C("k") >= 3)
        d = (j["b"] - j["a"]).to_numpy()
        t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 2 else None
        cl = x.filter(cond & ~C("open_trail25"))
        ca = x.filter(~C("open_trail25"))
        return {
            "months": len(d),
            "diff": round(float(d.mean()), 4) if len(d) else None,
            "t": None if t is None else round(t, 2),
            "closed_diff": round(float(cl["ex_trail25"].mean() - ca["ex_trail25"].mean()), 4)
            if cl.height and ca.height
            else None,
        }

    ptab = {}
    for f, d in ftab.items():
        lo_c, hi_c = d["cut"]
        for side, cond in (("low", C(f) <= lo_c), ("high", C(f) > hi_c)):
            ptab[f"{f}_{side}"] = {f"h{h}": paired(cond & C(f).is_not_nan(), h) for h in (1, 2)}
            print("paired", f, side, ptab[f"{f}_{side}"])
    out["paired"] = ptab
    base = {}
    for h in (1, 2):
        x = sig.filter(C("half") == h)
        base[f"h{h}"] = {
            "n": x.height,
            "big": round(float(x["big"].mean()), 3),
            "net": round(float(x["net_trail25"].mean()), 3),
            "ex": round(float(x["ex_trail25"].mean()), 3),
            "open": int(x["open_trail25"].sum()),
        }
    out["signals_base"] = base
    print("base", base)

    # pick on half 1: the feature third with the best mean excess, judged on half 2
    best = max(
        (
            (f, side, d[f"h1_{side}"]["ex"])
            for f, d in ftab.items()
            for side in ("low", "high")
            if d[f"h1_{side}"]["n"] >= 30
        ),
        key=lambda z: z[2],
    )
    f, side, _ = best
    out["picked_on_h1"] = {
        "feature": f,
        "side": side,
        "h1": ftab[f][f"h1_{side}"],
        "h2": ftab[f][f"h2_{side}"],
        "h2_all": base["h2"],
    }
    print("picked", out["picked_on_h1"])

    # sectors among signals: big-run share by sector in each half (sectors with >= 20 signals)
    sec_tab = (
        sig.group_by("sector", "half")
        .agg(n=pl.len(), big=C("big").mean(), ex=C("ex_trail25").mean())
        .sort("sector", "half")
    )
    out["signal_sectors"] = [r for r in sec_tab.to_dicts() if r["n"] >= 20]

    # 3. exits
    ex = {}
    for rule in EXITS:
        d = {}
        for h in (1, 2):
            x = sig.filter((C("half") == h) & C(f"net_{rule}").is_not_null())
            closed = x.filter(~C(f"open_{rule}"))
            d[f"h{h}"] = {
                "net": round(float(x[f"net_{rule}"].mean()), 4),
                "ex": round(float(x[f"ex_{rule}"].mean()), 4),
                "net_median": round(float(x[f"net_{rule}"].median()), 4),
                "closed_ex": round(float(closed[f"ex_{rule}"].mean()), 4)
                if closed.height
                else None,
                "open": int(x[f"open_{rule}"].sum()),
            }
        ex[rule] = d
        print(rule, d)
    out["exits"] = ex
    bigs = sig.filter(C("big"))
    out["exits_on_big_runs"] = {
        rule: {
            "net_median": round(float(bigs[f"net_{rule}"].median()), 3),
            "kept_median": round(
                float(((1 + bigs[f"net_{rule}"]) / (1 + bigs["runup"])).median()), 3
            ),
        }
        for rule in EXITS
    }
    print(out["exits_on_big_runs"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
