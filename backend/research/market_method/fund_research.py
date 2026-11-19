"""Every stock study, redone on tradable funds. (docs/reports/fund-research-2026-11.md)

One panel, one judge, so the parts can be compared:

panel   every equity, mixed, sector, commodity (gold), leveraged and fixed-income fund with prices,
        adjusted closes. A day is "liquid" when the fund's median traded value of the 20 days up to
        it is at least 1 billion toman, decided that day (no look at today's list, so funds that
        died are in). A one-day move above 35% that the adjustment missed (unit-price change) cuts
        every forward return that spans it.
entry   close of the day after the signal (t+1); returns h = 5, 20, 60 trading days after that.
cost    0.3% round trip (fund), charged once per holding.
halves  calendar halves of the days with data; a result counts only if it holds in both.
t       on non-overlapping days (every h-th day), never on overlapping windows.

A  cross-section inside each group: rank correlation of each of the ~70 stock features (the
   technical, money-flow and board columns of tmon.features.builder) with the next h-day return,
   and top third minus the group, after cost. Pass = same sign and |t| >= 2 in both halves and the
   top third beats the group after cost in both. The same run on shuffled returns counts how many
   features pass by luck.
B  timing of each group as a whole (equal-weight index of its liquid funds) against always
   holding it: trend averages, the stock market's breadth regime (share of stocks above their
   60-day average), the overall index trend, drawdown from the high, RSI, retail money flow into
   the group, weekday and Persian month-turn calendar effects; for gold funds the move of 18k gold
   the day before and the fund's premium over 18k gold; rotation between groups by 60-day return.
C  machine learning: LightGBM per group, trained on the past only with an h-day gap before each
   test month (walk-forward), against the best single feature of the training window.

Run from backend/ with the live env (docs/14-local-run.md):
    python research/market_method/fund_research.py
Optional env FR_PANEL=<parquet> caches the feature panel. Output: results_fund_research.json
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import jdatetime
import lightgbm as lgb
import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.core.db import session_scope
from tmon.domain.rules import RuleBook
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import BOARD_COLUMNS, TECHNICAL_COLUMNS, build_features
from tmon.features.store import load_inputs
from tmon.storage.models import Instrument

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
OUT = HERE / "results_fund_research.json"
DB = os.environ.get("TMON_DATABASE_URL", "").removeprefix("sqlite:///")
CACHE = os.environ.get("FR_PANEL")
COST = 0.003
MIN_VALUE = 1e10  # rial, 1 billion toman
JUMP = 0.35
FIXED_DROP = -0.005  # a fixed-income day below -0.5% is a payout (1st percentile -1.5%)
HS = (5, 20, 60)
TEDPIX = "32097828799138957"
GROUP = {
    "etf_equity": "equity",
    "etf_mixed": "equity",
    "etf_leveraged": "leveraged",
    "etf_commodity": "gold",
    "etf_fixed_income": "fixed",
}
NOT_FEATURES = {"queue_code", "days_in_queue", "smart_money_flag"}  # constant or flags for funds
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- panel


def build() -> tuple[pl.DataFrame, pl.DataFrame]:
    """(fund panel with features and forward returns, stock breadth by day)."""
    with session_scope() as s:
        mp, mc, ms = load_inputs(s)
        cp, cc, cs = load_inputs(s, comparison_funds=True)
        rules = RuleBook.from_session(s)
        types = {i.id: i.instrument_type for i in s.scalars(select(Instrument))}
    kinds = {i: GROUP[t] for i, t in types.items() if t in GROUP}
    ids = list(kinds)
    prices = pl.concat([mp.filter(C(G).is_in(ids)), cp.select(mp.columns)])
    clients = pl.concat([mc.filter(C(G).is_in(ids)), cc.select(mc.columns)])
    sectors = pl.concat([ms.filter(C(G).is_in(ids)), cs.select(ms.columns)])
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = (
        apply_adjustments(prices)
        .select(G, "date", "adj_close", "value")
        .with_columns(C("date").cast(pl.Date))
    )
    feats = feats.with_columns(C("date").cast(pl.Date)).join(adj, on=[G, "date"], how="inner")
    feats = feats.sort(G, "date").with_columns(kind=C(G).replace_strict(kinds, default=None))
    # breadth of the STOCK market: share of model stocks above their 60-day average
    st = apply_adjustments(mp.filter(~C(G).is_in(ids))).select(G, "date", "adj_close")
    st = st.sort(G, "date").with_columns(
        above=(C("adj_close") > C("adj_close").rolling_mean(60).over(G)).cast(pl.Float64),
        n=C("adj_close").rolling_mean(60).over(G).is_not_null(),
        date=C("date").cast(pl.Date),
    )
    breadth = st.filter(C("n")).group_by("date").agg(C("above").mean().alias("breadth_stocks"))
    return feats, breadth.sort("date")


def finish(feats: pl.DataFrame) -> pl.DataFrame:
    """Daily return, cuts, forward returns and the liquidity flag (cheap, so redone on a cache)."""
    c = C("adj_close")
    r1 = (c / c.shift(1) - 1).over(G)
    # fixed-income funds that pay cash drop on the payout day and the adjustment does not see it;
    # such a drop (or a rise above 2%, never a real fixed-income day) is cut the same way
    fixed_break = (C("kind") == "fixed") & ((r1 < FIXED_DROP) | (r1 > 0.02))
    feats = feats.with_columns(r1=r1, jump=((r1.abs() > JUMP) | fixed_break).fill_null(False))
    # a jump at day j breaks every window (t+1, t+1+h] that contains j
    feats = feats.with_columns(jc=C("jump").cast(pl.Int32).cum_sum().over(G))
    for h in HS:
        f = (c.shift(-1 - h) / c.shift(-1) - 1).over(G)
        broken = (C("jc").shift(-1 - h) - C("jc").shift(-1)).over(G) > 0
        feats = feats.with_columns(pl.when(broken).then(None).otherwise(f).alias(f"fwd_{h}"))
    return feats.with_columns(
        liquid=(C("value").rolling_median(20).over(G) >= MIN_VALUE).fill_null(False)
    )


def feature_names(p: pl.DataFrame) -> list[str]:
    cols = [*TECHNICAL_COLUMNS, *BOARD_COLUMNS]
    return [
        x for x in cols if x in p.columns and x not in NOT_FEATURES and p.schema[x].is_numeric()
    ]


def halves(dates: list) -> object:
    ds = sorted(set(dates))
    return ds[len(ds) // 2]


def welch(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 6 or len(b) < 6:
        return None
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def tstat(x: np.ndarray) -> float | None:
    x = x[np.isfinite(x)]
    if len(x) < 6 or x.std(ddof=1) == 0:
        return None
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


# ---------------------------------------------------------------- A: cross-section


def daily_ic(g: pl.DataFrame, feats: list[str], h: int, shuffle: bool) -> pl.DataFrame:
    f = f"fwd_{h}"
    d = g.filter(C(f).is_not_null())
    if shuffle:
        d = d.with_columns(C(f).shuffle(seed=int(RNG.integers(1 << 30))).over("date"))
    aggs = [pl.len().alias("n"), C(f).mean().alias("grp")]
    for x in feats:
        ok = C(x).is_not_null() & C(x).is_finite()
        aggs.append(pl.corr(C(x).filter(ok).rank(), C(f).filter(ok).rank()).alias(f"ic|{x}"))
        q = C(x).filter(ok).quantile(2 / 3)
        aggs.append(C(f).filter(ok & (C(x) >= q)).mean().alias(f"top|{x}"))
        q1 = C(x).filter(ok).quantile(1 / 3)
        aggs.append(C(f).filter(ok & (C(x) <= q1)).mean().alias(f"bot|{x}"))
    return d.group_by("date").agg(aggs).filter(C("n") >= 8).sort("date")


def judge_ic(by: pl.DataFrame, feats: list[str], h: int, mid) -> dict:
    out = {}
    for x in feats:
        res = {}
        for part, sub in (
            ("first", by.filter(C("date") < mid)),
            ("second", by.filter(C("date") >= mid)),
        ):
            ind = sub.gather_every(h)
            ic = ind[f"ic|{x}"].to_numpy().astype(float)
            # the side the feature points to: positive IC -> top third, negative -> bottom third
            res[part] = {
                "ic": float(np.nanmean(sub[f"ic|{x}"].to_numpy().astype(float))),
                "t": tstat(ic),
                "top_net": float(
                    np.nanmean((sub[f"top|{x}"] - sub["grp"]).to_numpy().astype(float))
                )
                - COST,
                "bot_net": float(
                    np.nanmean((sub[f"bot|{x}"] - sub["grp"]).to_numpy().astype(float))
                )
                - COST,
                "days": sub.height,
            }
        a, b = res["first"], res["second"]
        sign = np.sign(a["ic"]) if np.sign(a["ic"]) == np.sign(b["ic"]) else 0
        side = "top_net" if sign > 0 else "bot_net"
        res["pass"] = bool(
            sign != 0
            and a["t"] is not None
            and b["t"] is not None
            and abs(a["t"]) >= 2
            and abs(b["t"]) >= 2
            and a[side] > 0
            and b[side] > 0
        )
        out[x] = res
    return out


def study_cross(p: pl.DataFrame, feats: list[str]) -> dict:
    res: dict = {}
    for grp in ("equity", "gold", "fixed", "leveraged"):
        g = p.filter((C("kind") == grp) & C("liquid"))
        if g.is_empty():
            continue
        res[grp] = {"funds": g[G].n_unique(), "h": {}}
        for h in HS:
            by = daily_ic(g, feats, h, shuffle=False)
            # halves of the days that have 8 funds, so both halves hold usable days
            mid = halves(by["date"].to_list()) if by.height else None
            if by.height < 4 * h:
                res[grp]["h"][h] = {"days": by.height, "note": "too few days with 8 funds"}
                continue
            real = judge_ic(by, feats, h, mid)
            null = judge_ic(daily_ic(g, feats, h, shuffle=True), feats, h, mid)
            res[grp]["h"][h] = {
                "days": by.height,
                "mid": str(mid),
                "passed": [x for x, v in real.items() if v["pass"]],
                "passed_by_luck": [x for x, v in null.items() if v["pass"]],
                "best": sorted(
                    (
                        {
                            "feature": x,
                            "ic": [v["first"]["ic"], v["second"]["ic"]],
                            "t": [v["first"]["t"], v["second"]["t"]],
                            "net_side": [
                                v["first"]["top_net" if v["first"]["ic"] > 0 else "bot_net"],
                                v["second"]["top_net" if v["second"]["ic"] > 0 else "bot_net"],
                            ],
                        }
                        for x, v in real.items()
                        if np.sign(v["first"]["ic"]) == np.sign(v["second"]["ic"])
                    ),
                    key=lambda r: -min(abs(r["t"][0] or 0), abs(r["t"][1] or 0)),
                )[:8],
            }
    return res


# ---------------------------------------------------------------- B: timing of a whole group


def group_index(p: pl.DataFrame) -> pl.DataFrame:
    """Daily equal-weight return of each group's liquid funds (yesterday's liquidity, no jumps),
    plus the group's retail net flow ratio."""
    d = p.with_columns(liq_prev=C("liquid").shift(1).over(G)).filter(
        C("liq_prev") & ~C("jump") & C("r1").is_not_null()
    )
    g = d.group_by("date", "kind").agg(
        C("r1").mean().alias("ret"),
        C("ind_net_flow").sum().alias("flow"),
        C("value").sum().alias("val"),
        pl.len().alias("n"),
    )
    return g.filter(C("n") >= 3).sort("kind", "date")


