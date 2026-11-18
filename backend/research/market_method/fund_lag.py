"""Do sector funds lag their industry? (docs/reports/fund-lag-2026-11.md)

Idea from the owner: an industry rises or falls and its sector fund follows a day or more later,
so the gap is a buy (or sell) signal. Tested on daily adjusted closes since START, judged in both
halves of time with costs, entering at the next day's open (the price a person can get after
seeing today's close).

Fund -> industry: the fund's official type ("سهامی بخشی در صنعت ...") when TSETMC has it;
otherwise a fixed name-based map below (checked against daily co-movement). Funds whose industry
stays unclear are left out.

Industry return on a day: market-cap weighted mean of the industry's stocks that traded that day
(weights from today's share count, a small look-ahead that only sets weights). Daily NAV history
is not in the database, so the fund's own price is compared with its industry, not with its NAV.

Signals at the close of day t, for k in (1, 3, 5):
    gap_k = industry return over the last k days - fund return over the same days
Targets:
    open_h  = fund return from the open of t+1 to the close of t+h   (tradable)
    close_1 = fund return from the close of t to the close of t+1     (includes the open jump)
    rel_h   = open_h minus the industry's return over the same window (catch-up, not trend)
Statistics: daily cross-sectional correlation of signal and target across funds, mean and t over
days (Fama-MacBeth), per half; partial version that also holds the fund's own last-k return.
Trades: buy when gap_k is above the half-1 80th percentile, open t+1 to close t+h, net of COST;
compared with every fund-day (same windows) and with random picks of the same size.

Descriptive. Not advice. Run from backend/ with the live env:
python research/market_method/fund_lag.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from fundamentals_study import DB  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
START = date.fromisoformat(os.environ.get("LAG_START", "2023-11-01"))
OUT = HERE / "results_fund_lag.json"
COST = 0.002  # fund round trip: broker and exchange fees about 0.1% a side, rounded up
KS = (1, 3, 5)
HS = (1, 3, 5)
SEED = 7

DESC_KEYS = {
    "بانک": "57",
    "پتروشیمی": "44",
    "شیمیایی": "44",
    "فلزات اساسی": "27",
    "دارویی": "43",
    "غذایی": "42",
    "خودرو": "34",
    "سیمان": "53",
    "کانه": "13",
    "بیمه": "66",
    "برق": "40",
    "فرآورده های نفتی": "23",
}
# funds without an official type; the name and the daily co-movement agree on the industry
BY_NAME = {
    "امگا": "40",
    "یوتیلیتی": "40",
    "ولتاژ": "40",
    "نفتوداریوش": "23",
    "آلکان": "44",
    "سیمان": "53",
    "سمنتوداریوش": "53",
    "فرا الگوریتم": "42",
    "نمک": "42",
    "طعام": "42",
    "پناه": "66",
    "بنکوداریوش": "57",
    "فارمانی": "43",
    "ناوگان": "60",
    "پولاد": "27",
}


def meta() -> tuple[
    dict[int, str], dict[int, str], dict[int, str], dict[int, float], dict[str, str]
]:
    """fund id -> industry code, stock id -> industry code, id -> symbol, stock id -> shares,
    industry code -> name."""
    con = sqlite3.connect(DB, uri=True)
    fund_ind: dict[int, str] = {}
    stock_ind: dict[int, str] = {}
    sym: dict[int, str] = {}
    shares: dict[int, float] = {}
    for i, s, t, sec, tags in con.execute(
        "select id, symbol_fa, instrument_type, sector_code, tags from instruments "
        "where delisted_at is null"
    ):
        d = json.loads(tags or "{}")
        sym[i] = s
        if t == "stock" and sec:
            stock_ind[i] = sec
            if d.get("shares"):
                shares[i] = float(d["shares"])
        if t == "etf_equity" and (
            d.get("subsector_code") == "6819" or "بخشی" in (d.get("fund_desc") or "")
        ):
            if re.search(r"\d$", s):  # second listing of the same fund
                continue
            m = re.search(r"بخشی در صنعت\s*(.+)", d.get("fund_desc") or "")
            code = None
            if m:
                code = next((v for k, v in DESC_KEYS.items() if k in m.group(1)), None)
            code = code or BY_NAME.get(s)
            if code:
                fund_ind[i] = code
    names = dict(con.execute("select code, name from sector_names"))
    return fund_ind, stock_ind, sym, shares, names


def load(ids: set[int]) -> pd.DataFrame:
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    p = (
        apply_adjustments(prices)
        .filter(C(G).is_in(list(ids)) & ~C("market_halt") & (C("close") > 0))
        .with_columns(C("date").cast(pl.Date))
        .filter(C("date") >= START)
        .sort(G, "date")
    )
    # adj_open on the same scale as adj_close
    p = p.with_columns(adj_open=C("open") * C("adj_close") / C("close"))
    return p.select(G, "date", "adj_open", "adj_close", "close", "volume").to_pandas()


def industry_returns(
    ret: pd.DataFrame, stock_ind: dict[int, str], cap: dict[int, float]
) -> pd.DataFrame:
    out = {}
    for code in sorted(set(stock_ind.values())):
        cols = [i for i in ret.columns if stock_ind.get(i) == code and i in cap]
        if len(cols) < 3:
            continue
        w = pd.Series({i: cap[i] for i in cols})
        r = ret[cols]
        ww = r.notna().mul(w, axis=1)
        out[code] = r.fillna(0).mul(w, axis=1).sum(axis=1) / ww.sum(axis=1).replace(0, np.nan)
    return pd.DataFrame(out)


def fm(
    sig: pd.DataFrame, tgt: pd.DataFrame, days: pd.Index, ctrl: pd.DataFrame | None = None
) -> dict:
    """Mean over days of the cross-sectional correlation (or partial correlation) across funds."""
    vals = []
    for d in days:
        x, y = sig.loc[d], tgt.loc[d]
        ok = x.notna() & y.notna()
        if ctrl is not None:
            z = ctrl.loc[d]
            ok &= z.notna()
        if ok.sum() < 8:
            continue
        x, y = x[ok], y[ok]
        if ctrl is not None:
            z = z[ok]
            zz = np.c_[np.ones(len(z)), z.to_numpy()]
            x = x - zz @ np.linalg.lstsq(zz, x.to_numpy(), rcond=None)[0]
            y = y - zz @ np.linalg.lstsq(zz, y.to_numpy(), rcond=None)[0]
        if x.std() == 0 or y.std() == 0:
            continue
        vals.append(float(np.corrcoef(x, y)[0, 1]))
    v = np.array(vals)
    if len(v) < 20:
        return {"n": len(v)}
    return {
        "ic": round(v.mean(), 4),
        "t": round(v.mean() / v.std(ddof=1) * np.sqrt(len(v)), 2),
        "n": len(v),
    }


def pooled_beta(sig: pd.DataFrame, tgt: pd.DataFrame, days: pd.Index) -> dict:
    """Slope of target on signal, all fund-days pooled; how much of a 1-unit gap comes back."""
    x = sig.loc[days].stack()
    y = tgt.loc[days].stack()
    j = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
    if len(j) < 100:
        return {"n": len(j)}
    b = np.cov(j.x, j.y)[0, 1] / j.x.var()
    return {"beta": round(float(b), 3), "n": len(j)}


def trades(
    sig: pd.DataFrame, tgt: pd.DataFrame, days: pd.Index, cut: float, rng, h: int, rel: pd.DataFrame
) -> dict:
    s, t, r = sig.loc[days], tgt.loc[days], rel.loc[days]
    pick = (s > cut) & t.notna()
    got = t[pick].stack().dropna()
    every = t[s.notna() & t.notna()].stack().dropna()
    if len(got) < 30:
        return {"n": len(got)}
    rand = [float(rng.choice(every.to_numpy(), len(got)).mean()) for _ in range(500)]
    net = got - COST
    # one trade a day per signal: group by day so a busy day counts once in the t-stat
    by_day = net.groupby(level=0).mean()
    # excess over all funds that same day; keep every h-th day so holding windows do not overlap
    ex = (got.groupby(level=0).mean() - every.groupby(level=0).mean()).dropna()
    ex_n = ex.iloc[::h]
    rel_got = r[pick].stack().dropna()
    rel_day = rel_got.groupby(level=0).mean().iloc[::h]
    return {
        "n": len(got),
        "days": len(by_day),
        "mean_net": round(float(net.mean()), 4),
        "hit": round(float((net > 0).mean()), 3),
        "t_by_day": round(float(by_day.mean() / by_day.std(ddof=1) * np.sqrt(len(by_day))), 2),
        "all_mean_net": round(float(every.mean() - COST), 4),
        "random_p95_net": round(float(np.percentile(rand, 95) - COST), 4),
        "excess_vs_all": round(float(ex.mean()), 4),
        "t_excess_nonoverlap": round(float(ex_n.mean() / ex_n.std(ddof=1) * np.sqrt(len(ex_n))), 2),
        "vs_industry": round(float(rel_got.mean()), 4),
        "t_vs_industry_nonoverlap": round(
            float(rel_day.mean() / rel_day.std(ddof=1) * np.sqrt(len(rel_day))), 2
        ),
    }


def main() -> None:
    fund_ind, stock_ind, sym, shares, names = meta()
    ids = set(fund_ind) | set(stock_ind)
    p = load(ids)
    close = p.pivot(index="date", columns=G, values="adj_close").sort_index()
    opn = p.pivot(index="date", columns=G, values="adj_open").reindex(close.index)
    vol = p.pivot(index="date", columns=G, values="volume").reindex(close.index)
    raw = p.pivot(index="date", columns=G, values="close").reindex(close.index)
    ret = (close / close.shift(1) - 1).clip(-0.25, 0.25)
    last_cap = {
        i: shares[i] * raw[i].dropna().iloc[-1] for i in shares if i in raw and raw[i].notna().any()
    }
    ind = industry_returns(ret[[c for c in ret.columns if c in stock_ind]], stock_ind, last_cap)

    funds = [f for f in fund_ind if f in close.columns and fund_ind[f] in ind.columns]
    fr = ret[funds]
    # a fund that did not trade has no return that day (no stale zero)
    fr = fr.where(vol[funds].fillna(0) > 0)
    ir = pd.DataFrame({f: ind[fund_ind[f]] for f in funds})
    days = close.index
    mid = days[len(days) // 2]
    h1, h2 = days[days < mid], days[days >= mid]

    sig, own = {}, {}
    for k in KS:
        sig[k] = ir.rolling(k).sum() - fr.rolling(k, min_periods=k).sum()
        own[k] = fr.rolling(k, min_periods=k).sum()
    tgt, rel = {}, {}
    fc, fo = close[funds], opn[funds]
    for h in HS:
        tgt[h] = (fc.shift(-h) / fo.shift(-1) - 1).clip(-0.4, 0.4)
        # industry over the same window, close t -> close t+h (fund open t+1 ~ close t)
        rel[h] = tgt[h] - ir.shift(-1).rolling(h).sum().shift(-(h - 1))
    close1 = fr.shift(-1)

    out: dict = {
        "start": str(START),
        "mid": str(mid.date()),
        "end": str(days[-1].date()),
        "funds": len(funds),
        "fund_list": {sym[f]: names.get(fund_ind[f], fund_ind[f]) for f in funds},
        "cost": COST,
    }
    # how closely funds track their industry the same day and the next
    same = [fr[f].corr(ir[f]) for f in funds]
    nxt = [fr[f].shift(-1).corr(ir[f]) for f in funds]
    out["corr_same_day_median"] = round(float(np.nanmedian(same)), 3)
    out["corr_industry_today_fund_tomorrow_median"] = round(float(np.nanmedian(nxt)), 3)

    rng = np.random.default_rng(SEED)
    res: dict = {}
    for k in KS:
        for half, dd in (("h1", h1), ("h2", h2)):
            r: dict = {}
            r["close_1"] = fm(sig[k], close1, dd)
            for h in HS:
                r[f"open_{h}"] = fm(sig[k], tgt[h], dd)
                r[f"open_{h}_partial_own"] = fm(sig[k], tgt[h], dd, own[k])
                r[f"rel_{h}"] = fm(sig[k], rel[h], dd)
            r["beta_close_1"] = pooled_beta(sig[k], close1, dd)
            r["beta_open_1"] = pooled_beta(sig[k], tgt[1], dd)
            res[f"k{k}_{half}"] = r
    out["ic"] = res

    tr: dict = {}
    for k in KS:
        cut_hi = float(np.nanpercentile(sig[k].loc[h1].stack(), 80))
        cut_lo = float(np.nanpercentile(sig[k].loc[h1].stack(), 20))
        for h in HS:
            for half, dd in (("h1", h1), ("h2", h2)):
                tr[f"k{k}_h{h}_{half}_buy_lagging"] = {
                    "cut": round(cut_hi, 4),
                    **trades(sig[k], tgt[h], dd, cut_hi, rng, h, rel[h]),
                }
                tr[f"k{k}_h{h}_{half}_buy_ahead"] = {
                    "cut": round(cut_lo, 4),
                    **trades(-sig[k], tgt[h], dd, -cut_lo, rng, h, rel[h]),
                }
    out["trades"] = tr

    # per fund (k=1, open_1, both halves): who lags most consistently
    per = []
    for f in funds:
        row = {"symbol": sym[f], "industry": names.get(fund_ind[f])}
        for half, dd in (("h1", h1), ("h2", h2)):
            j = pd.concat(
                [sig[1][f].loc[dd], tgt[1][f].loc[dd], close1[f].loc[dd]],
                axis=1,
                keys=["s", "o", "c"],
            ).dropna()
            row[f"n_{half}"] = len(j)
            row[f"b_open_{half}"] = (
                round(float(np.cov(j.s, j.o)[0, 1] / j.s.var()), 3) if len(j) > 40 else None
            )
            row[f"b_close_{half}"] = (
                round(float(np.cov(j.s, j.c)[0, 1] / j.s.var()), 3) if len(j) > 40 else None
            )
            # catch-up against the industry: 5-day gap -> next 5 days relative to the industry
            q = (
                pd.concat([sig[5][f].loc[dd], rel[5][f].loc[dd]], axis=1, keys=["s", "r"])
                .dropna()
                .iloc[::5]
            )
            row[f"b_catchup5_{half}"] = (
                round(float(np.cov(q.s, q.r)[0, 1] / q.s.var()), 3) if len(q) > 25 else None
            )
        row["same_day_corr"] = round(float(fr[f].corr(ir[f])), 3)
        row["median_value_bt"] = round(float((raw[f] * vol[f]).loc[days[-60:]].median() / 1e10), 1)
        per.append(row)
    out["per_fund"] = sorted(per, key=lambda r: -(r["b_open_h1"] or -9))

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print({k: v for k, v in out.items() if k not in ("ic", "trades", "per_fund", "fund_list")})
    for k, v in res.items():
        print(k, v)
    for k, v in tr.items():
        print(k, v)
    for r in out["per_fund"]:
        print(r)


if __name__ == "__main__":
    main()
