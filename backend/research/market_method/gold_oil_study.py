"""Oil, world gold (ounce) and domestic gold against the market and industries, and the ratios
between them (docs/reports/gold-oil-2026-11.md)

Series (macro_series): brent_usd and gold_usd from Yahoo, gold_18k (rial per gram), coin_emami
(rial) and usd_free from tgju. Derived:

- ounce_rial = gold_usd * usd_free, brent_rial = brent_usd * usd_free
- gold_prem: 18k gold over its value at the ounce and the free dollar (0.75 purity, 31.1035 g)
- coin_bubble: Emami coin over its gold value (8.133 g at 0.900)
- usd_implied: the dollar that 18k gold and the ounce imply; usd_gap = usd_implied / usd_free - 1
- oil_gold: Brent in ounces of gold

Weeks: stocks Saturday to Wednesday, macro Thursday to Wednesday (as correlation_map.py), so a
Thursday-Friday move counts toward the stock week that reacts to it.

1. Levels: premium, bubble, dollar gap and oil/gold since 2013, by year.
2. Same week (last three years, liquid universe): market and each industry's market-removed
   residual against each series' weekly change, per half.
3. Leads, judged in both halves: last week's change against this week's market; the last four
   weeks against the next four (non-overlapping blocks); industry spreads picked on half 1.
4. Long check since 2013 with the TSETMC equal-weight index.
5. Ratios that may revert: does a high gold premium or coin bubble shrink, does the free dollar
   follow the gold-implied dollar, does the oil/gold trend say anything about the market?
6. Gold funds: how closely their weekly price follows 18k gold and the ounce in rial.

Descriptive and tested. Not advice. Run from backend/ with the live env:
python research/market_method/gold_oil_study.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import correlation_map as cm  # noqa: E402
import trend_ride as tr  # noqa: E402
from fundamentals_study import DB  # noqa: E402

OUT = HERE / "results_gold_oil.json"
GRAM = 31.1035
LONG_START = pd.Timestamp("2013-08-01")
EW_INDEX = "67130298613737946"  # TSETMC equal-weight index
TOTAL_INDEX = "32097828799138957"
H = 4  # weeks ahead for the block tests
PRICES = ("usd_free", "gold_18k", "coin_emami", "gold_usd", "brent_usd", "ounce_rial", "brent_rial")
RATIOS = ("gold_prem", "coin_bubble", "usd_gap", "oil_gold")


def week_of(d: pd.Series) -> pd.Series:
    return (d + pd.Timedelta(days=4)).dt.to_period("W-SUN").dt.start_time


def levels() -> pd.DataFrame:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select series, ref_period, value from macro_series where series in "
            "('usd_free','brent_usd','gold_usd','coin_emami','gold_18k')"
        ).fetchall()
    df = pd.DataFrame(rows, columns=["s", "d", "v"])
    df["d"] = pd.to_datetime(df["d"])
    df["week"] = week_of(df["d"])
    lv = df.sort_values("d").groupby(["week", "s"])["v"].last().unstack().sort_index()
    lv = lv[lv.index >= LONG_START].ffill(limit=2)
    lv["ounce_rial"] = lv["gold_usd"] * lv["usd_free"]
    lv["brent_rial"] = lv["brent_usd"] * lv["usd_free"]
    lv["gold_prem"] = lv["gold_18k"] / (lv["ounce_rial"] / GRAM * 0.75) - 1
    lv["coin_bubble"] = lv["coin_emami"] / (lv["ounce_rial"] / GRAM * 8.133 * 0.9) - 1
    lv["usd_implied"] = lv["gold_18k"] * GRAM / (0.75 * lv["gold_usd"])
    lv["usd_gap"] = lv["usd_implied"] / lv["usd_free"] - 1
    lv["oil_gold"] = lv["brent_usd"] / lv["gold_usd"]
    return lv


def changes(lv: pd.DataFrame) -> pd.DataFrame:
    ch = pd.DataFrame(index=lv.index)
    for x in PRICES:
        ch[x] = lv[x].pct_change(fill_method=None)
    # usd_gap equals gold_prem by construction (both are 18k gold over ounce x free dollar), so
    # only the premium enters the change table; usd_follow below asks which side moves back
    for x in ("gold_prem", "coin_bubble"):
        ch[x] = lv[x].diff()
    ch["oil_gold"] = lv["oil_gold"].pct_change(fill_method=None)
    return ch


def corr(a: pd.Series, b: pd.Series, n_min: int = 20) -> float | None:
    x = pd.concat([a, b], axis=1).dropna()
    if len(x) < n_min or x.iloc[:, 0].std() == 0 or x.iloc[:, 1].std() == 0:
        return None
    return round(float(x.corr().iloc[0, 1]), 2) if len(x) >= n_min else None


def halves(index: pd.Index, mid) -> tuple[tuple[str, np.ndarray], ...]:
    return (("h1", np.asarray(index < mid)), ("h2", np.asarray(index >= mid)))


def block_corr(sig: pd.Series, fwd: pd.Series, h: int = H) -> dict:
    """Correlation of the last h weeks' signal with the next h weeks, on non-overlapping blocks
    (each of the h offsets separately, then averaged), so the t is not inflated by overlap."""
    s = sig.rolling(h).sum()
    f = fwd.rolling(h).sum().shift(-h)
    cs, ns = [], []
    for k in range(h):
        x = pd.concat([s.iloc[k::h], f.iloc[k::h]], axis=1).dropna()
        if len(x) < 12:
            continue
        cs.append(float(x.corr().iloc[0, 1]))
        ns.append(len(x))
    if not cs:
        return {}
    c, n = float(np.mean(cs)), int(np.mean(ns))
    t = c * np.sqrt(max(n - 2, 1) / max(1 - c * c, 1e-9))
    return {"corr": round(c, 2), "n": n, "t": round(float(t), 2)}


def lead_tests(y: pd.Series, ch: pd.DataFrame, mid) -> dict:
    out: dict = {}
    for x in ch.columns:
        row = {}
        for h, mask in halves(y.index, mid):
            a = pd.concat([y[mask], ch[x].shift(1)[mask]], axis=1).dropna()
            if len(a) > 20:
                c = float(a.corr().iloc[0, 1])
                row[f"lag1_{h}"] = {
                    "corr": round(c, 2),
                    "t": round(c * np.sqrt((len(a) - 2) / max(1 - c * c, 1e-9)), 2),
                }
            row[f"block{H}_{h}"] = block_corr(ch[x][mask], y[mask])
        out[x] = row
    return out


def same_week(m: pd.Series, res: pd.DataFrame, ch: pd.DataFrame, mid) -> dict:
    out: dict = {"market": {}, "industries": {}}
    for x in ch.columns:
        out["market"][x] = {h: corr(m[mask], ch[x][mask]) for h, mask in halves(m.index, mid)}
        out["market"][x]["all"] = corr(m, ch[x])
    for s in res.columns:
        out["industries"][s] = {
            x: {h: corr(res[s][mask], ch[x][mask]) for h, mask in halves(res.index, mid)}
            for x in ch.columns
        }
    return out


def spread_leads(res: pd.DataFrame, ch: pd.DataFrame, mid) -> dict:
    """For each series: industries whose same-week residual link to it was >= 0.15 (or <= -0.15)
    in half 1 form a long-minus-short spread. Then the lead of last week's series move on this
    week's spread, in each half (half 1 is in-sample for the pick, half 2 is not)."""
    out: dict = {}
    h1 = np.asarray(res.index < mid)
    for x in ch.columns:
        link = {s: corr(res[s][h1], ch[x][h1]) or 0.0 for s in res.columns}
        up = sorted(s for s, v in link.items() if v >= 0.15)
        dn = sorted(s for s, v in link.items() if v <= -0.15)
        if not up or not dn:
            out[x] = {"up": up, "down": dn}
            continue
        spread = res[up].mean(axis=1) - res[dn].mean(axis=1)
        row: dict = {"up": up, "down": dn}
        for h, mask in halves(res.index, mid):
            row[f"same_week_{h}"] = corr(spread[mask], ch[x][mask])
            a = pd.concat([spread[mask], ch[x].shift(1)[mask]], axis=1).dropna()
            row[f"lag1_{h}"] = round(float(a.corr().iloc[0, 1]), 2) if len(a) > 20 else None
            row[f"block{H}_{h}"] = block_corr(ch[x][mask], spread[mask])
        out[x] = row
    return out