def macro(series: str) -> pl.DataFrame:
    c = sqlite3.connect(DB)
    rows = c.execute(
        "select ref_period, value from macro_series where series=? order by ref_period", (series,)
    ).fetchall()
    return pl.DataFrame(
        rows, schema={"date": pl.Utf8, series: pl.Float64}, orient="row"
    ).with_columns(C("date").str.to_date())


def tedpix() -> pl.DataFrame:
    c = sqlite3.connect(DB)
    rows = c.execute(
        "select date, close from market_index_daily where index_code=? order by date", (TEDPIX,)
    ).fetchall()
    return pl.DataFrame(
        rows, schema={"date": pl.Utf8, "tedpix": pl.Float64}, orient="row"
    ).with_columns(C("date").str.to_date())


def run_rule(ret: np.ndarray, on: np.ndarray, rf_daily: np.ndarray) -> np.ndarray:
    """Daily returns of following ``on`` decided at the close of day t, acted on at the close of
    t+1 (so the position on day t+2 onward); out of the market earns the bond rate; a cost of half
    the round trip on each switch."""
    pos = np.zeros(len(ret))
    pos[2:] = on[:-2]
    out = np.where(pos > 0, ret, rf_daily)
    sw = np.abs(np.diff(pos, prepend=0)) > 0
    return out - sw * COST / 2


