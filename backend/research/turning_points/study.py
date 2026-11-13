"""Turning-point event study: does a beaten-down (or overextended) symbol tend to turn, and
which confirmations matter? One-off research behind docs/reports/turning-points-2026-11.md.

Run from backend/ with the live env (see ../weekly_outlook/README.md); argv[1] = scratch dir.
Entry is the close of t+1 (never the signal day's own close), prices are adjusted, and the
universe each day is the liquid 60% by 20-day median traded value. Excess = forward return minus
the same-day mean of the universe. Rows overlap, so every table also gives per-year stability:
the share of calendar years whose mean excess is positive and a t-stat over yearly means.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

SP = sys.argv[1]
G = "instrument_id"
C = pl.col


def roll(e: pl.Expr, fn: str, n: int) -> pl.Expr:
    return getattr(e, f"rolling_{fn}")(n, min_samples=n).over(G)


def build_panel() -> pl.DataFrame:
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    p = p.with_columns(close=C("adj_close"), high=C("adj_high"), low=C("adj_low"))
    c = clients.select(G, "date", "buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i")
    p = p.join(c, on=[G, "date"], how="left")
    cl = C("close")
    p = p.with_columns(
        ret1=cl / cl.shift(1).over(G) - 1,
        ret5=cl / cl.shift(5).over(G) - 1,
        ret20=cl / cl.shift(20).over(G) - 1,
        ret60=cl / cl.shift(60).over(G) - 1,
        hi250=roll(cl, "max", 250),
        lo250=roll(cl, "min", 250),
        sma20=roll(cl, "mean", 20),
        sma50=roll(cl, "mean", 50),
        sma200=roll(cl, "mean", 200),
        vmed20=roll(C("value"), "median", 20),
        vol20=roll(C("volume"), "mean", 20).shift(1).over(G),
        net_i=(C("buy_value_i") - C("sell_value_i")) / C("value"),
        power=(C("buy_value_i") / C("buy_count_i")) / (C("sell_value_i") / C("sell_count_i")),
        n=pl.int_range(pl.len()).over(G),
    )
    d = p.with_columns(
        dd=cl / C("hi250") - 1,
        up_lo=cl / C("lo250") - 1,
        vr=C("volume") / C("vol20"),
        net5=roll(C("net_i"), "mean", 5),
        power5=roll(C("power"), "mean", 5),
        gain=C("ret1").clip(lower_bound=0),
        loss=(-C("ret1")).clip(lower_bound=0),
        lowdays=(cl <= C("lo250")).cast(pl.Int8),
    )
    d = d.with_columns(
        rsi=100 - 100 / (1 + roll(C("gain"), "mean", 14) / roll(C("loss"), "mean", 14)),
    )
    entry = C("close").shift(-1).over(G)  # entry at the close of t+1
    for h in (20, 60, 120):
        d = d.with_columns((C("close").shift(-1 - h).over(G) / entry - 1).alias(f"f{h}"))
    # worst close in the 60 days after entry, relative to entry
    fut_min = C("close").reverse().rolling_min(60, min_samples=1).reverse().shift(-2).over(G)
    d = d.with_columns(mae60=fut_min / entry - 1)
    d = d.filter(C("n") >= 250)
    d = d.with_columns(liq=C("vmed20").rank("average").over("date") / pl.len().over("date"))
    d = d.filter(C("liq") >= 0.4)
    mk = (
        d.group_by("date")
        .agg(m=C("ret1").mean(), breadth=(C("close") > C("sma200")).mean())
        .sort("date")
        .with_columns(lvl=(1 + C("m").fill_null(0)).cum_prod())
    )
    mk = mk.with_columns(
        mkt_bull=C("lvl") > C("lvl").rolling_mean(200, min_samples=200),
        mkt_dd=C("lvl") / C("lvl").rolling_max(250, min_samples=1) - 1,
    )
    d = d.join(mk.select("date", "mkt_bull", "breadth", "mkt_dd"), on="date", how="left")
    for h in (20, 60, 120):
        d = d.with_columns((C(f"f{h}") - C(f"f{h}").mean().over("date")).alias(f"x{h}"))
    return d.with_columns(year=C("date").dt.year())


def stats(sub: pl.DataFrame) -> dict:
    out: dict = {
        "n": sub.height,
        "symbols": sub[G].n_unique(),
        "episodes": sub.select(G, C("date").dt.strftime("%Y-%m")).unique().height,
    }
    for h in (20, 60, 120):
        ok = sub.filter(C(f"x{h}").is_not_null())
        if ok.height < 30:
            continue
        x, f = ok[f"x{h}"].to_numpy(), ok[f"f{h}"].to_numpy()
        yr = ok.group_by("year").agg(C(f"x{h}").mean(), pl.len()).filter(C("len") >= 20)
        ym = yr[f"x{h}"].to_numpy()
        sd = ym.std(ddof=1) if len(ym) > 2 else 0.0
        out[f"h{h}"] = {
            "excess_mean": float(x.mean()),
            "excess_median": float(np.median(x)),
            "beat": float((x > 0).mean()),
            "raw_median": float(np.median(f)),
            "p_up50": float((f > 0.5).mean()),
            "p_dn20": float((f < -0.2).mean()),
            "years": len(ym),
            "years_pos": float((ym > 0).mean()) if len(ym) else None,
            "t_years": float(ym.mean() / (sd / np.sqrt(len(ym)))) if sd > 0 else None,
        }
    m = sub["mae60"].drop_nulls().to_numpy()
    if len(m):
        out["mae60_median"] = float(np.median(m))
        out["mae60_p10"] = float(np.quantile(m, 0.1))
    return out


deep = C("dd") <= -0.5
mid = (C("dd") > -0.5) & (C("dd") <= -0.3)
knife = C("ret20") < -0.10
turn = (C("close") > C("sma20")) & (C("ret20") > 0)
turn50 = (C("close") > C("sma50")) & (C("sma20") > C("sma50"))
flow = (C("net5") > 0.05) & (C("power5") > 1.2)
oversold = C("rsi") < 30
capit = (C("vr") > 3) & (C("ret1") < -0.03)
newlow = C("lowdays") == 1
hot = C("ret60") > 1.0
nearhi = C("dd") > -0.05
overb = C("rsi") > 80
flow_out = (C("net5") < -0.05) & (C("power5") < 0.8)
bear = ~C("mkt_bull")
STATES = {
    "all": pl.lit(True),
    "deep_dd50": deep,
    "mid_dd30_50": mid,
    "deep_still_falling": deep & knife,
    "deep_new_low": deep & newlow,
    "deep_oversold": deep & oversold,
    "deep_capitulation": deep & capit,
    "deep_turn_sma20": deep & turn,
    "deep_turn_sma50": deep & turn50,
    "deep_flow_in": deep & flow,
    "deep_turn_and_flow": deep & turn & flow,
    "mid_turn_and_flow": mid & turn & flow,
    "deep_bear_mkt": deep & bear,
    "deep_bull_mkt": deep & ~bear,
    "deep_turn_bear_mkt": deep & turn & bear,
    "deep_turn_bull_mkt": deep & turn & ~bear,
    "deep_mkt_dd20": deep & (C("mkt_dd") < -0.2),
    "deep_turn_mkt_dd20": deep & turn & (C("mkt_dd") < -0.2),
    "hot_60d_x2": hot,
    "hot_near_high": hot & nearhi,
    "hot_overbought": hot & overb,
    "hot_flow_out": hot & flow_out,
    "near_high_flow_out": nearhi & flow_out,
    "hot_lost_sma20": hot & (C("close") < C("sma20")),
    "near_high_trend": nearhi & (C("sma20") > C("sma50")) & (C("sma50") > C("sma200")),
}

if __name__ == "__main__":
    d = build_panel()
    d.drop("buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i").write_parquet(
        SP + "/tp_panel.parquet"
    )
    res = {k: stats(d.filter(v)) for k, v in STATES.items()}
    with open(SP + "/tp_stats.json", "w") as fh:
        json.dump(res, fh, indent=1)
    nan = float("nan")
    for k, v in res.items():
        a, b = v.get("h60", {}), v.get("h120", {})
        print(
            f"{k:22s} n={v['n']:7d} ep={v['episodes']:6d} "
            f"x60={a.get('excess_mean', nan):+.3f} beat60={a.get('beat', nan):.2f} "
            f"yrs+={a.get('years_pos') or nan:.2f} t={a.get('t_years') or nan:+.2f} "
            f"x120={b.get('excess_mean', nan):+.3f} t120={b.get('t_years') or nan:+.2f} "
            f"up50={b.get('p_up50', nan):.2f} dn20={b.get('p_dn20', nan):.2f} "
            f"mae60={v.get('mae60_median', nan):+.3f}/{v.get('mae60_p10', nan):+.3f}"
        )
