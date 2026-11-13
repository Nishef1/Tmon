"""Turning points: where a symbol stands in its fall or run-up, and what history says about
symbols in the same place (docs/reports/turning-points-2026-11.md).

Every symbol-day gets exactly one *state* from a fixed priority list (an overheated run-up first,
then a deep fall with or without confirmation, then a half fall, then an uptrend near the high).
For each state the history of the liquid universe gives the forward excess return over the
same-day universe mean (entry at the close of ``t+1``, adjusted prices), the chance of a +50% or
a -20% move in 120 trading days, and how far the price fell first (worst close in the next 60
days). The rules and thresholds below were fixed before any per-symbol output was looked at and
are not tuned; a verdict is claimed only when both halves of the history agree.

This is a description of past base rates, not a forecast for one symbol and not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from tmon.features.adjustment import apply_adjustments

G = "instrument_id"
C = pl.col
HORIZONS = (20, 60, 120)
MIN_HISTORY = 250  # trading days: the 52-week high and low need a full year
LIQUID_SHARE = 0.6  # stats use the liquid 60% of each day by 20-day median traded value

# thresholds (fixed; see the module docstring)
DEEP_DD = -0.5  # at least 50% below the 52-week high
MID_DD = -0.3
HOT_RET60 = 1.0  # doubled in 60 trading days
NEAR_HIGH = -0.05
FALLING_RET20 = -0.10
FLOW_NET5 = 0.05  # 5-day mean of individual net buying / traded value
FLOW_POWER5 = 1.2  # 5-day mean of per-capita buy / per-capita sell (individuals)
OUT_NET5 = -0.05
OUT_POWER5 = 0.8
MKT_DD = -0.2
# the one sell warning of docs/reports/technical-signals-2026-11.md that held in both halves:
# volume over three times its 20-day mean on a down day with individuals net sellers
WARN_VR = 3.0
WARN_RECENT = 20  # shown when it fired within the symbol's last 20 trading days


@dataclass(frozen=True)
class State:
    key: str
    title: str
    meaning: str


STATES: tuple[State, ...] = (
    State(
        "hot_breaking",
        "رشد خیلی تند، حالا رو به ضعف",
        "در ۶۰ روز بیش از دو برابر شده و حالا زیر میانگین ۲۰ روزه بسته شده است.",
    ),
    State(
        "hot_flow_out",
        "رشد خیلی تند، حقیقی‌ها در حال فروش",
        "در ۶۰ روز بیش از دو برابر شده و در ۵ روز اخیر حقیقی‌ها فروشنده‌اند.",
    ),
    State("hot", "رشد خیلی تند", "قیمت در سه ماه (۶۰ روز معاملاتی) بیش از دو برابر شده است."),
    State(
        "deep_flow_in",
        "ریزش سنگین، حقیقی‌ها در حال خرید",
        "بیش از ۵۰٪ زیر سقف ۵۲ هفته و در ۵ روز اخیر حقیقی‌ها با سرانهٔ بالاتر خریدارند.",
    ),
    State(
        "deep_turn_with_market",
        "ریزش سنگین، شروع برگشت در بازار ضعیف",
        "بیش از ۵۰٪ زیر سقف، بالای میانگین ۲۰ روزه برگشته و کل بازار هم در افت یا روند نزولی است.",
    ),
    State(
        "deep_turn_alone",
        "ریزش سنگین، شروع برگشت در بازار صعودی",
        "بیش از ۵۰٪ زیر سقف و بالای میانگین ۲۰ روزه برگشته؛ بازار صعودی است و این نماد جا مانده.",
    ),
    State(
        "deep_falling",
        "ریزش سنگین، هنوز در حال سقوط",
        "بیش از ۵۰٪ زیر سقف و در ۲۰ روز اخیر باز هم بیش از ۱۰٪ افت کرده است.",
    ),
    State("deep_base", "ریزش سنگین، بدون نشانهٔ برگشت", "بیش از ۵۰٪ زیر سقف ۵۲ هفته، بدون تأیید."),
    State("mid_fall", "افت متوسط", "۳۰ تا ۵۰٪ زیر سقف ۵۲ هفته."),
    State(
        "uptrend_high",
        "روند صعودی، نزدیک سقف",
        "کمتر از ۵٪ زیر سقف و میانگین‌های ۲۰، ۵۰ و ۲۰۰ روزه به ترتیب صعودی.",
    ),
    State("normal", "وضعیت معمولی", "هیچ‌یک از حالت‌های بالا نیست."),
)
STATE_BY_KEY = {s.key: s for s in STATES}
WARNING = State(
    "suspicious_volume_down",
    "حجم مشکوک با افت قیمت و خروج حقیقی",
    "حجم معاملات بیش از سه برابر میانگین ۲۰ روزه، قیمت پایانی پایین‌تر از روز قبل و حقیقی‌ها "
    "در مجموع فروشنده.",
)

# what would move a symbol from one state to a better or worse one (shown with that state's stats)
TRIGGERS: dict[str, list[tuple[str, str]]] = {
    "deep_falling": [
        (
            "deep_flow_in",
            "ورود پول حقیقی: میانگین ۵ روزهٔ خالص خرید حقیقی ≥ ۵٪ ارزش معاملات و قدرت خریدار ≥ ۱٫۲",
        ),
        (
            "deep_turn_with_market",
            "بسته شدن بالای میانگین ۲۰ روزه با بازده ۲۰ روزهٔ مثبت، در بازار نزولی",
        ),
        ("deep_turn_alone", "همان برگشت، ولی در بازار صعودی"),
    ],
    "deep_base": [
        (
            "deep_flow_in",
            "ورود پول حقیقی: میانگین ۵ روزهٔ خالص خرید حقیقی ≥ ۵٪ ارزش معاملات و قدرت خریدار ≥ ۱٫۲",
        ),
        (
            "deep_turn_with_market",
            "بسته شدن بالای میانگین ۲۰ روزه با بازده ۲۰ روزهٔ مثبت، در بازار نزولی",
        ),
        ("deep_falling", "افت بیش از ۱۰٪ دیگر در ۲۰ روز"),
    ],
    "deep_turn_alone": [
        ("deep_flow_in", "ورود پول حقیقی با همان شرط"),
        ("deep_falling", "افت بیش از ۱۰٪ دیگر در ۲۰ روز"),
    ],
    "deep_turn_with_market": [
        ("deep_flow_in", "ورود پول حقیقی با همان شرط"),
        ("deep_falling", "افت بیش از ۱۰٪ دیگر در ۲۰ روز"),
    ],
    "deep_flow_in": [
        ("deep_falling", "پول حقیقی برگردد و افت بیش از ۱۰٪ در ۲۰ روز تکرار شود"),
    ],
    "hot": [
        ("hot_flow_out", "خروج پول حقیقی: میانگین ۵ روزه ≤ −۵٪ و قدرت خریدار ≤ ۰٫۸"),
        ("hot_breaking", "بسته شدن زیر میانگین ۲۰ روزه"),
    ],
    "hot_flow_out": [("hot_breaking", "بسته شدن زیر میانگین ۲۰ روزه")],
    "uptrend_high": [("hot", "دو برابر شدن در ۶۰ روز")],
    "mid_fall": [("deep_falling", "افت تا بیش از ۵۰٪ زیر سقف با ادامهٔ ریزش")],
}


def _roll(e: pl.Expr, fn: str, n: int) -> pl.Expr:
    out: pl.Expr = getattr(e, f"rolling_{fn}")(n, min_samples=n).over(G)
    return out


def build_panel(prices: pl.DataFrame, clients: pl.DataFrame) -> pl.DataFrame:
    """One row per symbol-day with the state inputs, the state, the market state and the
    forward outcomes (null where the future is not known yet)."""
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    # every price below is the adjusted one, or a capital increase reads as a crash
    p = p.with_columns(close=C("adj_close"), high=C("adj_high"), low=C("adj_low"))
    cols = ["buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i"]
    p = p.join(clients.select(G, "date", *cols), on=[G, "date"], how="left")
    cl = C("close")
    p = p.with_columns(
        ret1=cl / cl.shift(1).over(G) - 1,
        ret20=cl / cl.shift(20).over(G) - 1,
        ret60=cl / cl.shift(60).over(G) - 1,
        hi250=_roll(cl, "max", MIN_HISTORY),
        sma20=_roll(cl, "mean", 20),
        sma50=_roll(cl, "mean", 50),
        sma200=_roll(cl, "mean", 200),
        vmed20=_roll(C("value"), "median", 20),
        vol20=_roll(C("volume"), "mean", 20).shift(1).over(G),
        net_i=(C("buy_value_i") - C("sell_value_i")) / C("value"),
        power=(C("buy_value_i") / C("buy_count_i")) / (C("sell_value_i") / C("sell_count_i")),
        n=pl.int_range(pl.len()).over(G),
    )
    p = p.with_columns(
        dd=cl / C("hi250") - 1,
        net5=_roll(C("net_i"), "mean", 5),
        power5=_roll(C("power"), "mean", 5),
        gain=C("ret1").clip(lower_bound=0),
        loss=(-C("ret1")).clip(lower_bound=0),
    )
    sell_flag = (C("volume") / C("vol20") > WARN_VR) & (C("ret1") < 0) & (C("net_i") < 0)
    p = p.with_columns(
        rsi=100 - 100 / (1 + _roll(C("gain"), "mean", 14) / _roll(C("loss"), "mean", 14)),
        # first day of the run only, as in the study (research/technical_signals/study.py)
        warn=sell_flag.fill_null(False) & ~sell_flag.shift(1).over(G).fill_null(False),
    )
    entry = C("close").shift(-1).over(G)  # entry at the close of t+1
    p = p.with_columns(
        *[(C("close").shift(-1 - h).over(G) / entry - 1).alias(f"f{h}") for h in HORIZONS],
        mae60=C("close").reverse().rolling_min(60, min_samples=1).reverse().shift(-2).over(G)
        / entry
        - 1,
    )
    p = p.filter(C("n") >= MIN_HISTORY - 1)
    p = p.with_columns(
        liquid=(C("vmed20").rank("average").over("date") / pl.len().over("date"))
        >= 1 - LIQUID_SHARE
    )
    mk = (
        p.filter(C("liquid"))
        .group_by("date")
        .agg(m=C("ret1").mean())
        .sort("date")
        .with_columns(lvl=(1 + C("m").fill_null(0)).cum_prod())
    )
    mk = mk.with_columns(
        mkt_bull=C("lvl") > C("lvl").rolling_mean(200, min_samples=200),
        mkt_dd=C("lvl") / C("lvl").rolling_max(MIN_HISTORY, min_samples=1) - 1,
    )
    p = p.join(mk.select("date", "mkt_bull", "mkt_dd"), on="date", how="left")
    univ = C("liquid")
    p = p.with_columns(
        *[
            (C(f"f{h}") - C(f"f{h}").filter(univ).mean().over("date")).alias(f"x{h}")
            for h in HORIZONS
        ]
    )
    return p.with_columns(state=state_expr()).drop(
        "buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i", "gain", "loss"
    )


def state_expr() -> pl.Expr:
    deep = C("dd") <= DEEP_DD
    hot = C("ret60") > HOT_RET60
    turn = (C("close") > C("sma20")) & (C("ret20") > 0)
    flow_in = (C("net5") >= FLOW_NET5) & (C("power5") >= FLOW_POWER5)
    flow_out = (C("net5") <= OUT_NET5) & (C("power5") <= OUT_POWER5)
    weak_mkt = (~C("mkt_bull").fill_null(True)) | (C("mkt_dd") < MKT_DD)
    trend = (C("sma20") > C("sma50")) & (C("sma50") > C("sma200"))
    e = (
        pl.when(hot & (C("close") < C("sma20")))
        .then(pl.lit("hot_breaking"))
        .when(hot & flow_out)
        .then(pl.lit("hot_flow_out"))
        .when(hot)
        .then(pl.lit("hot"))
        .when(deep & flow_in)
        .then(pl.lit("deep_flow_in"))
        .when(deep & turn & weak_mkt)
        .then(pl.lit("deep_turn_with_market"))
        .when(deep & turn)
        .then(pl.lit("deep_turn_alone"))
        .when(deep & (C("ret20") < FALLING_RET20))
        .then(pl.lit("deep_falling"))
        .when(deep)
        .then(pl.lit("deep_base"))
        .when((C("dd") > DEEP_DD) & (C("dd") <= MID_DD))
        .then(pl.lit("mid_fall"))
        .when((C("dd") > NEAR_HIGH) & trend)
        .then(pl.lit("uptrend_high"))
        .otherwise(pl.lit("normal"))
    )
    return pl.when(C("dd").is_null()).then(None).otherwise(e)


def _f(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x)
    return None if np.isnan(v) else v


def _block(sub: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": sub.height}
    for h in HORIZONS:
        ok = sub.filter(C(f"x{h}").is_not_null())
        if ok.height < 30:
            out[f"h{h}"] = None
            continue
        x, f = ok[f"x{h}"].to_numpy(), ok[f"f{h}"].to_numpy()
        out[f"h{h}"] = {
            "n": ok.height,
            "excess_mean": float(x.mean()),
            "excess_median": float(np.median(x)),
            "beat": float((x > 0).mean()),
            "raw_median": float(np.median(f)),
            "p_up50": float((f > 0.5).mean()),
            "p_dn20": float((f < -0.2).mean()),
        }
    m = sub["mae60"].drop_nulls().to_numpy()
    out["mae60_median"] = float(np.median(m)) if len(m) else None
    out["mae60_p10"] = float(np.quantile(m, 0.1)) if len(m) else None
    return out


def state_stats(panel: pl.DataFrame, cost: float) -> dict[str, Any]:
    """History per state on the liquid universe, for the whole span and for each half."""
    liq = panel.filter(C("liquid") & C("state").is_not_null())
    days = liq["date"].unique().sort()
    split = days[len(days) // 2]
    base = _block(liq)
    halves_base = [_block(liq.filter(C("date") < split)), _block(liq.filter(C("date") >= split))]
    out: dict[str, Any] = {}
    for s in STATES:
        sub = liq.filter(C("state") == s.key)
        whole = _block(sub)
        halves = [_block(sub.filter(C("date") < split)), _block(sub.filter(C("date") >= split))]
        whole["symbols"] = sub[G].n_unique()
        whole["episodes"] = sub.select(G, C("date").dt.strftime("%Y-%m")).unique().height
        whole["halves"] = halves
        whole["tone"] = _tone(halves, halves_base, cost)
        # every excess distribution is right-skewed (its median is below zero); "skewed" means a
        # positive mean carried by a few large winners while the typical case lags all symbols
        h, hb = whole.get("h120") or {}, base.get("h120") or {}
        whole["skewed"] = bool(
            h and hb and h["excess_mean"] > 0 and h["excess_median"] < hb["excess_median"]
        )
        out[s.key] = whole
    return {
        "split_date": str(split),
        "first": str(days[0]),
        "last": str(days[-1]),
        "base": base,
        "base_halves": halves_base,
        "states": out,
    }


def _tone(halves: list[dict[str, Any]], base: list[dict[str, Any]], cost: float) -> str:
    """``up``: the 120-day mean excess beats the round-trip cost in both halves; ``down``: it is
    negative in both halves and either worse than minus the cost or with a 20% fall at least
    5 points likelier than for all symbols; ``none`` otherwise (no edge both halves agree on)."""
    h = [b.get("h120") for b in halves]
    if any(x is None for x in h):
        return "none"
    xs = [float(x["excess_mean"]) for x in h if x]
    if all(v > cost for v in xs):
        return "up"
    dn = [
        float(x["p_dn20"]) - float((b.get("h120") or {}).get("p_dn20", 0))
        for x, b in zip(h, base, strict=True)
        if x
    ]
    if all(v < 0 for v in xs) and (all(v < -cost for v in xs) or all(d >= 0.05 for d in dn)):
        return "down"
    return "none"


def warning_stats(panel: pl.DataFrame) -> dict[str, Any]:
    """History of the sell warning on the liquid universe, whole and per half (same split as
    ``state_stats``)."""
    liq = panel.filter(C("liquid") & C("state").is_not_null())
    days = liq["date"].unique().sort()
    split = days[len(days) // 2]
    sub = liq.filter(C("warn"))
    out = _block(sub)
    out["symbols"] = sub[G].n_unique()
    out["halves"] = [_block(sub.filter(C("date") < split)), _block(sub.filter(C("date") >= split))]
    return out


def current_states(panel: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """Latest row per symbol (its own last trading day) with the inputs of its state."""
    last = panel.filter(C("state").is_not_null()).group_by(G).agg(pl.all().sort_by("date").last())
    tail = panel.sort(G, "date").group_by(G).tail(WARN_RECENT)
    warned = (
        tail.with_columns(ago=pl.int_range(pl.len(), 0, -1).over(G) - 1)
        .filter(C("warn"))
        .group_by(G)
        .agg(C("date").max().alias("warn_date"), C("ago").min().alias("warn_ago"))
    )
    wmap = {int(r[G]): r for r in warned.iter_rows(named=True)}
    out: dict[int, dict[str, Any]] = {}
    for r in last.iter_rows(named=True):
        w = wmap.get(int(r[G]))
        out[int(r[G])] = {
            "date": str(r["date"]),
            "state": r["state"],
            "dd": _f(r["dd"]),
            "ret20": _f(r["ret20"]),
            "ret60": _f(r["ret60"]),
            "rsi": _f(r["rsi"]),
            "net5": _f(r["net5"]),
            "power5": _f(r["power5"]),
            "above_sma20": None if r["sma20"] is None else bool(r["close"] > r["sma20"]),
            "liquid": bool(r["liquid"]),
            "warn_date": str(w["warn_date"]) if w else None,
            "warn_ago": int(w["warn_ago"]) if w else None,
        }
    return out


def market_now(panel: pl.DataFrame) -> dict[str, Any]:
    d = panel["date"].max()
    r = panel.filter(C("date") == d).select("mkt_bull", "mkt_dd").row(0, named=True)
    return {"date": str(d), "bull": r["mkt_bull"], "drawdown": _f(r["mkt_dd"])}