def compare(dates: np.ndarray, base: np.ndarray, rule: np.ndarray, mid) -> dict:
    res = {}
    for part, m in (("first", dates < mid), ("second", dates >= mid)):
        b, r = base[m], rule[m]
        # monthly blocks of 21 days for the t of the difference
        k = len(b) // 21
        diff = np.array(
            [
                np.prod(1 + r[i * 21 : i * 21 + 21]) - np.prod(1 + b[i * 21 : i * 21 + 21])
                for i in range(k)
            ]
        )
        res[part] = {
            "rule_month": float(np.prod(1 + r) ** (21 / max(len(r), 1)) - 1),
            "hold_month": float(np.prod(1 + b) ** (21 / max(len(b), 1)) - 1),
            "diff_t": tstat(diff),
            "rule_maxdd": maxdd(r),
            "hold_maxdd": maxdd(b),
            "in_market": None,
        }
    res["better_both"] = bool(
        all(res[x]["rule_month"] > res[x]["hold_month"] for x in ("first", "second"))
    )
    res["significant_both"] = bool(
        res["better_both"] and all((res[x]["diff_t"] or 0) >= 2 for x in ("first", "second"))
    )
    res["less_drawdown_both"] = bool(
        all(res[x]["rule_maxdd"] > res[x]["hold_maxdd"] for x in ("first", "second"))
    )
    return res


