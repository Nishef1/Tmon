"""Do the techniques Iranian chart analysts teach beat the market here? One-off research behind
docs/reports/technical-signals-2026-11.md.

Run from backend/ with the live env (see ../weekly_outlook/README.md); argv[1] = scratch dir.
Each signal is an *event*: the first day its condition turns true for a symbol, on the liquid
60% of that day by 20-day median traded value. Entry is the close of t+1, prices are adjusted,
and excess = forward return minus the same-day mean of the liquid universe. A signal "works"
only when the 60-day mean excess beats the round-trip cost (1.75%) in both halves of the history
and is positive in most calendar years. Indicators are written here in polars (no TA-Lib).
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
COST = 0.0175
H = (20, 60, 120)


def roll(e: pl.Expr, fn: str, n: int) -> pl.Expr:
    return getattr(e, f"rolling_{fn}")(n, min_samples=n).over(G)


def ema(e: pl.Expr, n: int) -> pl.Expr:
    return e.ewm_mean(span=n, adjust=False, min_samples=n).over(G)


def lag(e: pl.Expr, k: int = 1) -> pl.Expr:
    return e.shift(k).over(G)


def build_panel() -> pl.DataFrame:
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    cols = ["buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i"]
    p = p.join(clients.select(G, "date", *cols), on=[G, "date"], how="left")
    cl, hi, lo = C("close"), C("high"), C("low")
    p = p.with_columns(
        ret1=cl / lag(cl) - 1,
        ret5=cl / lag(cl, 5) - 1,
        ret20=cl / lag(cl, 20) - 1,
        ret60=cl / lag(cl, 60) - 1,
        sma20=roll(cl, "mean", 20),
        sma50=roll(cl, "mean", 50),
        sma200=roll(cl, "mean", 200),
        sd20=roll(cl, "std", 20),
        hi250=roll(cl, "max", 250),
        vmed20=roll(C("value"), "median", 20),
        vol20=lag(roll(C("volume"), "mean", 20)),
        ema12=ema(cl, 12),
        ema26=ema(cl, 26),
        tenkan=(roll(hi, "max", 9) + roll(lo, "min", 9)) / 2,
        kijun=(roll(hi, "max", 26) + roll(lo, "min", 26)) / 2,
        span_b_raw=(roll(hi, "max", 52) + roll(lo, "min", 52)) / 2,
        lo20=roll(cl, "min", 20),
        net_i=(C("buy_value_i") - C("sell_value_i")) / C("value"),
        power=(C("buy_value_i") / C("buy_count_i")) / (C("sell_value_i") / C("sell_count_i")),
        n=pl.int_range(pl.len()).over(G),
    )
    p = p.with_columns(
        macd=C("ema12") - C("ema26"),
        span_a_raw=(C("tenkan") + C("kijun")) / 2,
        bbw=4 * C("sd20") / C("sma20"),
        vr=C("volume") / C("vol20"),
        dd=cl / C("hi250") - 1,
        prev_hi250=lag(C("hi250")),
        gain=C("ret1").clip(lower_bound=0),
        loss=(-C("ret1")).clip(lower_bound=0),
        net5=roll(C("net_i"), "mean", 5),
        power5=roll(C("power"), "mean", 5),
    )
    p = p.with_columns(
        macd_sig=ema(C("macd"), 9),
        # the cloud plotted under today's candle was computed 26 days ago
        cloud_top=pl.max_horizontal(lag(C("span_a_raw"), 26), lag(C("span_b_raw"), 26)),
        cloud_bot=pl.min_horizontal(lag(C("span_a_raw"), 26), lag(C("span_b_raw"), 26)),
        bbw_q10=lag(C("bbw").rolling_quantile(0.1, window_size=120, min_samples=120).over(G)),
        rsi=100 - 100 / (1 + roll(C("gain"), "mean", 14) / roll(C("loss"), "mean", 14)),
    )
    p = p.with_columns(
        # previous swing: the 20-day low and the RSI at that time, 20 trading days ago
        prev_lo20=lag(C("lo20"), 20),
        prev_rsi_min=lag(roll(C("rsi"), "min", 20), 20),
        power_hi=(C("power") > 2).cast(pl.Int8),
    )
    entry = lag(cl, -1)
    p = p.with_columns(*[(lag(cl, -1 - h) / entry - 1).alias(f"f{h}") for h in H])
    p = p.filter(C("n") >= 250)
    p = p.with_columns(
        liquid=(C("vmed20").rank("average").over("date") / pl.len().over("date")) >= 0.4
    )
    p = p.with_columns(
        *[
            (C(f"f{h}") - C(f"f{h}").filter(C("liquid")).mean().over("date")).alias(f"x{h}")
            for h in H
        ],
        year=C("date").dt.year(),
    )
    return p.drop(*cols, "gain", "loss", "span_a_raw", "span_b_raw")


def cross_up(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return (a > b) & (lag(a) <= lag(b))


def turns_on(cond: pl.Expr) -> pl.Expr:
    return cond & ~lag(cond).fill_null(False)


cl = C("close")
above_cloud = cl > C("cloud_top")
below_cloud = cl < C("cloud_bot")
SIGNALS: dict[str, tuple[str, pl.Expr]] = {
    # buy-side, as taught
    "golden_cross": ("buy", cross_up(C("sma50"), C("sma200"))),
    "close_over_sma200": ("buy", cross_up(cl, C("sma200"))),
    "close_over_sma50": ("buy", cross_up(cl, C("sma50"))),
    "macd_cross": ("buy", cross_up(C("macd"), C("macd_sig"))),
    "macd_cross_below_zero": ("buy", cross_up(C("macd"), C("macd_sig")) & (C("macd") < 0)),
    "rsi_exit_oversold": ("buy", (C("rsi") > 30) & (lag(C("rsi")) <= 30)),
    "rsi_bull_divergence": (
        "buy",
        turns_on(
            (cl <= C("lo20"))
            & (cl < C("prev_lo20"))
            & (C("rsi") > C("prev_rsi_min") + 5)
            & (C("rsi") < 40)
        ),
    ),
    "ichimoku_break_cloud": ("buy", turns_on(above_cloud) & (C("tenkan") > C("kijun"))),
    "ichimoku_tk_cross_above_cloud": ("buy", cross_up(C("tenkan"), C("kijun")) & above_cloud),
    "bollinger_squeeze_break": (
        "buy",
        (C("bbw") <= C("bbw_q10")) & cross_up(cl, C("sma20") + 2 * C("sd20")),
    ),
    "new_52w_high": ("buy", cross_up(cl, C("prev_hi250"))),
    "suspicious_volume_up": ("buy", turns_on((C("vr") > 3) & (C("ret1") > 0) & (C("net_i") > 0))),
    "heavy_real_money_in": ("buy", turns_on((C("net_i") > 0.2) & (C("power") > 2))),
    "power_over_2_three_days": ("buy", turns_on(roll(C("power_hi"), "sum", 3) == 3)),
    "smart_money_combo": (
        "buy",
        turns_on((C("power") > 1.5) & (C("vr") > 2) & (cl > C("sma20")) & (C("ret1") > 0)),
    ),
    "all_aligned": (
        "buy",
        turns_on(
            above_cloud
            & (C("macd") > C("macd_sig"))
            & (C("power5") > 1.2)
            & C("rsi").is_between(50, 70)
            & (C("sma50") > C("sma200"))
        ),
    ),
    # sell-side, as taught
    "death_cross": ("sell", cross_up(C("sma200"), C("sma50"))),
    "close_under_cloud": ("sell", turns_on(below_cloud)),
    "rsi_exit_overbought": ("sell", (C("rsi") < 70) & (lag(C("rsi")) >= 70)),
    "heavy_real_money_out": ("sell", turns_on((C("net_i") < -0.2) & (C("power") < 0.5))),
    "suspicious_volume_down": (
        "sell",
        turns_on((C("vr") > 3) & (C("ret1") < 0) & (C("net_i") < 0)),
    ),
}


def stats(sub: pl.DataFrame, split: object) -> dict:
    out: dict = {"n": sub.height, "symbols": sub[G].n_unique()}
    for h in H:
        ok = sub.filter(C(f"x{h}").is_not_null())
        if ok.height < 50:
            continue
        x, f = ok[f"x{h}"].to_numpy(), ok[f"f{h}"].to_numpy()
        yr = ok.group_by("year").agg(C(f"x{h}").mean(), pl.len()).filter(C("len") >= 20)
        ym = yr[f"x{h}"].to_numpy()
        sd = ym.std(ddof=1) if len(ym) > 2 else 0.0
        halves = [
            float(ok.filter(C("date") < split)[f"x{h}"].mean() or np.nan),
            float(ok.filter(C("date") >= split)[f"x{h}"].mean() or np.nan),
        ]
        out[f"h{h}"] = {
            "n": ok.height,
            "excess_mean": float(x.mean()),
            "excess_median": float(np.median(x)),
            "beat": float((x > 0).mean()),
            "raw_mean": float(f.mean()),
            "halves": halves,
            "years": len(ym),
            "years_pos": float((ym > 0).mean()) if len(ym) else None,
            "t_years": float(ym.mean() / (sd / np.sqrt(len(ym)))) if sd > 0 else None,
        }
    return out


def verdict(side: str, s: dict) -> str:
    """works: beats the cost in the signal's direction in both halves and in most years."""
    h = s.get("h60")
    if not h:
        return "too_few"
    sign = 1 if side == "buy" else -1
    a, b = (sign * v for v in h["halves"])
    yp = h["years_pos"] if sign == 1 else 1 - (h["years_pos"] or 0)
    if a > COST and b > COST and (yp or 0) >= 0.6:
        return "works"
    if a < -COST and b < -COST:
        return "backfires"
    return "no_edge"