def level_summary(lv: pd.DataFrame) -> dict:
    out: dict = {}
    for x in RATIOS:
        s = lv[x].dropna()
        by_year = s.groupby(s.index.year).agg(["mean", "min", "max"]).round(3)
        out[x] = {
            "latest": round(float(s.iloc[-1]), 3),
            "latest_week": str(s.index[-1].date()),
            "pct_rank_since_2013": round(float((s < s.iloc[-1]).mean()), 2),
            "pct_rank_3y": round(float((s[s.index >= s.index[-1] - pd.Timedelta(days=1095)] < s.iloc[-1]).mean()), 2),
            "mean": round(float(s.mean()), 3),
            "by_year": {str(k): v for k, v in by_year.to_dict("index").items()},
        }
    return out


def reversion(lv: pd.DataFrame, mid) -> dict:
    """Does the ratio itself come back? Level now against its change over the next H weeks, and
    for the premium and bubble, what holding 18k gold or a coin earned over gold's value."""
    out: dict = {}
    fwd_ratio = {x: lv[x].shift(-H) - lv[x] for x in ("gold_prem", "coin_bubble", "usd_gap")}
    fwd_ratio["oil_gold"] = lv["oil_gold"].shift(-H) / lv["oil_gold"] - 1
    for x, f in fwd_ratio.items():
        dev = lv[x] - lv[x].rolling(52, min_periods=26).mean()
        row = {}
        for h, mask in halves(lv.index, mid):
            cs = []
            for k in range(H):
                a = pd.concat([dev[mask].iloc[k::H], f[mask].iloc[k::H]], axis=1).dropna()
                if len(a) > 12:
                    cs.append(float(a.corr().iloc[0, 1]))
            if cs:
                c = float(np.mean(cs))
                n = int(mask.sum() / H)
                row[h] = {"corr": round(c, 2), "n": n, "t": round(c * np.sqrt((n - 2) / (1 - c * c)), 2)}
        out[x] = row
    # the free dollar against the gold-implied dollar
    gap = lv["usd_gap"]
    usd_f = lv["usd_free"].shift(-H) / lv["usd_free"] - 1
    imp_f = lv["usd_implied"].shift(-H) / lv["usd_implied"] - 1
    row = {}
    for h, mask in halves(lv.index, mid):
        row[h] = {
            "gap_vs_next_usd_free": block_level(gap[mask], usd_f[mask]),
            "gap_vs_next_usd_implied": block_level(gap[mask], imp_f[mask]),
        }
    out["usd_follow"] = row
    return out


