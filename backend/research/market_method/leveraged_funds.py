"""Are leveraged funds a way to earn about 10% a month? (docs/reports/leveraged-funds-2026-11.md)

Owner's observation: the leveraged funds (type "سهامی اهرمی") look excellent and could earn 10% a
month. Tested here on their daily closes, never on a forecast:

1. Per fund: beta and correlation against the main index (TEPIX), yearly volatility, daily alpha
   after beta with its t, the distribution of the next-21-session return (share at or above +10%,
   below 0, below -10%), and the worst fall from a peak.
2. Fund types side by side over the last three years (equal-weight daily-rebalanced baskets of the
   liquid funds): mean, median and compound monthly return, worst 21 sessions, worst fall.
3. Timing rules on the leveraged basket, judged in both halves of time with a round-trip cost:
   index above its 50/100/200-day average and basket above its own 50-day average. A circular
   shift placebo keeps the exposure share and breaks the timing.
4. The last 21 sessions: how far each fund moved against what its beta to the index predicts.
5. Price against fund NAV today (fipiran), only as a snapshot: NAV history is four days.

Prices are the exchange closes (these funds have no price adjustments). Descriptive. Not advice.
Run from backend/ with the live env: python research/market_method/leveraged_funds.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "results_leveraged_funds.json"
DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
TEPIX = "32097828799138957"
EQUAL_WEIGHT = "67130298613737946"  # the equal-weight total index
H = 21  # one month of sessions
COST = 0.003  # round trip for a fund, rounded up
THREE_YEARS = "2023-11-01"
MIN_VALUE = 1e10  # a fund counts as liquid above 1 billion toman a day (values are in rials)
SEED = 7


def _round(x: float, n: int = 2) -> float:
    return float(np.round(x, n))


def fwd(s: pd.Series) -> pd.Series:
    return (s.shift(-H) / s - 1).dropna()


def per_fund(w: pd.DataFrame, ix: pd.Series, ew: pd.Series) -> list[dict]:
    r, rm, re_ = w.pct_change(), ix.pct_change(), ew.pct_change()
    rows = []
    for s in w.columns:
        x = pd.concat([r[s], rm], axis=1).dropna()
        x.columns = ["f", "m"]
        beta = float(np.cov(x.f, x.m)[0, 1] / x.m.var())
        alpha = float(x.f.mean() - beta * x.m.mean())
        resid = x.f - alpha - beta * x.m
        y = pd.concat([r[s], re_], axis=1).dropna()
        y.columns = ["f", "m"]
        f = fwd(w[s])
        m = fwd(ix).reindex(f.index)
        q = w[s].dropna()
        dd = q / q.cummax() - 1
        rows.append(
            {
                "fund": s,
                "days": len(x),
                "since": str(q.index[0]),
                "beta": _round(beta),
                "corr": _round(x.f.corr(x.m)),
                "beta_equal_weight": _round(np.cov(y.f, y.m)[0, 1] / y.m.var()),
                "corr_equal_weight": _round(y.f.corr(y.m)),
                "vol_year_pct": _round(x.f.std() * np.sqrt(250) * 100, 0),
                "alpha_year_pct": _round(alpha * 250 * 100, 0),
                "alpha_t": _round(alpha / (resid.std() / np.sqrt(len(x))), 1),
                "m21_mean_pct": _round(f.mean() * 100, 1),
                "m21_median_pct": _round(f.median() * 100, 1),
                "p_ge_10": _round((f >= 0.10).mean() * 100, 0),
                "p_lt_0": _round((f < 0).mean() * 100, 0),
                "p_lt_m10": _round((f < -0.10).mean() * 100, 0),
                "worst21_pct": _round(f.min() * 100, 0),
                "excess_vs_index_mean_pct": _round((f - m).mean() * 100, 1),
                "max_dd_pct": _round(dd.min() * 100, 0),
            }
        )
    return rows


def stats(x: pd.Series) -> dict:
    eq = (1 + x).cumprod()
    return {
        "x": _round(eq.iloc[-1]),
        "cagr_pct": _round((eq.iloc[-1] ** (250 / len(x)) - 1) * 100, 0),
        "max_dd_pct": _round((eq / eq.cummax() - 1).min() * 100, 0),
    }


def timing(w: pd.DataFrame, ix: pd.Series) -> dict:
    bk = w.pct_change().mean(axis=1).loc["2022-11-06":]
    eq = (1 + bk).cumprod()
    sigs = {"buy_and_hold": pd.Series(1.0, index=bk.index)}
    for n in (50, 100, 200):
        sigs[f"index_above_sma{n}"] = (ix > ix.rolling(n).mean()).astype(float).reindex(bk.index)
    sigs["basket_above_sma50"] = (eq > eq.rolling(50).mean()).astype(float)
    mid = bk.index[len(bk) // 2]
    out: dict = {"start": str(bk.index[0]), "split": str(mid), "rules": {}}
    for name, s in sigs.items():
        pos = s.shift(1).fillna(0)  # decided at the close of t, held through t+1
        net = pos * bk - pos.diff().abs().fillna(0) * COST / 2 if name != "buy_and_hold" else bk
        out["rules"][name] = {
            "in_market_pct": _round(pos.mean() * 100, 0),
            "switches_per_year": _round(pos.diff().abs().sum() / (len(bk) / 250), 1),
            "all": stats(net),
            "half1": stats(net.loc[:mid]),
            "half2": stats(net.loc[mid:]),
        }
    pos = sigs["index_above_sma200"].shift(1).fillna(0).to_numpy()
    real = stats(pos * bk - pd.Series(pos, index=bk.index).diff().abs().fillna(0) * COST / 2)["x"]
    rng = np.random.default_rng(SEED)
    hits = 0
    for _ in range(500):
        rp = np.roll(pos, int(rng.integers(20, len(bk) - 20)))
        net = pd.Series(rp * bk.to_numpy() - np.abs(np.diff(rp, prepend=rp[0])) * COST / 2)
        hits += stats(net)["x"] >= real
    out["placebo_sma200_share_at_or_above_real_pct"] = _round(hits / 500 * 100, 0)
    f = fwd(eq)
    out["basket_m21"] = {
        "mean_pct": _round(f.mean() * 100, 1),
        "median_pct": _round(f.median() * 100, 1),
        "p_ge_10": _round((f >= 0.10).mean() * 100, 0),
        "p_lt_0": _round((f < 0).mean() * 100, 0),
        "p_lt_m10": _round((f < -0.10).mean() * 100, 0),
        "geo_month_pct": _round((eq.iloc[-1] ** (H / len(eq)) - 1) * 100, 1),
    }
    return out


def by_type(c: sqlite3.Connection) -> list[dict]:
    ins = pd.read_sql(
        "select id, instrument_type t from instruments where instrument_type in "
        "('etf_equity','etf_leveraged','etf_mixed','etf_fixed_income','etf_commodity')",
        c,
    )
    p = pd.read_sql(
        "select instrument_id i, date d, close, value from prices_daily where date >= ?",
        c,
        params=[THREE_YEARS],
    )
    p = p[p.i.isin(ins.id)]
    w = p.pivot(index="d", columns="i", values="close")
    v = p.pivot(index="d", columns="i", values="value")
    t = dict(zip(ins.id, ins.t, strict=True))
    ok = [i for i in w.columns if w[i].notna().sum() >= 500 and v[i].tail(60).median() > MIN_VALUE]
    rows = []
    for ty in sorted({t[i] for i in ok}):
        cols = [i for i in ok if t[i] == ty]
        r = w[cols].pct_change().clip(-0.2, 0.2).mean(axis=1).fillna(0)
        eq = (1 + r).cumprod()
        f = fwd(eq)
        own = [
            (w[i].dropna().iloc[-1] / w[i].dropna().iloc[0]) ** (H / w[i].notna().sum()) - 1
            for i in cols
        ]
        rows.append(
            {
                "type": ty,
                "funds": len(cols),
                "m21_mean_pct": _round(f.mean() * 100, 1),
                "m21_median_pct": _round(f.median() * 100, 1),
                "p_ge_10": _round((f >= 0.10).mean() * 100, 0),
                "p_lt_0": _round((f < 0).mean() * 100, 0),
                "worst21_pct": _round(f.min() * 100, 0),
                "max_dd_pct": _round((eq / eq.cummax() - 1).min() * 100, 0),
                "geo_month_pct": _round((eq.iloc[-1] ** (H / len(eq)) - 1) * 100, 1),
                "best_single_fund_geo_month_pct": _round(max(own) * 100, 1),
                "funds_with_geo_month_ge_10": int(sum(o >= 0.10 for o in own)),
            }
        )
    return rows


def recent(w: pd.DataFrame, ix: pd.Series, ew: pd.Series, betas: dict[str, float]) -> dict:
    ret = {s: w[s].iloc[-1] / w[s].iloc[-1 - H] - 1 for s in w.columns}
    idx = ix.iloc[-1] / ix.iloc[-1 - H] - 1
    idx_ew = ew.iloc[-1] / ew.iloc[-1 - H] - 1
    return {
        "from": str(w.index[-1 - H]),
        "to": str(w.index[-1]),
        "index_pct": _round(idx * 100, 1),
        "equal_weight_index_pct": _round(idx_ew * 100, 1),
        "funds": {
            s: {
                "ret_pct": _round(ret[s] * 100, 1),
                "implied_by_beta_pct": _round(betas[s] * idx * 100, 1),
                "implied_by_equal_weight_beta_pct": _round(betas[s + "|ew"] * idx_ew * 100, 1),
            }
            for s in w.columns
        },
    }


def nav_snapshot(c: sqlite3.Connection, ids: list[int]) -> list[dict]:
    q = (
        "select f.instrument_id i, i.symbol_fa s, max(f.date) d, f.cancel_nav nav "
        "from fund_nav f join instruments i on i.id = f.instrument_id "
        f"where f.instrument_id in ({','.join(map(str, ids))}) group by f.instrument_id"
    )
    out = []
    for r in pd.read_sql(q, c).itertuples():
        px = c.execute(
            "select close from prices_daily where instrument_id = ? and date <= ? "
            "order by date desc limit 1",
            (int(r.i), r.d),
        ).fetchone()
        if px and r.nav:
            out.append(
                {
                    "fund": r.s,
                    "nav_date": r.d,
                    "price": px[0],
                    "fund_nav": r.nav,
                    "price_over_nav": _round(px[0] / r.nav, 2),
                }
            )
    return out


def main() -> None:
    c = sqlite3.connect(DB, uri=True)
    lev = pd.read_sql(
        "select id, symbol_fa from instruments where instrument_type = 'etf_leveraged' "
        "and id in (select instrument_id from prices_daily group by 1 having count(*) > 250)",
        c,
    )
    p = pd.read_sql(
        "select instrument_id i, date d, close from prices_daily "
        f"where instrument_id in ({','.join(map(str, lev.id))}) order by 1, 2",
        c,
    )
    name = dict(zip(lev.id, lev.symbol_fa, strict=True))
    w = p.pivot(index="d", columns="i", values="close").rename(columns=name)
    ix = (
        pd.read_sql(
            "select date d, close from market_index_daily where index_code = ? order by 1",
            c,
            params=[TEPIX],
        )
        .set_index("d")["close"]
        .reindex(w.index)
        .ffill()
    )
    ew = (
        pd.read_sql(
            "select date d, close from market_index_daily where index_code = ? order by 1",
            c,
            params=[EQUAL_WEIGHT],
        )
        .set_index("d")["close"]
        .reindex(w.index)
        .ffill()
    )
    funds = per_fund(w, ix, ew)
    betas = {f["fund"]: f["beta"] for f in funds}
    betas |= {f["fund"] + "|ew": f["beta_equal_weight"] for f in funds}
    res = {
        "days": len(w),
        "first_day": str(w.index[0]),
        "last_day": str(w.index[-1]),
        "index_x_over_period": _round(ix.iloc[-1] / ix.iloc[0]),
        "index_max_dd_pct": _round(((ix / ix.cummax()) - 1).min() * 100, 0),
        "funds": funds,
        "timing": timing(w, ix),
        "types_3y": by_type(c),
        "recent": recent(w, ix, ew, betas),
        "nav_snapshot": nav_snapshot(c, [int(i) for i in lev.id]),
    }
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