if __name__ == "__main__":
    d = build_panel()
    sig = d.with_columns(*[e.fill_null(False).alias(k) for k, (_, e) in SIGNALS.items()])
    liq = sig.filter(C("liquid"))
    days = liq["date"].unique().sort()
    split = days[len(days) // 2]
    res = {"split_date": str(split), "first": str(days[0]), "last": str(days[-1]),
           "base": stats(liq, split), "signals": {}}  # fmt: skip
    for k, (side, _) in SIGNALS.items():
        s = stats(liq.filter(C(k)), split)
        s["side"] = side
        s["verdict"] = verdict(side, s)
        res["signals"][k] = s
    keep = ["instrument_id", "date", "liquid", "year", *[f"x{h}" for h in H], *[f"f{h}" for h in H]]
    feats = ["ret5", "ret20", "ret60", "dd", "rsi", "macd", "macd_sig", "bbw", "vr", "net5",
             "power5", "close", "sma20", "sma50", "sma200", "cloud_top", "cloud_bot", "tenkan",
             "kijun", "vmed20"]  # fmt: skip
    sig.select(*keep, *feats).write_parquet(SP + "/ts_panel.parquet")
    with open(SP + "/ts_stats.json", "w") as fh:
        json.dump(res, fh, indent=1)
    nan = float("nan")
    b = res["base"]["h60"]
    print(f"split={split} base x60={b['excess_mean']:+.3f} beat={b['beat']:.2f}")
    for k, v in res["signals"].items():
        a = v.get("h60") or {}
        c = v.get("h120") or {}
        hv = a.get("halves", [nan, nan])
        print(
            f"{k:30s} {v['side']:4s} n={v['n']:6d} "
            f"x20={(v.get('h20') or {}).get('excess_mean', nan):+.3f} "
            f"x60={a.get('excess_mean', nan):+.3f} med={a.get('excess_median', nan):+.3f} "
            f"beat={a.get('beat', nan):.2f} halves={hv[0]:+.3f}/{hv[1]:+.3f} "
            f"yrs+={a.get('years_pos') or nan:.2f} t={a.get('t_years') or nan:+.2f} "
            f"x120={c.get('excess_mean', nan):+.3f} -> {v['verdict']}"
        )
