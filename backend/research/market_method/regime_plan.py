"""Regime plan study: when to be in, when to scale in, when to switch a stock, and by how much.
(docs/reports/regime-plan-2026-11.md)

Four questions, each judged on both halves of time (and by era), with costs, against a simple baseline:
 A. Does a market trend filter (index vs its moving averages) help as an in/half/out exposure rule?
 B. Is buying in steps (time steps, or dip steps) better than buying at once, and in which market state?
 C. Does a rank-based stock pick beat the universe mean, and does a buffer (replace only a stock that fell
    out of the top M) cut turnover without losing the edge?
 D. The pieces together: exposure x selection, net of costs, 20-day periods.

Conventions: signal at close t, trade at close t+1, liquid top 60% by 20-day median traded value (rank known
the day before for the index), prices adjusted, round trip 1.75% split buy 0.62% / sell 1.13%
(commission+tax verified, slippage 0.5% assumed). Cash earns 0 or 20% a year (an untested assumption).
Run from backend/ with the live env.  Output: results_regime_plan.json
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

import small_target as st

C = pl.col
G = st.G
HERE = Path(__file__).parent
BUY, SELL = 0.0062, 0.0113
STEP = 20  # trading days per review period
RC_YEAR = 0.20  # cash yield used in the "with cash yield" runs
YEAR_DAYS = 245.0
START = dt.date(int(sys.argv[1]) if len(sys.argv) > 1 else 2009, 1, 1)
TAG = f"_{START.year}"


def pct(x: pl.Expr) -> pl.Expr:
    return x.rank("average").over("date") / x.count().over("date")


def load() -> pl.DataFrame:
    p = st.prepare()
    c = C("adj_close")
    return p.with_columns(
        mom=(c.shift(21) / c.shift(252) - 1).over(G),
        rv20=C("ret").rolling_std(20, min_samples=15).over(G),
        lq_prev=C("lq").shift(1).over(G),
    )


# ---------------------------------------------------------------- index and regimes
def market_index(p: pl.DataFrame) -> pl.DataFrame:
    d = (
        p.filter((C("lq_prev") > 0.4) & C("ret").is_not_null())
        .with_columns(C("ret").clip(-0.15, 0.15))
        .group_by("date")
        .agg(C("ret").mean().alias("m"), C("ret").len().alias("n"))
        .sort("date")
        .filter(C("n") >= 30)
    )
    d = d.with_columns(I=(1 + C("m")).cum_prod())
    for k in (50, 100, 200):
        d = d.with_columns(C("I").rolling_mean(k, min_samples=k).alias(f"ma{k}"))
    d = d.with_columns(
        hi252=C("I").rolling_max(252, min_samples=100),
        fwd20=C("I").shift(-20) / C("I") - 1,
    )
    return d.with_columns(
        up50=(C("I") > C("ma50")),
        up100=(C("I") > C("ma100")),
        up200=(C("I") > C("ma200")),
        dd=C("I") / C("hi252") - 1,
    )


def hysteresis(i: np.ndarray, ma: np.ndarray, band: float) -> np.ndarray:
    out = np.zeros(len(i))
    on = False
    for k in range(len(i)):
        if np.isnan(ma[k]):
            out[k] = 0.0
            continue
        if not on and i[k] > ma[k] * (1 + band):
            on = True
        elif on and i[k] < ma[k] * (1 - band):
            on = False
        out[k] = 1.0 if on else 0.0
    return out


def run_exposure(m: np.ndarray, e_raw: np.ndarray, rc_day: float, lag: int = 2) -> dict:
    e = np.concatenate([np.zeros(lag), e_raw[:-lag]]) if lag else e_raw.copy()
    v = 1.0
    peak = 1.0
    mdd = 0.0
    trades = 0
    prev = 0.0
    for k in range(len(m)):
        de = e[k] - prev
        if abs(de) > 1e-9:
            v *= 1 - (BUY * max(de, 0) + SELL * max(-de, 0))
            trades += 1
        prev = e[k]
        v *= 1 + e[k] * m[k] + (1 - e[k]) * rc_day
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {"final": v, "mdd": mdd, "trades": trades, "inmkt": float(e.mean())}


def cagr(v: float, years: float) -> float:
    return v ** (1 / years) - 1 if v > 0 and years > 0 else float("nan")


def section_a(idx: pl.DataFrame, mid) -> dict:
    d = idx.filter(C("ma200").is_not_null() & (C("date") >= START))
    dates = d["date"].to_list()
    m = d["m"].to_numpy()
    i = d["I"].to_numpy()
    up = {k: d[f"up{k}"].to_numpy().astype(float) for k in (50, 100, 200)}
    rules = {
        "always in": np.ones(len(m)),
        "in above MA50": up[50],
        "in above MA100": up[100],
        "in above MA200": up[200],
        "stair: 1/3 per MA (50,100,200)": (up[50] + up[100] + up[200]) / 3,
        "MA100 with 2% band": hysteresis(i, d["ma100"].to_numpy(), 0.02),
        "MA200 with 2% band": hysteresis(i, d["ma200"].to_numpy(), 0.02),
        "out when 15% below 252d high": (d["dd"].fill_null(0).to_numpy() > -0.15).astype(float),
    }
    spans = {
        "all": (dates[0], dates[-1]),
        "H1": (dates[0], mid),
        "H2": (mid, dates[-1]),
    }
    res: dict = {"period_starts": {k: str(v[0]) for k, v in spans.items()}, "rules": {}}
    for rc_name, rc_y in (("cash0", 0.0), ("cash20", RC_YEAR)):
        rc_day = (1 + rc_y) ** (1 / YEAR_DAYS) - 1
        for name, e in rules.items():
            row = {}
            for sp, (a, b) in spans.items():
                sel = np.array([(x >= a) and (x <= b) for x in dates])
                years = (b - a).days / 365.25
                r = run_exposure(m[sel], e[sel], rc_day)
                row[sp] = {
                    "cagr": cagr(r["final"], years),
                    "mdd": r["mdd"],
                    "trades": r["trades"],
                    "inmkt": r["inmkt"],
                }
            res["rules"].setdefault(name, {})[rc_name] = row
    # what the market did after each state (next 20 trading days, no costs)
    cond = {}
    for sp, (a, b) in spans.items():
        x = d.filter((C("date") >= a) & (C("date") <= b) & C("fwd20").is_not_null())
        cond[sp] = {
            "above MA200": _fw(x.filter(C("up200"))),
            "below MA200": _fw(x.filter(~C("up200"))),
            "above MA100": _fw(x.filter(C("up100"))),
            "below MA100": _fw(x.filter(~C("up100"))),
            "15%+ below 252d high": _fw(x.filter(C("dd") <= -0.15)),
        }
    res["forward20_by_state"] = cond
    # by era: in above MA200 vs always in, no cash yield
    eras = {}
    for a, b in ((2001, 2009), (2009, 2013), (2013, 2018), (2018, 2022), (2022, 2027)):
        sel = np.array([(x.year >= a) and (x.year < b) for x in dates])
        if sel.sum() < 100:
            continue
        years = (dates[np.where(sel)[0][-1]] - dates[np.where(sel)[0][0]]).days / 365.25
        out = {}
        for nm in ("always in", "in above MA200", "stair: 1/3 per MA (50,100,200)"):
            r = run_exposure(m[sel], rules[nm][sel], 0.0)
            out[nm] = {"cagr": cagr(r["final"], years), "mdd": r["mdd"]}
        eras[f"{a}-{b - 1}"] = out
    res["eras_cash0"] = eras
    return res


def _fw(x: pl.DataFrame) -> dict:
    if x.height == 0:
        return {"n": 0}
    f = x["fwd20"].to_numpy()
    return {"n": int(x.height), "mean": float(f.mean()), "pos": float((f > 0).mean()),
            "p10": float(np.quantile(f, 0.1))}


# ---------------------------------------------------------------- B: staged entry
def section_b(p: pl.DataFrame, idx: pl.DataFrame, mid) -> dict:
    q = p.filter(
        (C("lq_prev") > 0.4) & C("c1").is_not_null() & C("c21").is_not_null()
        & (C("entry_locked") == False)  # noqa: E712
        & (C("adj_close") > 0) & (C("date") >= START)
    )
    q = q.join(idx.select("date", "up100", "up200"), on="date", how="inner").filter(
        C("up100").is_not_null()
    )
    c1, c8, c15, c21 = (q[f"c{k}"].to_numpy() for k in (1, 8, 15, 21))
    low = np.stack([q[f"l{k}"].to_numpy() for k in range(2, 17)], axis=1)
    lump = c21 / c1 - 1
    timed = (c21 / c1 + c21 / c8 + c21 / c15) / 3 - 1
    f2 = (low <= (0.95 * c1)[:, None]).any(axis=1)
    f3 = (low <= (0.90 * c1)[:, None]).any(axis=1)
    dip = (lump + np.where(f2, c21 / (0.95 * c1) - 1, 0) + np.where(f3, c21 / (0.90 * c1) - 1, 0)) / 3
    deployed = (1 + f2 + f3) / 3
    ok = ~(np.isnan(lump) | np.isnan(timed))
    dates = q["date"]
    up = q["up100"].to_numpy()
    out: dict = {}
    for hn, hsel in (("H1", (dates < mid).to_numpy()), ("H2", (dates >= mid).to_numpy())):
        for rn, rsel in (("market above MA100", up), ("market below MA100", ~up)):
            s = ok & hsel & rsel
            row = {"n": int(s.sum())}
            for nm, r in (("lump", lump), ("time steps", timed), ("dip steps", dip)):
                x = r[s]
                row[nm] = {"mean": float(x.mean()), "median": float(np.median(x)),
                           "p10": float(np.quantile(x, 0.1)), "p90": float(np.quantile(x, 0.9))}
            row["dip_deployed"] = float(deployed[s].mean())
            row["dip_all3_filled"] = float(f3[s].mean())
            row["dip_none_filled"] = float((~f2[s]).mean())
            out[f"{hn} | {rn}"] = row
    return out


# ---------------------------------------------------------------- C: selection and switching
def review_rows(p: pl.DataFrame) -> pl.DataFrame:
    dates = p["date"].unique().sort()
    rev = dates.gather_every(STEP)
    q = p.filter(
        C("date").is_in(rev.implode()) & (C("lq") > 0.4) & C("c1").is_not_null() & C("c21").is_not_null()
        & C("mom").is_not_null() & C("rv20").is_not_null() & C("dd252").is_not_null()
        & (C("entry_locked") == False)  # noqa: E712
        & (C("adj_close") > 0) & (C("date") >= START)
    )
    q = q.with_columns(r=C("c21") / C("c1") - 1)
    q = q.with_columns(
        score=(pct(C("mom")) + pct(-C("rv20")) + pct(C("dd252"))) / 3,
    ).with_columns(
        pos=C("score").rank("ordinal", descending=True).over("date"),
        pos_hi=pct(C("dd252")).rank("ordinal", descending=True).over("date"),
    )
    return q.select("date", G, "score", "pos", "pos_hi", "r")


def simulate(q: pl.DataFrame, n: int, buffer: int | None, slow: int | None = None, pc: str = "pos") -> pl.DataFrame:
    """Per review period: gross mean return of the held names, turnover share, net return, base mean."""
    held: set = set()
    recs = []
    k = 0
    for (d,), g in sorted(q.partition_by("date", as_dict=True).items(), key=lambda kv: kv[0][0]):
        k += 1
        rows = {r[G]: r for r in g.iter_rows(named=True)}
        base = float(np.mean([r["r"] for r in rows.values()]))
        top = [r[G] for r in sorted(rows.values(), key=lambda r: r[pc])]
        if buffer is None and slow is None:
            new = set(top[:n])
        else:
            if slow is not None and (k - 1) % slow != 0 and held:
                keep = {s for s in held if s in rows}
            else:
                lim = buffer if buffer is not None else n
                keep = {s for s in held if s in rows and rows[s][pc] <= lim}
            new = set(keep)
            for s in top:
                if len(new) >= n:
                    break
                new.add(s)
        if not new:
            continue
        added = len(new - held)
        removed = len(held - new)
        cost = added / n * BUY + removed / n * SELL
        gross = float(np.mean([rows[s]["r"] for s in new]))
        recs.append({"date": d, "gross": gross, "net": gross - cost, "turn": added / n,
                     "base": base, "n_held": len(new)})
        held = new
    return pl.DataFrame(recs)


def sim_stats(s: pl.DataFrame, mid, idx_state: pl.DataFrame) -> dict:
    s = s.join(idx_state.select("date", "up100"), on="date", how="left")
    out = {}
    for hn, sel in (("H1", C("date") < mid), ("H2", C("date") >= mid)):
        x = s.filter(sel)
        ex = (x["net"] - x["base"]).to_numpy()
        out[hn] = {
            "periods": int(x.height),
            "net": float(x["net"].mean()),
            "base": float(x["base"].mean()),
            "excess": float(ex.mean()),
            "t": float(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))) if len(ex) > 2 else None,
            "turn": float(x["turn"].mean()),
        }
    for nm, sel in (("up", C("up100")), ("down", ~C("up100"))):
        x = s.filter(sel.fill_null(False))
        ex = (x["net"] - x["base"]).to_numpy()
        out[f"regime_{nm}"] = {
            "periods": int(x.height),
            "excess": float(ex.mean()) if len(ex) else None,
            "gross_excess": float((x["gross"] - x["base"]).mean()) if x.height else None,
        }
    return out


# ---------------------------------------------------------------- D: together
def combine(s: pl.DataFrame, idx: pl.DataFrame, mid, rule: str, rc_year: float, use_net: bool = True) -> dict:
    s = s.join(idx.select("date", "up50", "up100", "up200"), on="date", how="left").sort("date")
    rc = (1 + rc_year) ** (STEP / YEAR_DAYS) - 1
    ret = (s["net"] if use_net else s["base"]).to_numpy()
    up50, up100, up200 = (s[k].fill_null(False).to_numpy().astype(float) for k in ("up50", "up100", "up200"))
    e = {"always": np.ones(len(ret)), "stair": (up50 + up100 + up200) / 3, "MA200": up200,
         "MA100": up100}[rule]
    dts = s["date"].to_list()
    res = {}
    for nm, (a, b) in (("all", (dts[0], dts[-1])), ("H1", (dts[0], mid)), ("H2", (mid, dts[-1]))):
        v, peak, mdd, prev = 1.0, 1.0, 0.0, 0.0
        first = True
        n = 0
        for k, d in enumerate(dts):
            if d < a or d > b:
                continue
            if first:
                prev = 0.0
                first = False
            de = e[k] - prev
            if abs(de) > 1e-9:
                v *= 1 - (BUY * max(de, 0) + SELL * max(-de, 0))
            prev = e[k]
            v *= 1 + e[k] * ret[k] + (1 - e[k]) * rc
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
            n += 1
        years = n * STEP / YEAR_DAYS
        res[nm] = {"cagr": cagr(v, years), "mdd": mdd}
    return res


def main() -> int:
    p = load()
    idx = market_index(p)  # full history for the moving averages; scoring starts at START
    valid = idx.filter(C("ma200").is_not_null() & (C("date") >= START))["date"].sort()
    mid = valid[valid.len() // 2]
    out: dict = {"split": str(mid), "index_days": idx.height}
    out["A"] = section_a(idx, mid)
    out["B"] = section_b(p, idx, mid)
    q = review_rows(p)
    out["C"] = {}
    sims = {}
    for nm, (n, buf, slow) in {
        "top10 full rebalance": (10, None, None),
        "top10 keep while rank<=20": (10, 20, None),
        "top10 keep while rank<=30": (10, 30, None),
        "top10 keep while rank<=50": (10, 50, None),
        "top10 rebalance once a year": (10, None, 12),
        "top5 keep while rank<=15": (5, 15, None),
        "top20 keep while rank<=40": (20, 40, None),
        "NEAR-HIGH only: top10 keep<=30": (10, 30, None),
        "NEAR-HIGH only: top10 full rebalance": (10, None, None),
    }.items():
        s = simulate(q, n, buf, slow, "pos_hi" if nm.startswith("NEAR") else "pos")
        sims[nm] = s
        out["C"][nm] = sim_stats(s, mid, idx)
    # D: use the 'top10 keep while rank<=30' sleeve and the equal-weight universe
    d = {}
    base_s = sims["top10 keep while rank<=30"]
    hi_s = sims["NEAR-HIGH only: top10 keep<=30"]
    for rc_name, rc_y in (("cash0", 0.0), ("cash20", RC_YEAR)):
        for sleeve, use_net, src in (("equal-weight universe", False, base_s),
                                     ("top10 keep<=30", True, base_s),
                                     ("near-high top10 keep<=30", True, hi_s)):
            for rule in ("always", "MA200", "MA100", "stair"):
                d[f"{rc_name} | {sleeve} | {rule}"] = combine(src, idx, mid, rule, rc_y, use_net)
    out["D"] = d
    (HERE / f"results_regime_plan{TAG}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    # ---- print
    print("split", out["split"])
    print("== A (cash0): CAGR / maxDD ; trades ; time in market")
    for nm, r in out["A"]["rules"].items():
        a = r["cash0"]
        b = r["cash20"]
        print(f"{nm:34s} all {100*a['all']['cagr']:5.1f}%/{100*a['all']['mdd']:5.0f}%  H1 {100*a['H1']['cagr']:5.1f}%  H2 {100*a['H2']['cagr']:5.1f}%"
              f" | cash20 all {100*b['all']['cagr']:5.1f}% H1 {100*b['H1']['cagr']:5.1f}% H2 {100*b['H2']['cagr']:5.1f}%"
              f" | trades {a['all']['trades']} inmkt {100*a['all']['inmkt']:.0f}%")
    print("forward 20d of the market by state (H1 | H2): mean, share up")
    for st_name in out["A"]["forward20_by_state"]["H1"]:
        h1 = out["A"]["forward20_by_state"]["H1"][st_name]
        h2 = out["A"]["forward20_by_state"]["H2"][st_name]
        print(f"  {st_name:24s} H1 n={h1['n']:5d} {100*h1['mean']:+5.2f}% up {100*h1['pos']:3.0f}% | H2 n={h2['n']:5d} {100*h2['mean']:+5.2f}% up {100*h2['pos']:3.0f}%")
    print("eras (cash0):")
    for era, r in out["A"]["eras_cash0"].items():
        print("  ", era, {k: f"{100*v['cagr']:.1f}%/{100*v['mdd']:.0f}%" for k, v in r.items()})
    print("== B staged entry (20 day hold, mean / p10)")
    for k, r in out["B"].items():
        print(f"  {k:36s} n={r['n']:6d} lump {100*r['lump']['mean']:+5.2f}/{100*r['lump']['p10']:+6.1f}  time {100*r['time steps']['mean']:+5.2f}/{100*r['time steps']['p10']:+6.1f}"
              f"  dip {100*r['dip steps']['mean']:+5.2f}/{100*r['dip steps']['p10']:+6.1f} deployed {100*r['dip_deployed']:.0f}% none-filled {100*r['dip_none_filled']:.0f}%")
    print("== C selection / switching (net per 20d, excess vs universe, t, turnover)")
    for nm, r in out["C"].items():
        print(f"  {nm:30s} H1 net {100*r['H1']['net']:+5.2f} ex {100*r['H1']['excess']:+5.2f} t {r['H1']['t']:+.1f} turn {100*r['H1']['turn']:3.0f}%"
              f" | H2 net {100*r['H2']['net']:+5.2f} ex {100*r['H2']['excess']:+5.2f} t {r['H2']['t']:+.1f} turn {100*r['H2']['turn']:3.0f}%"
              f" | up ex {100*r['regime_up']['excess']:+5.2f} down ex {100*r['regime_down']['excess']:+5.2f} | GROSS up {100*r['regime_up']['gross_excess']:+5.2f} down {100*r['regime_down']['gross_excess']:+5.2f}")
    print("== D together: CAGR/maxDD (all, H1, H2)")
    for k, r in out["D"].items():
        print(f"  {k:52s} " + "  ".join(f"{s} {100*v['cagr']:5.1f}%/{100*v['mdd']:4.0f}%" for s, v in r.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