def maxdd(r: np.ndarray) -> float:
    w = np.cumprod(1 + r)
    return float((w / np.maximum.accumulate(w) - 1).min()) if len(w) else 0.0


def rsi(x: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(x, prepend=x[0])
    up = pl.Series(np.clip(d, 0, None)).ewm_mean(alpha=1 / n).to_numpy()
    dn = pl.Series(np.clip(-d, 0, None)).ewm_mean(alpha=1 / n).to_numpy()
    return 100 - 100 / (1 + up / np.where(dn == 0, np.nan, dn))


def persian_day(d) -> int:
    return jdatetime.date.fromgregorian(date=d).day


def study_timing(p: pl.DataFrame, breadth: pl.DataFrame) -> dict:
    gi = group_index(p)
    rf = macro("rf_1y_ytm")
    tp = tedpix().sort("date")
    tp = tp.with_columns(
        tp_sma200=C("tedpix").rolling_mean(200), tp_sma50=C("tedpix").rolling_mean(50)
    )
    g18 = macro("gold_18k")
    res: dict = {}
    for grp in ("equity", "gold", "leveraged", "fixed"):
        s = (
            gi.filter(C("kind") == grp)
            .join(breadth, on="date", how="left")
            .join(tp, on="date", how="left")
            .join_asof(rf.sort("date"), on="date", strategy="backward")
            .sort("date")
        )
        if s.height < 250:
            continue
        s = s.with_columns(C("breadth_stocks", "tedpix", "tp_sma200", "tp_sma50").forward_fill())
        dates = s["date"].to_numpy()
        ret = s["ret"].to_numpy()
        lvl = np.cumprod(1 + ret)
        rfd = (1 + np.nan_to_num(s["rf_1y_ytm"].to_numpy(), nan=0.23)) ** (1 / 245) - 1
        mid = dates[len(dates) // 2]

        def sma(n: int, lvl: np.ndarray = lvl) -> np.ndarray:
            return pl.Series(lvl).rolling_mean(n).to_numpy()

        hi = np.maximum.accumulate(lvl)
        dd = lvl / hi - 1
        r = rsi(lvl)
        flow = pl.Series(s["flow"].to_numpy() / np.maximum(s["val"].to_numpy(), 1))
        fz = ((flow - flow.rolling_mean(60)) / flow.rolling_std(60)).to_numpy()
        br = s["breadth_stocks"].to_numpy()
        rules = {
            "above_sma20": lvl > sma(20),
            "above_sma60": lvl > sma(60),
            "above_sma120": lvl > sma(120),
            "sma50_over_200": sma(50) > sma(200),
            "stock_breadth_over_45": br > 0.45,
            "stock_breadth_not_under_45": ~(br < 0.45),
            "tedpix_over_sma200": s["tedpix"].to_numpy() > s["tp_sma200"].to_numpy(),
            "tedpix_sma50_over_200": s["tp_sma50"].to_numpy() > s["tp_sma200"].to_numpy(),
            "out_after_dd10_until_sma20": ~((dd < -0.10) & (lvl < sma(20))),
            "rsi_not_over_70": ~(r > 70),
            "retail_inflow_z_under_1": ~(fz > 1),
            "retail_outflow_z_over_minus1": ~(fz < -1),
        }
        if grp == "gold":
            # 18k gold of day t is known that evening; run_rule acts at the close of t+1
            gr = (
                s.select("date")
                .join_asof(
                    g18.sort("date").with_columns(g=C("gold_18k") / C("gold_18k").shift(1) - 1),
                    on="date",
                    strategy="backward",
                )["g"]
                .to_numpy()
            )
            rules["gold18k_rose_that_day"] = gr > 0
        out = {
            "days": len(dates),
            "from": str(dates[0]),
            "mid": str(mid),
            "hold_month_all": float(lvl[-1] ** (21 / len(lvl)) - 1),
            "bond_month": float(np.mean(rfd) * 21),
            "rules": {},
        }
        for name, on in rules.items():
            on = np.nan_to_num(on.astype(float), nan=1.0) > 0
            x = compare(dates, ret, run_rule(ret, on, rfd), mid)
            x["in_market_share"] = float(on.mean())
            out["rules"][name] = x
        # calendar effects: mean return by weekday and in the first 3 Persian days vs the rest
        wd = np.array([d.astype("datetime64[D]").astype(object).weekday() for d in dates])
        pdays = np.array([persian_day(d.astype("datetime64[D]").astype(object)) for d in dates])
        cal = {}
        for part, m in (("first", dates < mid), ("second", dates >= mid)):
            cal[part] = {
                "weekday": {int(k): float(ret[m & (wd == k)].mean()) for k in np.unique(wd[m])},
                "month_turn": float(ret[m & ((pdays <= 3) | (pdays >= 29))].mean()),
                "rest": float(ret[m & (pdays > 3) & (pdays < 29)].mean()),
                "month_turn_t": welch(
                    ret[m & ((pdays <= 3) | (pdays >= 29))], ret[m & (pdays > 3) & (pdays < 29)]
                ),
                "weekday_t_vs_rest": {
                    int(k): welch(ret[m & (wd == k)], ret[m & (wd != k)]) for k in np.unique(wd[m])
                },
            }
        out["calendar"] = cal
        # retail flow as a signal: correlation of the flow z with the next 20 days (blocks)
        fwd20 = np.array(
            [
                np.prod(1 + ret[i + 2 : i + 22]) - 1 if i + 22 <= len(ret) else np.nan
                for i in range(len(ret))
            ]
        )
        out["flow_vs_next20"] = {
            part: float(
                pl.DataFrame({"a": fz[m][::20], "b": fwd20[m][::20]})
                .drop_nans()
                .drop_nulls()
                .select(pl.corr("a", "b"))
                .item()
                or 0
            )
            for part, m in (("first", dates < mid), ("second", dates >= mid))
        }
        if grp == "gold":
            out["gold"] = gold_study(s, g18, mid)
        res[grp] = out
    res["rotation"] = rotation(gi)
    return res


def gold_study(s: pl.DataFrame, g18: pl.DataFrame, mid) -> dict:
    """Gold funds against 18k gold: does yesterday's gold move lead the fund (catch-up), and does
    the fund's premium over gold (its price / 18k gold against its own 60-day mean) revert?"""
    lv = s.select("date", "ret").with_columns(lvl=(1 + C("ret")).cum_prod())
    g = g18.sort("date").with_columns(g_ret=C("gold_18k") / C("gold_18k").shift(1) - 1)
    d = lv.join_asof(g, on="date", strategy="backward").drop_nulls()
    # the 18k price of day t is known by its evening; the fund move of day t+1 is the test
    d = d.with_columns(
        next_ret=C("ret").shift(-1),
        # tradable: gold of day t known that evening, buy at the close of t+1, sell close of t+2
        trade_ret=C("ret").shift(-2),
        prem=(C("lvl") / C("gold_18k")).log(),
    ).with_columns(
        prem_z=(C("prem") - C("prem").rolling_mean(60)) / C("prem").rolling_std(60),
        next20=(C("lvl").shift(-21) / C("lvl").shift(-1) - 1),
    )
    out = {}
    for part, m in (("first", C("date") < mid), ("second", C("date") >= mid)):
        x = d.filter(m)
        same = x.select(pl.corr("ret", "g_ret")).item()
        lead = x.select(pl.corr("g_ret", "next_ret")).item()
        trade = x.select(pl.corr("g_ret", "trade_ret")).item()
        up = x.filter(C("g_ret") > 0)["trade_ret"].drop_nulls().to_numpy()
        dn = x.filter(C("g_ret") <= 0)["trade_ret"].drop_nulls().to_numpy()
        xb = x.gather_every(20).drop_nulls(["prem_z", "next20"])
        rev = xb.select(pl.corr("prem_z", "next20")).item()
        out[part] = {
            "same_day_corr": same,
            "gold_today_vs_fund_tomorrow": lead,
            "gold_today_vs_fund_day_after": trade,
            "day_after_mean_if_gold_up": float(up.mean()),
            "day_after_mean_if_gold_down": float(dn.mean()),
            "day_after_up_vs_down_t": welch(up, dn),
            "cost_one_trade": COST,
            "premium_z_vs_next20": rev,
            "n_blocks": xb.height,
        }
    return out


def rotation(gi: pl.DataFrame) -> dict:
    """Each 21 days hold the group (equity, gold, fixed) with the best past 60-day return, against
    an equal mix of the three, rebalanced on the same days."""
    w = (
        gi.filter(C("kind").is_in(["equity", "gold", "fixed"]))
        .pivot(on="kind", index="date", values="ret")
        .sort("date")
        .drop_nulls()
    )
    names = ["equity", "gold", "fixed"]
    r = w.select(names).to_numpy()
    dates = w["date"].to_numpy()
    mid = dates[len(dates) // 2]
    pick = np.full(len(r), -1)
    for i in range(60, len(r), 21):
        past = np.prod(1 + r[i - 60 : i], axis=0)
        pick[i + 1 : i + 22] = int(np.argmax(past))
    rot = np.array([r[i, pick[i]] if pick[i] >= 0 else r[i].mean() for i in range(len(r))])
    switches = np.r_[False, np.diff(pick) != 0]
    rot = rot - switches * COST
    mix = r.mean(axis=1)
    x = compare(dates, mix, rot, mid)
    x["from"] = str(dates[0])
    return x


# ---------------------------------------------------------------- C: machine learning


def study_ml(p: pl.DataFrame, feats: list[str], h: int = 20) -> dict:
    res = {}
    for grp in ("equity", "gold"):
        g = p.filter((C("kind") == grp) & C("liquid") & C(f"fwd_{h}").is_not_null())
        g = g.with_columns(
            y=(C(f"fwd_{h}") - C(f"fwd_{h}").mean().over("date")),
            ym=C("date").dt.strftime("%Y-%m"),
        )
        months = sorted(g["ym"].unique().to_list())
        if len(months) < 18:
            continue
        rows = []
        for i in range(12, len(months)):
            test_m = months[i]
            test = g.filter(C("ym") == test_m)
            first_test = test["date"].min()
            # gap of h trading days: drop training rows whose label window reaches the test month
            train = g.filter(C("date") < first_test).sort("date")
            cut = train["date"].unique().sort()
            if len(cut) <= h + 60:
                continue
            train = train.filter(C("date") <= cut[-h - 1])
            xs = train.select(feats).to_numpy().astype(np.float32)
            y = train["y"].to_numpy()
            m = lgb.LGBMRegressor(
                n_estimators=200,
                learning_rate=0.03,
                num_leaves=15,
                min_child_samples=200,
                subsample=0.8,
                subsample_freq=1,
                colsample_bytree=0.7,
                verbose=-1,
            )
            m.fit(xs, y)
            pred = m.predict(test.select(feats).to_numpy().astype(np.float32))
            # best single feature of the training window, with its sign
            ics = {}
            tr = train.gather_every(5)
            for x in feats:
                v = tr.select(pl.corr(C(x).rank(), C("y").rank())).item()
                if v is not None and np.isfinite(v):
                    ics[x] = v
            bx = max(ics, key=lambda k: abs(ics[k]))
            single = test[bx].to_numpy() * np.sign(ics[bx])
            t = test.with_columns(pl.Series("pred", pred), pl.Series("single", single))
            for (dt,), day in t.group_by(["date"]):
                if day.height < 8:
                    continue
                rows.append(
                    {
                        "date": dt,
                        "ic_ml": day.select(pl.corr(C("pred").rank(), C("y").rank())).item(),
                        "ic_single": day.select(pl.corr(C("single").rank(), C("y").rank())).item(),
                        "top_ml": day.filter(C("pred") >= C("pred").quantile(2 / 3))["y"].mean(),
                        "best_single": bx,
                    }
                )
        if not rows:
            continue
        r = pl.DataFrame(rows).sort("date")
        mid = halves(r["date"].to_list())
        out = {"test_days": r.height}
        for part, sub in (
            ("first", r.filter(C("date") < mid)),
            ("second", r.filter(C("date") >= mid)),
        ):
            ind = sub.gather_every(h)
            out[part] = {
                "ic_ml": sub["ic_ml"].mean(),
                "ic_ml_t": tstat(ind["ic_ml"].to_numpy().astype(float)),
                "ic_single": sub["ic_single"].mean(),
                "top_ml_net": (sub["top_ml"].mean() or 0) - COST,
                "singles_used": sub["best_single"]
                .value_counts()
                .sort("count", descending=True)
                .head(3)
                .to_dicts(),
            }
        res[grp] = out
    return res


def main() -> None:
    if CACHE and Path(CACHE).exists():
        p = finish(pl.read_parquet(CACHE))
        breadth = pl.read_parquet(CACHE + ".breadth")
    else:
        p, breadth = build()
        p = finish(p)
        if CACHE:
            p.write_parquet(CACHE)
            breadth.write_parquet(CACHE + ".breadth")
    feats = feature_names(p)
    census = (
        p.filter(C("liquid"))
        .group_by("kind")
        .agg(
            C(G).n_unique().alias("funds"),
            C("date").min().alias("from"),
            pl.len().alias("fund_days"),
        )
        .to_dicts()
    )
    jumps = p.filter(C("jump")).select(G, "date", "r1").height
    print("census", census, "jumps cut", jumps, "features", len(feats))
    res = {"census": census, "jumps_cut": jumps, "features": feats, "cost": COST}
    res["A_cross_section"] = study_cross(p, feats)
    for grp, v in res["A_cross_section"].items():
        for h, x in v["h"].items():
            print(
                "A", grp, h, x.get("days"), "pass", x.get("passed"), "luck", x.get("passed_by_luck")
            )
    res["B_timing"] = study_timing(p, breadth)
    for grp, v in res["B_timing"].items():
        if grp == "rotation":
            print(
                "B rotation",
                {k: v[k] for k in ("better_both", "significant_both")},
                v["first"],
                v["second"],
            )
            continue
        good = [k for k, x in v["rules"].items() if x["better_both"]]
        safer = [k for k, x in v["rules"].items() if x["less_drawdown_both"]]
        print("B", grp, v["from"], "better both", good, "less dd both", safer)
    res["C_ml"] = study_ml(p, feats)
    print("C", json.dumps(res["C_ml"], default=str)[:1500])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