def block_level(sig: pd.Series, fwd: pd.Series) -> dict:
    cs, ns = [], []
    for k in range(H):
        a = pd.concat([sig.iloc[k::H], fwd.iloc[k::H]], axis=1).dropna()
        if len(a) > 12:
            cs.append(float(a.corr().iloc[0, 1]))
            ns.append(len(a))
    if not cs:
        return {}
    c, n = float(np.mean(cs)), int(np.mean(ns))
    return {"corr": round(c, 2), "n": n, "t": round(c * np.sqrt((n - 2) / max(1 - c * c, 1e-9)), 2)}


def index_weekly() -> pd.DataFrame:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute("select index_code, date, close from market_index_daily").fetchall()
    df = pd.DataFrame(rows, columns=["c", "d", "v"])
    df["d"] = pd.to_datetime(df["d"])
    df["week"] = (df["d"] + pd.Timedelta(days=2)).dt.to_period("W-SUN").dt.start_time
    w = df.sort_values("d").groupby(["week", "c"])["v"].last().unstack().sort_index()
    w = w[w.index >= LONG_START]
    r = w.pct_change(fill_method=None)
    gap = pd.Series(w.index).diff().dt.days.fillna(7).to_numpy()
    return r[gap <= 14].rename(columns={EW_INDEX: "equal_weight", TOTAL_INDEX: "total"})


