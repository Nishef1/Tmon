"""How stocks, their listed parents and industries move together, and whether any of it leads
(docs/reports/correlation-map-2026-11.md)

Universe: stocks in the point-in-time top 300 on at least 60% of trading days since START.
Returns are weekly (Saturday to Wednesday), from the adjusted close, because daily returns are
held back by the price limit and queues. Weeks that follow a gap of more than 14 days (the
1404-1405 closure) are dropped, since one return then covers months.

1. Stocks: mean pair correlation, raw and after removing the equal-weight market; the share of
   variance in the first factor and the effective number of independent bets; correlation in
   down weeks against up weeks; how it changed over time; the closest pairs; clusters of the
   residual correlation and how well the official industry explains them.
2. Parents: a holder in today's shareholder list whose name matches a listed company. Residual
   correlation of parent and child against random pairs of the same industries. The shareholder
   list is one snapshot (1405), so older links may differ.
3. Industries: equal-weight weekly index of members with at least 3 stocks. Correlation, raw and
   residual, and each industry's link to the free-market dollar, Brent and gold.
4. Lead and lag, judged in both halves (cut points and pair picks from half 1 only):
   a. a stock whose industry rose last week while it did not: does it catch up next week?
   b. a parent whose listed children rose last week more than it did: does it follow?
   c. industry pairs where one led the other in half 1: does it hold in half 2?
   d. the most correlated pairs in half 1: does a 4-week gap between them close in the next 4?
   Weekly turnover costs about 1.75% a round trip in this market; the lead-lag numbers are gross.

Descriptive. Not advice. Run from backend/ with the live env:
python research/market_method/correlation_map.py  (CORR_START=2010-01-01 for the long check)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("TREND_TOP", "300")

import numpy as np
import pandas as pd
import polars as pl
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import adjusted_rand_score

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import trend_ride as tr  # noqa: E402
from fundamentals_study import DB  # noqa: E402

C = pl.col
G = "instrument_id"
START = date.fromisoformat(os.environ.get("CORR_START", "2023-11-01"))
SUFFIX = "" if "CORR_START" not in os.environ else f"_{START.year}"
OUT = HERE / f"results_correlation{SUFFIX}.json"
MIN_MEMBER = 0.6
MIN_PARENT_PCT = 5.0
WATCH = ("درازک", "شکام", "دزاگرس", "شبهرن", "فولاد", "فملی", "خودرو", "شستا")


def norm(s: str) -> str:
    s = s.replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace("ة", "ه")
    return re.sub(r"سهامی\s*(عام|خاص)|شرکت|[()\-.،]|\s+", "", s)


def meta() -> tuple[dict[int, str], dict[int, str], list[tuple[int, int, float]]]:
    """Sector name per stock, symbol per stock, and (parent, child, percent) links."""
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select i.id, i.symbol_fa, i.name_fa, coalesce(n.name, i.sector_code) "
            "from instruments i left join sector_names n on n.code = i.sector_code "
            "where i.instrument_type = 'stock'"
        ).fetchall()
        hold = db.execute("select instrument_id, name, percent from shareholders").fetchall()
    sector = {i: s for i, _, _, s in rows}
    symbol = {i: sym for i, sym, _, _ in rows}
    by_name: dict[str, list[int]] = {}
    for i, _, name, _ in rows:
        if name:
            by_name.setdefault(norm(name), []).append(i)
    links = [
        (pid, child, pct)
        for child, name, pct in hold
        if pct and pct >= MIN_PARENT_PCT
        for pid in by_name.get(norm(name), [])
        if pid != child
    ]
    return sector, symbol, links


def weekly(p: pl.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    """Weekly returns (rows: week, cols: instrument) of the universe."""
    p = p.filter(C("date") >= START - timedelta(days=10))
    share = (
        p.filter(C("date") >= START)
        .group_by(G)
        .agg(m=C("member").mean())
        .filter(C("m") >= MIN_MEMBER)
    )
    uni = share[G].to_list()
    w = (
        p.filter(C(G).is_in(uni))
        .with_columns(week=(C("date") + pl.duration(days=2)).dt.truncate("1w"))
        .group_by(G, "week")
        .agg(close=C("adj_close").last(), last_day=C("date").max())
        .sort(G, "week")
        .with_columns(ret=(C("close") / C("close").shift(1) - 1).over(G))
        .filter(C("week") >= START)
    )
    wide = w.to_pandas().pivot(index="week", columns=G, values="ret").sort_index()
    days = pd.Series(wide.index)
    gap = days.diff().dt.days
    wide = wide[(gap.fillna(7) <= 14).to_numpy()]
    return wide.clip(-0.6, 1.5), uni


def residuals(r: pd.DataFrame, m: pd.Series) -> pd.DataFrame:
    out = {}
    for col in r.columns:
        y = r[col]
        ok = y.notna() & m.notna()
        if ok.sum() < 20:
            continue
        b = np.cov(y[ok], m[ok])[0, 1] / m[ok].var()
        out[col] = y - b * m
    return pd.DataFrame(out)


def mean_offdiag(c: np.ndarray) -> float:
    n = c.shape[0]
    return float((np.nansum(c) - np.nansum(np.diag(c))) / (n * n - n))


def tstat(x: list[float]) -> dict[str, float]:
    a = np.array([v for v in x if np.isfinite(v)])
    if len(a) < 3:
        return {"n": len(a)}
    return {
        "n": len(a),
        "mean": round(float(a.mean()), 4),
        "t": round(float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))), 2),
    }


def stocks_block(r, m, res, sector, symbol) -> dict:
    out: dict = {}
    cr = r.corr(min_periods=40)
    ce = res.corr(min_periods=40)
    out["n_stocks"] = r.shape[1]
    out["n_weeks"] = r.shape[0]
    out["mean_corr_raw"] = round(mean_offdiag(cr.to_numpy()), 3)
    out["mean_corr_resid"] = round(mean_offdiag(ce.to_numpy()), 3)
    # eigen: share of the first factor, effective number of bets
    z = r.fillna(0).to_numpy()
    z = (z - z.mean(0)) / (z.std(0) + 1e-12)
    ev = np.sort(np.linalg.eigvalsh(np.corrcoef(z.T)))[::-1]
    ev = ev[ev > 0]
    out["first_factor_share"] = round(float(ev[0] / ev.sum()), 3)
    out["top5_factor_share"] = round(float(ev[:5].sum() / ev.sum()), 3)
    pn = ev / ev.sum()
    out["effective_bets"] = round(float(np.exp(-(pn * np.log(pn)).sum())), 1)
    # down vs up weeks: dispersion-based average correlation proxy per regime
    # when the market falls or rises, what share of stocks goes the same way
    for name, mask, side in (("down", m < -0.02, -1), ("up", m > 0.02, 1)):
        sub = r[mask.to_numpy()]
        same = (np.sign(sub) == side).sum(axis=1) / sub.notna().sum(axis=1)
        out[f"same_way_{name}_weeks"] = round(float(same.mean()), 3)
        out[f"n_{name}_weeks"] = int(mask.sum())
    # over time: half-year windows
    path = []
    weeks = r.index
    for k in range(0, len(weeks) - 25, 13):
        sub = r.iloc[k : k + 26]
        path.append(
            {
                "from": str(weeks[k].date()),
                "to": str(weeks[k + 25].date()),
                "mean_corr": round(mean_offdiag(sub.corr(min_periods=15).to_numpy()), 3),
                "market": round(float((1 + m.iloc[k : k + 26]).prod() - 1), 3),
            }
        )
    out["corr_path"] = path
    # same sector vs different
    cols = list(ce.columns)
    sec = np.array([sector.get(c) for c in cols])
    a = ce.to_numpy()
    same = sec[:, None] == sec[None, :]
    np.fill_diagonal(same, False)
    diff = ~same
    np.fill_diagonal(diff, False)
    out["resid_corr_same_sector"] = round(float(np.nanmean(a[same])), 3)
    out["resid_corr_other_sector"] = round(float(np.nanmean(a[diff])), 3)
    by_sec = {}
    for s in set(sec):
        idx = np.where(sec == s)[0]
        if len(idx) >= 3:
            blk = a[np.ix_(idx, idx)]
            by_sec[s] = {"n": len(idx), "resid_corr": round(mean_offdiag(blk), 3)}
    out["resid_corr_by_sector"] = dict(sorted(by_sec.items(), key=lambda kv: -kv[1]["resid_corr"]))
    # top pairs (residual)
    iu = np.triu_indices(len(cols), 1)
    vals = a[iu]
    order = np.argsort(-np.nan_to_num(vals, nan=-9))[:40]
    out["top_pairs_resid"] = [
        {
            "a": symbol[cols[iu[0][k]]],
            "b": symbol[cols[iu[1][k]]],
            "resid": round(float(vals[k]), 2),
            "raw": round(float(cr.iloc[iu[0][k], iu[1][k]]), 2),
            "same_sector": bool(sec[iu[0][k]] == sec[iu[1][k]]),
        }
        for k in order
    ]
    # clusters of residual correlation vs official sectors
    d = 1 - np.nan_to_num(a, nan=0.0)
    np.fill_diagonal(d, 0)
    lk = linkage(squareform(np.clip((d + d.T) / 2, 0, 2), checks=False), "average")
    nsec = len(set(sec))
    lab = fcluster(lk, t=nsec, criterion="maxclust")
    out["cluster_vs_sector_ari"] = round(float(adjusted_rand_score(sec, lab)), 3)
    groups = {}
    for c, g in zip(cols, lab, strict=True):
        groups.setdefault(int(g), []).append(c)
    clusters = []
    for g in sorted(groups.values(), key=len, reverse=True):
        if len(g) < 3:
            continue
        idx = [cols.index(c) for c in g]
        secs = pd.Series([sector.get(c) for c in g]).value_counts()
        clusters.append(
            {
                "n": len(g),
                "resid_corr": round(mean_offdiag(a[np.ix_(idx, idx)]), 3),
                "main_sector": secs.index[0],
                "main_share": round(float(secs.iloc[0] / len(g)), 2),
                "symbols": [symbol[c] for c in g][:25],
            }
        )
    out["clusters"] = clusters[:25]
    # neighbours of watched symbols
    sym2id = {symbol[c]: c for c in cols}
    nb = {}
    for s in WATCH:
        if s in sym2id:
            row = ce[sym2id[s]].drop(sym2id[s]).dropna().sort_values(ascending=False)
            nb[s] = [{"s": symbol[k], "resid": round(float(v), 2)} for k, v in row.head(6).items()]
    out["neighbours"] = nb
    return out


def sectors_index(r: pd.DataFrame, sector: dict[int, str]) -> pd.DataFrame:
    sec = pd.Series({c: sector.get(c) for c in r.columns})
    keep = sec.value_counts()
    keep = keep[keep >= 3].index
    return pd.DataFrame({s: r[sec[sec == s].index].mean(axis=1) for s in keep})


def macro_weekly(index: pd.Index) -> pd.DataFrame:
    with sqlite3.connect(DB, uri=True) as db:
        rows = db.execute(
            "select series, ref_period, value from macro_series "
            "where series in ('usd_free','brent_usd','gold_usd','coin_emami')"
        ).fetchall()
    df = pd.DataFrame(rows, columns=["s", "d", "v"])
    df["d"] = pd.to_datetime(df["d"])
    # Thursday to Wednesday, so a week ends with the stock week's last session and the
    # Thursday-Friday dollar move counts toward the stock week that reacts to it.
    df["week"] = (df["d"] + pd.Timedelta(days=4)).dt.to_period("W-SUN").dt.start_time
    lv = df.sort_values("d").groupby(["week", "s"])["v"].last().unstack()
    return lv.pct_change().reindex(index)


def sectors_block(si: pd.DataFrame, m: pd.Series, mid) -> dict:
    out: dict = {"n_sectors": si.shape[1]}
    cr = si.corr(min_periods=40)
    res = residuals(si, m)
    ce = res.corr(min_periods=40)
    out["mean_corr_raw"] = round(mean_offdiag(cr.to_numpy()), 3)
    out["mean_corr_resid"] = round(mean_offdiag(ce.to_numpy()), 3)
    out["corr_raw"] = {a: {b: round(float(cr.loc[a, b]), 2) for b in cr.columns} for a in cr.index}
    out["corr_resid"] = {
        a: {b: round(float(ce.loc[a, b]), 2) for b in ce.columns} for a in ce.index
    }
    beta = {}
    for s in si.columns:
        y = si[s]
        ok = y.notna() & m.notna()
        beta[s] = round(float(np.cov(y[ok], m[ok])[0, 1] / m[ok].var()), 2)
    out["beta_to_market"] = dict(sorted(beta.items(), key=lambda kv: -kv[1]))
    mac = macro_weekly(si.index)
    links = {}
    for s in si.columns:
        if s not in res:
            continue
        e = res[s]
        row = {}
        for x in ("usd_free", "brent_usd", "gold_usd"):
            if x not in mac:
                continue
            for h, mask in (("h1", si.index < mid), ("h2", si.index >= mid)):
                a = pd.concat([e[mask], mac[x][mask]], axis=1).dropna()
                row[f"{x}_{h}"] = round(float(a.corr().iloc[0, 1]), 2) if len(a) > 20 else None
            # does the macro move of last week show up in this week's sector residual?
            for h, mask in (("h1", si.index < mid), ("h2", si.index >= mid)):
                a = pd.concat([e[mask], mac[x].shift(1)[mask]], axis=1).dropna()
                row[f"{x}_lag1_{h}"] = round(float(a.corr().iloc[0, 1]), 2) if len(a) > 20 else None
        links[s] = row
    out["macro_links_resid"] = links
    # dollar-linked industries picked on half 1 (same-week link), then last week's dollar
    # against this week's residual of that group, in each half
    if "usd_free" in mac:
        grp = [s for s, row in links.items() if (row.get("usd_free_h1") or 0) >= 0.15]
        anti = [s for s, row in links.items() if (row.get("usd_free_h1") or 0) <= -0.15]
        usd1 = mac["usd_free"].shift(1)
        blk: dict = {"exporters": grp, "dollar_losers": anti}
        for name, cols in (("exporters", grp), ("dollar_losers", anti)):
            if not cols:
                continue
            y = res[cols].mean(axis=1)
            for h, mask in (("h1", si.index < mid), ("h2", si.index >= mid)):
                a = pd.concat([y[mask], usd1[mask]], axis=1).dropna()
                up = a.iloc[:, 0][a.iloc[:, 1] > 0.02]
                rest = a.iloc[:, 0][a.iloc[:, 1] <= 0.02]
                blk[f"{name}_{h}"] = {
                    "corr_with_last_week_usd": round(float(a.corr().iloc[0, 1]), 2),
                    "after_usd_up_2pct": tstat(list(up)),
                    "other_weeks": tstat(list(rest)),
                }
        out["dollar_lead"] = blk
    mk = pd.concat([m, mac], axis=1).dropna()
    out["market_vs_macro"] = {
        x: round(float(mk.corr().iloc[0][x]), 2) for x in mac.columns if x in mk
    }
    out["market_vs_macro_lag1"] = {
        x: round(float(pd.concat([m, mac[x].shift(1)], axis=1).dropna().corr().iloc[0, 1]), 2)
        for x in mac.columns
    }
    return out


def ic_by_week(sig: pd.DataFrame, fwd: pd.DataFrame, mid) -> dict:
    """Weekly cross-section Spearman of signal with next-week return; mean and t by half."""
    out = {}
    ics, spreads = {"h1": [], "h2": []}, {"h1": [], "h2": []}
    for wk in sig.index:
        a = pd.concat([sig.loc[wk], fwd.loc[wk]], axis=1).dropna()
        if len(a) < 15:
            continue
        h = "h1" if wk < mid else "h2"
        ics[h].append(a.rank().corr().iloc[0, 1])
        q = a.iloc[:, 0].rank(pct=True)
        spreads[h].append(a.iloc[:, 1][q > 2 / 3].mean() - a.iloc[:, 1][q <= 1 / 3].mean())
    for h in ("h1", "h2"):
        out[f"ic_{h}"] = tstat(ics[h])
        out[f"top_minus_bottom_{h}"] = tstat(spreads[h])
    return out


def partial_ic(sig: pd.DataFrame, own: pd.DataFrame, fwd: pd.DataFrame, mid) -> dict:
    """Weekly rank regression of next-week return on own last week and the signal; the
    signal's coefficient tells whether it adds anything beyond the stock's own momentum."""
    co = {"h1": [], "h2": []}
    for wk in sig.index:
        a = pd.concat([own.loc[wk], sig.loc[wk], fwd.loc[wk]], axis=1).dropna()
        if len(a) < 15:
            continue
        z = a.rank(pct=True) - 0.5
        x = np.column_stack([np.ones(len(z)), z.iloc[:, 0], z.iloc[:, 1]])
        b = np.linalg.lstsq(x, z.iloc[:, 2].to_numpy(), rcond=None)[0]
        co["h1" if wk < mid else "h2"].append(b[2])
    return {f"beyond_own_{h}": tstat(v) for h, v in co.items()}


def tradable_momentum(p: pl.DataFrame, r: pd.DataFrame, mid) -> dict:
    """Own last-week return, bought at the close of the next trading day when that day is not
    locked at the limit, held 5 trading days. Top third against all eligible stocks."""
    d = (
        p.filter(C(G).is_in(list(r.columns)) & (C("date") >= START))
        .select(G, "date", "adj_close", "locked")
        .sort(G, "date")
        .with_columns(week=(C("date") + pl.duration(days=2)).dt.truncate("1w"))
        .with_columns(
            last_of_week=C("week") != C("week").shift(-1).over(G),
            entry=C("adj_close").shift(-1).over(G),
            entry_locked=C("locked").shift(-1).over(G),
            exit=C("adj_close").shift(-6).over(G),
        )
        .filter(C("last_of_week"))
        .to_pandas()
    )
    d["week"] = pd.to_datetime(d["week"])
    d["fwd"] = d["exit"] / d["entry"] - 1
    d = d[d["week"].isin(r.index)]
    own = r.stack().rename("own").reset_index().rename(columns={"level_1": G})
    d = d.merge(own, on=["week", G])
    rows = {"h1": [], "h2": []}
    locked_share = {"h1": [], "h2": []}
    for wk, g in d.groupby("week"):
        g = g.dropna(subset=["own"])
        if len(g) < 30:
            continue
        top = g[g["own"].rank(pct=True) > 2 / 3]
        h = "h1" if wk < mid else "h2"
        locked_share[h].append(float(top["entry_locked"].mean()))
        ok = g[~g["entry_locked"].astype(bool)].dropna(subset=["fwd"])
        tk = top[~top["entry_locked"].astype(bool)].dropna(subset=["fwd"])
        if len(tk) >= 5:
            rows[h].append(float(tk["fwd"].mean() - ok["fwd"].mean()))
    return {
        **{f"top_third_vs_all_{h}": tstat(v) for h, v in rows.items()},
        **{
            f"top_locked_at_entry_{h}": round(float(np.mean(v)), 3) for h, v in locked_share.items()
        },
        "round_trip_cost": tr.COST,
    }


def leadlag_block(r, m, si, sector, symbol, links, mid) -> dict:
    out: dict = {}
    ex = r.sub(m, axis=0)
    fwd = ex.shift(-1)
    # a. industry rose, stock did not
    sec = pd.Series({c: sector.get(c) for c in r.columns})
    sec_of = pd.DataFrame({c: si.get(sec[c], np.nan) for c in r.columns})
    gap = sec_of - r
    out["catch_up_industry"] = ic_by_week(gap, fwd, mid)
    # momentum and reversal of the stock itself for reference
    out["own_last_week"] = ic_by_week(r, fwd, mid)
    out["industry_last_week"] = ic_by_week(sec_of, fwd, mid)
    out["industry_last_week"].update(partial_ic(sec_of, r, fwd, mid))
    # b. parents: weighted children return minus own
    kids: dict[int, list[tuple[int, float]]] = {}
    for p, c, pct in links:
        if p in r.columns and c in r.columns:
            kids.setdefault(p, []).append((c, pct))
    if kids:
        kid_ret = pd.DataFrame(
            {
                p: sum(r[c].fillna(0) * w for c, w in ks) / sum(w for _, w in ks)
                for p, ks in kids.items()
            }
        )
        pg = kid_ret - r[list(kids)]
        out["parent_follows_children"] = ic_by_week(pg, fwd[list(kids)], mid)
        out["parent_follows_children"]["n_parents"] = len(kids)
        out["parent_follows_children"].update(
            partial_ic(kid_ret, r[list(kids)], fwd[list(kids)], mid)
        )
        # child follows parent
        par_of = {}
        for p, c, _pct in links:
            if p in r.columns and c in r.columns:
                par_of.setdefault(c, p)
        cg = pd.DataFrame({c: r[p] - r[c] for c, p in par_of.items()})
        out["child_follows_parent"] = ic_by_week(cg, fwd[list(par_of)], mid)
        out["child_follows_parent"]["n_children"] = len(par_of)
        pr = pd.DataFrame({c: r[p] for c, p in par_of.items()})
        out["child_follows_parent"].update(partial_ic(pr, r[list(par_of)], fwd[list(par_of)], mid))
    # c. industry pairs: lagged correlation picked on h1
    sres = residuals(si, m)
    h1 = sres.index < mid
    pairs = []
    for a in sres.columns:
        for b in sres.columns:
            if a == b:
                continue
            x1 = pd.concat([sres[a].shift(1)[h1], sres[b][h1]], axis=1).dropna()
            x2 = pd.concat([sres[a].shift(1)[~h1], sres[b][~h1]], axis=1).dropna()
            if len(x1) < 30 or len(x2) < 20:
                continue
            pairs.append((a, b, x1.corr().iloc[0, 1], x2.corr().iloc[0, 1]))
    pdf = pd.DataFrame(pairs, columns=["lead", "follow", "h1", "h2"])
    top = pdf.reindex(pdf["h1"].abs().sort_values(ascending=False).index).head(15)
    out["industry_lead_pairs"] = {
        "n_pairs": len(pdf),
        "corr_h1_h2_of_all_pairs": round(float(pdf[["h1", "h2"]].corr().iloc[0, 1]), 2),
        "top15_same_sign_in_h2": int((np.sign(top["h1"]) == np.sign(top["h2"])).sum()),
        "top15": top.round(2).to_dict("records"),
    }
    # d. pair gap reversal on the top residual pairs of h1
    res = residuals(r, m)
    c1 = res[res.index < mid].corr(min_periods=25)
    cols = list(c1.columns)
    a = c1.to_numpy()
    iu = np.triu_indices(len(cols), 1)
    order = np.argsort(-np.nan_to_num(a[iu], nan=-9))[:50]
    logp = np.log1p(r.fillna(0)).cumsum()
    rows = []
    laggard: list[float] = []
    for k in order:
        x, y = cols[iu[0][k]], cols[iu[1][k]]
        spread = logp[x] - logp[y]
        past = spread - spread.shift(4)
        nxt = spread.shift(-4) - spread
        df = pd.concat([past, nxt], axis=1).dropna()
        df = df[df.index >= mid].iloc[::4]
        if len(df) > 8:
            rows.append(
                {
                    "a": symbol[x],
                    "b": symbol[y],
                    "c_h1": round(float(a[iu[0][k], iu[1][k]]), 2),
                    "reversal_h2": round(float(-df.corr().iloc[0, 1]), 2),
                }
            )
        # long only: buy the pair's laggard of the last 4 weeks, hold 4 weeks, vs market
        exm = np.log1p(r[[x, y]].fillna(0).sub(m, axis=0)).cumsum()
        p4 = exm - exm.shift(4)
        n4 = exm.shift(-4) - exm
        for wk in p4.index[p4.index >= mid][::4]:
            if p4.loc[wk].isna().any() or n4.loc[wk].isna().any():
                continue
            gap = p4.loc[wk, x] - p4.loc[wk, y]
            if abs(gap) < 0.10:
                continue
            lag = y if gap > 0 else x
            laggard.append(float(np.expm1(n4.loc[wk, lag])))
    out["pair_gap_reversal_h2"] = {
        **tstat([x["reversal_h2"] for x in rows]),
        "pairs": rows[:20],
    }
    out["pair_laggard_4w_vs_market_h2"] = {**tstat(laggard), "gap_min": 0.10, "cost": tr.COST}
    return out


def parents_block(res, sector, symbol, links) -> dict:
    ce = res.corr(min_periods=40)
    cols = set(ce.columns)
    got = []
    for p, c, pct in links:
        if p in cols and c in cols:
            got.append(
                {
                    "parent": symbol[p],
                    "child": symbol[c],
                    "pct": round(pct, 1),
                    "same_sector": sector.get(p) == sector.get(c),
                    "resid": round(float(ce.loc[p, c]), 2),
                }
            )
    df = pd.DataFrame(got).drop_duplicates(["parent", "child"])
    # baseline: random pairs with the same sector pair
    rng = np.random.default_rng(0)
    by_sec: dict[str, list[int]] = {}
    for c in cols:
        by_sec.setdefault(sector.get(c), []).append(c)
    sym2id = {symbol[c]: c for c in cols}
    base = []
    for row in got:
        sp, sc = sector.get(sym2id[row["parent"]]), sector.get(sym2id[row["child"]])
        for _ in range(20):
            x, y = rng.choice(by_sec[sp]), rng.choice(by_sec[sc])
            if x != y:
                base.append(ce.loc[x, y])
    return {
        "n_links": len(df),
        "mean_resid_parent_child": round(float(df["resid"].mean()), 3),
        "mean_resid_same_sector_random": round(float(np.nanmean(base)), 3),
        "by_pct": {
            ">=20%": round(float(df[df.pct >= 20]["resid"].mean()), 3),
            "5-20%": round(float(df[df.pct < 20]["resid"].mean()), 3),
        },
        "links": df.sort_values("resid", ascending=False).to_dict("records")[:40],
    }


def main() -> None:
    p, _ids = tr.load()
    sector, symbol, links = meta()
    r, uni = weekly(p)
    m = r.mean(axis=1)
    mid = r.index[len(r) // 2]
    res = residuals(r, m)
    out: dict = {"start": str(START), "mid": str(mid.date()), "universe": len(uni)}
    out["stocks"] = stocks_block(r, m, res, sector, symbol)
    # daily corr for contrast (price limits hold daily moves back)
    d = (
        p.filter(C(G).is_in(list(r.columns)) & (C("date") >= START))
        .select(G, "date", "ret")
        .to_pandas()
        .pivot(index="date", columns=G, values="ret")
    )
    out["stocks"]["mean_corr_daily_raw"] = round(
        mean_offdiag(d.corr(min_periods=100).to_numpy()), 3
    )
    out["parents"] = parents_block(res, sector, symbol, links)
    si = sectors_index(r, sector)
    out["sectors"] = sectors_block(si, m, mid)
    out["leadlag"] = leadlag_block(r, m, si, sector, symbol, links, mid)
    out["leadlag"]["tradable_momentum"] = tradable_momentum(p, r, mid)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    s = out["stocks"]
    print({k: v for k, v in s.items() if not isinstance(v, (list, dict))})
    print("parents", {k: v for k, v in out["parents"].items() if k != "links"})
    print("sectors", out["sectors"]["mean_corr_raw"], out["sectors"]["mean_corr_resid"])
    print("macro", out["sectors"]["market_vs_macro"], out["sectors"]["market_vs_macro_lag1"])
    print("dollar_lead", out["sectors"].get("dollar_lead"))
    for k, v in out["leadlag"].items():
        if k not in ("industry_lead_pairs", "pair_gap_reversal_h2"):
            print(k, v)
    print(
        "industry pairs",
        {k: v for k, v in out["leadlag"]["industry_lead_pairs"].items() if k != "top15"},
    )
    print(
        "pair gap",
        {k: v for k, v in out["leadlag"]["pair_gap_reversal_h2"].items() if k != "pairs"},
    )


if __name__ == "__main__":
    main()