def gold_funds(lv: pd.DataFrame, ch: pd.DataFrame) -> dict:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select i.symbol_fa, p.date, p.close from prices_daily p join instruments i "
            "on i.id = p.instrument_id where i.instrument_type = 'etf_commodity' "
            "and (i.name_fa like '%طلا%' or i.symbol_fa in ('عیار','طلا','گوهر','کهربا'))"
        ).fetchall()
    df = pd.DataFrame(rows, columns=["s", "d", "v"])
    df["d"] = pd.to_datetime(df["d"])
    df = df[df["v"] > 0]
    df["week"] = (df["d"] + pd.Timedelta(days=2)).dt.to_period("W-SUN").dt.start_time
    w = df.sort_values("d").groupby(["week", "s"])["v"].last().unstack().sort_index()
    r = w.pct_change(fill_method=None).clip(-0.5, 0.5)
    start = lv.index[-1] - pd.Timedelta(days=1095)
    out = {}
    for s in r.columns:
        y = r[s][r.index >= start]
        if y.notna().sum() < 60:
            continue
        out[s] = {
            "weeks": int(y.notna().sum()),
            "corr_gold_18k": corr(y, ch["gold_18k"]),
            "corr_coin": corr(y, ch["coin_emami"]),
            "corr_ounce_rial": corr(y, ch["ounce_rial"]),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["weeks"]))


def main() -> None:
    lv = levels()
    ch = changes(lv)
    out: dict = {"levels": level_summary(lv)}

    # last three years, liquid universe (same as correlation_map)
    p, _ = tr.load()
    sector, _symbol, _links = cm.meta()
    r, uni = cm.weekly(p)
    m = r.mean(axis=1)
    mid = r.index[len(r) // 2]
    si = cm.sectors_index(r, sector)
    res = cm.residuals(si, m)
    ch3 = ch.reindex(r.index)
    out["recent"] = {
        "start": str(r.index[0].date()),
        "mid": str(mid.date()),
        "weeks": len(r),
        "stocks": len(uni),
        "same_week": same_week(m, res, ch3, mid),
        "market_leads": lead_tests(m, ch3, mid),
        "industry_spreads": spread_leads(res, ch3, mid),
    }

    # long check on the equal-weight and total index
    iw = index_weekly()
    chl = ch.reindex(iw.index)
    lmid = iw.index[len(iw) // 2]
    out["long"] = {
        "start": str(iw.index[0].date()),
        "mid": str(lmid.date()),
        "weeks": len(iw),
        "same_week": {
            k: {x: {h: corr(iw[k][mask], chl[x][mask]) for h, mask in halves(iw.index, lmid)} for x in chl.columns}
            for k in ("equal_weight", "total")
        },
        "market_leads": {k: lead_tests(iw[k], chl, lmid) for k in ("equal_weight", "total")},
    }
    lvmid = lv.index[len(lv) // 2]
    out["reversion"] = {"mid": str(lvmid.date()), **reversion(lv, lvmid)}
    out["gold_funds"] = gold_funds(lv, ch)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    for x, v in out["levels"].items():
        print(x, {k: v[k] for k in v if k != "by_year"})
    print("market same week", out["recent"]["same_week"]["market"])
    for x, v in out["recent"]["market_leads"].items():
        print("lead", x, v)
    for x, v in out["recent"]["industry_spreads"].items():
        print("spread", x, {k: w for k, w in v.items()})
    for k in ("equal_weight", "total"):
        for x, v in out["long"]["market_leads"][k].items():
            print("long", k, x, v)
    print("reversion", out["reversion"])
    print("funds", out["gold_funds"])


if __name__ == "__main__":
    main()
