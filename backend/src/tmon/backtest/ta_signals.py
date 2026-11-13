"""Every chart term of the glossary, computed and tested.

Report: docs/reports/glossary-signals-2026-11.md.

Each classic reading is an *event*: the first day its condition turns true for a symbol (the side
is what the textbooks teach: ``buy`` or ``sell``). History is the liquid 60% of each day by 20-day
median traded value; entry is the close of ``t+1`` on adjusted prices, and excess = forward return
minus the same-day mean of the liquid universe. For each horizon (1 to 60 candles) we keep:

* the mean excess, whole and per half of the history (the profit test: it must beat the
  round-trip cost in the signal's direction in both halves and in most calendar years);
* the share of cases that went up (the direction test: in the signal's direction it must beat
  the share for all symbols on the same days by ``DIR_EDGE`` in both halves).

Only entries one could trade count: a buy whose entry day was probably locked at the upper limit
(up ``LOCK_MOVE`` or more, or one price all day) is dropped, and a sell on a day locked down. The
price-limit history is not stored, so this is a stand-in that drops more days than the real queue.
Each signal also keeps its locked share and the 20-candle excess with locked days left in.

Nothing here is tuned: thresholds are the textbook ones (RSI 30/70, stochastic 20/80, ...).
Indicators are written in polars (TA-Lib is never a runtime dependency). This describes the
past; it is not a forecast for one symbol and not advice.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from tmon.features.adjustment import apply_adjustments

G = "instrument_id"
C = pl.col
H = (1, 3, 5, 10, 20, 60)
SHORT = (1, 3, 5)  # "the next few candles"
PROFIT_H = (5, 10, 20, 60)
MIN_HISTORY = 250
LIQUID_SHARE = 0.6
DIR_EDGE = 0.03  # 3 points better than all symbols in the up/down share, in both halves
MIN_YEARS_SHARE = 0.6
LOCK_MOVE = 0.028  # below every daily band TSETMC has used (3% and up)
RECENT = 10  # a signal is "current" for a symbol when it fired in its last 10 trading days


def roll(e: pl.Expr, fn: str, n: int) -> pl.Expr:
    out: pl.Expr = getattr(e, f"rolling_{fn}")(n, min_samples=n).over(G)
    return out


def ema(e: pl.Expr, n: int) -> pl.Expr:
    return e.ewm_mean(span=n, adjust=False, min_samples=n).over(G)


def wilder(e: pl.Expr, n: int) -> pl.Expr:
    return e.ewm_mean(alpha=1 / n, adjust=False, min_samples=n).over(G)


def lag(e: pl.Expr, k: int = 1) -> pl.Expr:
    return e.shift(k).over(G)


def cross_up(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return (a > b) & (lag(a) <= lag(b))


def turns_on(cond: pl.Expr) -> pl.Expr:
    return cond.fill_null(False) & ~lag(cond).fill_null(False)


FVG_MIN = 0.01  # a gap under 1% of the price is noise
FVG_AGE = 20  # a zone is watched for 20 trading days after it forms
ZIGZAG = 0.10  # Elliott pivots: a swing counts once the close turns 10% from its extreme


def _fvg(p: pl.DataFrame) -> pl.DataFrame:
    """Fair value gaps (three-candle imbalances) and the latest one of each side per symbol.

    Bullish: today's low is above the high of two days ago (zone = that high .. today's low).
    Bearish: today's high is below the low of two days ago. Zones are carried forward with
    their age; the signals read yesterday's zone so a gap never triggers on the day it forms."""
    hi, lo, cl = C("high"), C("low"), C("close")
    bull = (lo - lag(hi, 2)) / cl >= FVG_MIN
    bear = (lag(lo, 2) - hi) / cl >= FVG_MIN
    idx = pl.int_range(pl.len()).over(G)
    p = p.with_columns(
        _i=idx,
        fb_top=pl.when(bull).then(lo),
        fb_bot=pl.when(bull).then(lag(hi, 2)),
        fb_i=pl.when(bull).then(idx),
        fs_top=pl.when(bear).then(lag(lo, 2)),
        fs_bot=pl.when(bear).then(hi),
        fs_i=pl.when(bear).then(idx),
    )
    ff = ["fb_top", "fb_bot", "fb_i", "fs_top", "fs_bot", "fs_i"]
    p = p.with_columns([C(c).forward_fill().over(G) for c in ff])
    p = p.with_columns(
        fb_age=C("_i") - C("fb_i"),
        fs_age=C("_i") - C("fs_i"),
    )
    # yesterday's zone, so today's own gap is not read as a retest
    return p.with_columns(
        [
            lag(C(c)).alias(c + "_y")
            for c in ("fb_top", "fb_bot", "fb_age", "fs_top", "fs_bot", "fs_age")
        ]
    ).drop([*ff, "_i"])


def zigzag(close: np.ndarray, th: float = ZIGZAG) -> list[tuple[int, int, float, int]]:
    """Swing pivots of a close series: (pivot index, confirmed index, price, +1 high / -1 low).
    A pivot is only known on the day the close has turned ``th`` away from it, which is the
    day any signal built on it may fire."""
    out: list[tuple[int, int, float, int]] = []
    if len(close) == 0:
        return out
    d = 0
    hi_i = lo_i = 0
    hi = lo = float(close[0])
    for i in range(1, len(close)):
        c = float(close[i])
        if not np.isfinite(c):
            continue
        if d == 0:
            if c > hi:
                hi_i, hi = i, c
            if c < lo:
                lo_i, lo = i, c
            if c <= hi * (1 - th):
                out.append((hi_i, i, hi, 1))
                d, lo_i, lo = -1, i, c
            elif c >= lo * (1 + th):
                out.append((lo_i, i, lo, -1))
                d, hi_i, hi = 1, i, c
        elif d == 1:
            if c > hi:
                hi_i, hi = i, c
            elif c <= hi * (1 - th):
                out.append((hi_i, i, hi, 1))
                d, lo_i, lo = -1, i, c
        else:
            if c < lo:
                lo_i, lo = i, c
            elif c >= lo * (1 + th):
                out.append((lo_i, i, lo, -1))
                d, hi_i, hi = 1, i, c
    return out


def elliott_marks(close: np.ndarray, th: float = ZIGZAG) -> dict[str, np.ndarray]:
    """Textbook Elliott counts on zigzag pivots, flagged on the day the last pivot is confirmed.

    - ``ew_w3``: low, high, higher low that gave back 38.2-78.6% of the first swing: wave 2 is
      done and wave 3 would start (buy).
    - ``ew_5``: five up waves with wave 2 above the start, wave 4 above the top of wave 1,
      wave 5 above wave 3 and wave 3 not the shortest: the impulse is done (sell).
    - ``ew_abc``: such an impulse followed by A down, B below the top of 5, C below A: the
      correction is done (buy)."""
    n = len(close)
    w3, w5, abc = (np.zeros(n, dtype=bool) for _ in range(3))
    pv = zigzag(close, th)

    def impulse(q: list[tuple[int, int, float, int]]) -> bool:
        a, b, c, d, e, f = (x[2] for x in q)
        if [x[3] for x in q] != [-1, 1, -1, 1, -1, 1]:
            return False
        legs = (b - a, d - c, f - e)
        return c > a and d > b and e > b and f > d and legs[1] >= min(legs[0], legs[2])

    for k in range(len(pv)):
        conf = pv[k][1]
        if k >= 2:
            a, b, c = pv[k - 2], pv[k - 1], pv[k]
            if (a[3], b[3], c[3]) == (-1, 1, -1) and b[2] > a[2]:
                back = (b[2] - c[2]) / (b[2] - a[2])
                if 0.382 <= back <= 0.786:
                    w3[conf] = True
        if k >= 5 and impulse(pv[k - 5 : k + 1]):
            w5[conf] = True
        if k >= 8 and impulse(pv[k - 8 : k - 2]):
            top = pv[k - 3][2]
            a_, b_, c_ = pv[k - 2], pv[k - 1], pv[k]
            if (a_[3], b_[3], c_[3]) == (-1, 1, -1) and b_[2] < top and c_[2] < a_[2]:
                abc[conf] = True
    return {"ew_w3": w3, "ew_5": w5, "ew_abc": abc}


def _elliott(p: pl.DataFrame) -> pl.DataFrame:
    parts = []
    for (_,), g in p.select(G, "date", "close").group_by(G, maintain_order=True):
        m = elliott_marks(g["close"].to_numpy().astype(float))
        parts.append(g.select(G, "date").with_columns(**{k: pl.Series(v) for k, v in m.items()}))
    if not parts:
        return p.with_columns(ew_w3=pl.lit(False), ew_5=pl.lit(False), ew_abc=pl.lit(False))
    return p.join(pl.concat(parts), on=[G, "date"], how="left")


def indicators(prices: pl.DataFrame, clients: pl.DataFrame) -> pl.DataFrame:
    """One row per symbol-day with every indicator of the glossary on adjusted prices."""
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    p = p.with_columns(
        close=C("adj_close"), high=C("adj_high"), low=C("adj_low"), open=C("adj_open")
    )
    cols = ["buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i"]
    p = p.join(clients.select(G, "date", *cols), on=[G, "date"], how="left")
    cl, hi, lo = C("close"), C("high"), C("low")
    tp = (hi + lo + cl) / 3
    p = p.with_columns(
        ret1=cl / lag(cl) - 1,
        ret5=cl / lag(cl, 5) - 1,
        ret20=cl / lag(cl, 20) - 1,
        gap=C("open") / lag(cl) - 1,
        sma20=roll(cl, "mean", 20),
        sma50=roll(cl, "mean", 50),
        sma200=roll(cl, "mean", 200),
        ema12=ema(cl, 12),
        ema26=ema(cl, 26),
        sd20=roll(cl, "std", 20),
        hi20=lag(roll(hi, "max", 20)),
        lo20=lag(roll(lo, "min", 20)),
        hi250=lag(roll(cl, "max", MIN_HISTORY)),
        lo250=lag(roll(cl, "min", MIN_HISTORY)),
        hi120=roll(hi, "max", 120),
        lo120=roll(lo, "min", 120),
        hh14=roll(hi, "max", 14),
        ll14=roll(lo, "min", 14),
        vmed20=roll(C("value"), "median", 20),
        vol20=lag(roll(C("volume"), "mean", 20)),
        tenkan=(roll(hi, "max", 9) + roll(lo, "min", 9)) / 2,
        kijun=(roll(hi, "max", 26) + roll(lo, "min", 26)) / 2,
        span_b_raw=(roll(hi, "max", 52) + roll(lo, "min", 52)) / 2,
        tr=pl.max_horizontal(hi - lo, (hi - lag(cl)).abs(), (lo - lag(cl)).abs()),
        up_move=hi - lag(hi),
        dn_move=lag(lo) - lo,
        tpv=tp * C("volume"),
        mf=tp * C("volume"),
        tp=tp,
        obv_step=pl.when(cl > lag(cl))
        .then(C("volume"))
        .when(cl < lag(cl))
        .then(-C("volume"))
        .otherwise(0.0),
        net_i=(C("buy_value_i") - C("sell_value_i")) / C("value"),
        power=(C("buy_value_i") / C("buy_count_i")) / (C("sell_value_i") / C("sell_count_i")),
        # yesterday's classic pivot
        pivot=lag(tp),
        r1=2 * lag(tp) - lag(lo),
        s1=2 * lag(tp) - lag(hi),
        n=pl.int_range(pl.len()).over(G),
    )
    one_price = C("high") == C("low")
    p = p.with_columns(
        lock_up=(C("ret1") >= LOCK_MOVE) | (one_price & (C("ret1") > 0)),
        lock_dn=(C("ret1") <= -LOCK_MOVE) | (one_price & (C("ret1") < 0)),
    )
    p = p.with_columns(
        macd=C("ema12") - C("ema26"),
        span_a_raw=(C("tenkan") + C("kijun")) / 2,
        bb_up=C("sma20") + 2 * C("sd20"),
        bb_dn=C("sma20") - 2 * C("sd20"),
        bbw=4 * C("sd20") / C("sma20"),
        vr=C("volume") / C("vol20"),
        dd=cl / C("hi250") - 1,
        gain=C("ret1").clip(lower_bound=0),
        loss=(-C("ret1")).clip(lower_bound=0),
        stoch_k=100 * (cl - C("ll14")) / (C("hh14") - C("ll14")),
        willr=-100 * (C("hh14") - cl) / (C("hh14") - C("ll14")),
        atr14=wilder(C("tr"), 14),
        pdm=pl.when((C("up_move") > C("dn_move")) & (C("up_move") > 0))
        .then(C("up_move"))
        .otherwise(0.0),
        mdm=pl.when((C("dn_move") > C("up_move")) & (C("dn_move") > 0))
        .then(C("dn_move"))
        .otherwise(0.0),
        obv=C("obv_step").cum_sum().over(G),
        vwap20=roll(C("tpv"), "sum", 20) / roll(C("volume"), "sum", 20),
        pmf=roll(pl.when(C("tp") > lag(C("tp"))).then(C("mf")).otherwise(0.0), "sum", 14),
        nmf=roll(pl.when(C("tp") < lag(C("tp"))).then(C("mf")).otherwise(0.0), "sum", 14),
        net5=roll(C("net_i"), "mean", 5),
        power5=roll(C("power"), "mean", 5),
        # Fibonacci 61.8% retracement of the last 120-day range
        fib618=C("hi120") - 0.618 * (C("hi120") - C("lo120")),
    )
    p = p.with_columns(
        macd_sig=ema(C("macd"), 9),
        rsi=100 - 100 / (1 + wilder(C("gain"), 14) / wilder(C("loss"), 14)),
        stoch_d=roll(C("stoch_k"), "mean", 3),
        atr_pct=C("atr14") / cl,
        pdi=100 * wilder(C("pdm"), 14) / C("atr14"),
        mdi=100 * wilder(C("mdm"), 14) / C("atr14"),
        mfi=100 - 100 / (1 + C("pmf") / C("nmf")),
        obv_chg20=(C("obv") - lag(C("obv"), 20)) / roll(C("volume"), "sum", 20),
        cloud_top=pl.max_horizontal(lag(C("span_a_raw"), 26), lag(C("span_b_raw"), 26)),
        cloud_bot=pl.min_horizontal(lag(C("span_a_raw"), 26), lag(C("span_b_raw"), 26)),
        bbw_q10=lag(C("bbw").rolling_quantile(0.1, window_size=120, min_samples=120).over(G)),
    )
    p = p.with_columns(
        adx=wilder(100 * (C("pdi") - C("mdi")).abs() / (C("pdi") + C("mdi")), 14),
        atr_q10=lag(C("atr_pct").rolling_quantile(0.1, window_size=120, min_samples=120).over(G)),
        prev_lo20=lag(roll(cl, "min", 20), 20),
        prev_hi20c=lag(roll(cl, "max", 20), 20),
        prev_rsi_min=lag(roll(C("rsi"), "min", 20), 20),
        prev_rsi_max=lag(roll(C("rsi"), "max", 20), 20),
        lo20c=roll(cl, "min", 20),
        hi20c=roll(cl, "max", 20),
        power_hi=(C("power") > 2).cast(pl.Int8),
    )
    p = _fvg(p)
    p = _elliott(p)
    return p.drop(
        "tpv", "mf", "obv_step", "up_move", "dn_move", "pdm", "mdm", "tr", "pmf", "nmf",
        "gain", "loss", "span_a_raw", "span_b_raw", *cols,
    )  # fmt: skip


cl = C("close")
_above_cloud = cl > C("cloud_top")
_below_cloud = cl < C("cloud_bot")

# key: (glossary term, side, plain Persian name, textbook condition (an event))
SIGNALS: dict[str, tuple[str, str, str, pl.Expr]] = {
    "close_over_sma50": ("sma", "buy", "بسته شدن بالای میانگین ۵۰ روزه", cross_up(cl, C("sma50"))),
    "close_over_sma200": (
        "sma",
        "buy",
        "بسته شدن بالای میانگین ۲۰۰ روزه",
        cross_up(cl, C("sma200")),
    ),
    "golden_cross": (
        "moving_average",
        "buy",
        "تقاطع طلایی (۵۰ بالای ۲۰۰)",
        cross_up(C("sma50"), C("sma200")),
    ),
    "death_cross": (
        "moving_average",
        "sell",
        "تقاطع مرگ (۵۰ زیر ۲۰۰)",
        cross_up(C("sma200"), C("sma50")),
    ),
    "ema_cross_up": ("ema", "buy", "عبور EMA ۱۲ از بالای EMA ۲۶", cross_up(C("ema12"), C("ema26"))),
    "ema_cross_down": (
        "ema",
        "sell",
        "عبور EMA ۱۲ به زیر EMA ۲۶",
        cross_up(C("ema26"), C("ema12")),
    ),
    "rsi_exit_oversold": (
        "rsi",
        "buy",
        "خروج RSI از زیر ۳۰",
        (C("rsi") > 30) & (lag(C("rsi")) <= 30),
    ),
    "rsi_exit_overbought": (
        "rsi",
        "sell",
        "برگشت RSI از بالای ۷۰",
        (C("rsi") < 70) & (lag(C("rsi")) >= 70),
    ),
    "rsi_oversold": ("rsi", "buy", "RSI زیر ۳۰ (اشباع فروش)", turns_on(C("rsi") < 30)),
    "rsi_overbought": ("rsi", "sell", "RSI بالای ۷۰ (اشباع خرید)", turns_on(C("rsi") > 70)),
    "macd_cross": ("macd", "buy", "عبور مکدی از خط سیگنال", cross_up(C("macd"), C("macd_sig"))),
    "macd_cross_below_zero": (
        "macd",
        "buy",
        "عبور مکدی از سیگنال زیر صفر",
        cross_up(C("macd"), C("macd_sig")) & (C("macd") < 0),
    ),
    "macd_cross_down": (
        "macd",
        "sell",
        "عبور مکدی به زیر خط سیگنال",
        cross_up(C("macd_sig"), C("macd")),
    ),
    "stoch_buy": (
        "stochastic",
        "buy",
        "استوکاستیک: عبور %K از %D زیر ۲۰",
        cross_up(C("stoch_k"), C("stoch_d")) & (C("stoch_k") < 20),
    ),
    "stoch_sell": (
        "stochastic",
        "sell",
        "استوکاستیک: عبور %K به زیر %D بالای ۸۰",
        cross_up(C("stoch_d"), C("stoch_k")) & (C("stoch_k") > 80),
    ),
    "willr_exit_oversold": (
        "stochastic",
        "buy",
        "ویلیامز %R: خروج از زیر −۸۰",
        (C("willr") > -80) & (lag(C("willr")) <= -80),
    ),
    "mfi_exit_oversold": (
        "mfi",
        "buy",
        "خروج MFI از زیر ۲۰",
        (C("mfi") > 20) & (lag(C("mfi")) <= 20),
    ),
    "mfi_exit_overbought": (
        "mfi",
        "sell",
        "برگشت MFI از بالای ۸۰",
        (C("mfi") < 80) & (lag(C("mfi")) >= 80),
    ),
    "obv_bull_divergence": (
        "obv",
        "buy",
        "OBV بالا رفته ولی قیمت ۲۰ روز افت کرده",
        turns_on((C("obv_chg20") > 0.1) & (C("ret20") < -0.05)),
    ),
    "obv_bear_divergence": (
        "obv",
        "sell",
        "OBV پایین آمده ولی قیمت ۲۰ روز بالا رفته",
        turns_on((C("obv_chg20") < -0.1) & (C("ret20") > 0.05)),
    ),
    "adx_trend_up": (
        "adx",
        "buy",
        "ADX بالای ۲۵ با +DI بالاتر از −DI",
        turns_on((C("adx") > 25) & (C("pdi") > C("mdi"))),
    ),
    "adx_trend_down": (
        "adx",
        "sell",
        "ADX بالای ۲۵ با −DI بالاتر از +DI",
        turns_on((C("adx") > 25) & (C("mdi") > C("pdi"))),
    ),
    "atr_squeeze": (
        "atr",
        "buy",
        "کمترین نوسان (ATR) در شش ماه",
        turns_on(C("atr_pct") <= C("atr_q10")),
    ),
    "bollinger_squeeze_break": (
        "bollinger",
        "buy",
        "شکست باند بالا پس از فشردگی بولینگر",
        (C("bbw") <= C("bbw_q10")) & cross_up(cl, C("bb_up")),
    ),
    "bollinger_below_lower": (
        "bollinger",
        "buy",
        "بسته شدن زیر باند پایین بولینگر",
        cross_up(C("bb_dn"), cl),
    ),
    "bollinger_above_upper": (
        "bollinger",
        "sell",
        "بسته شدن بالای باند بالای بولینگر",
        cross_up(cl, C("bb_up")),
    ),
    "vwap_cross_up": ("vwap", "buy", "بسته شدن بالای VWAP بیست‌روزه", cross_up(cl, C("vwap20"))),
    "ichimoku_break_cloud": (
        "ichimoku",
        "buy",
        "شکست ابر ایچیموکو با تنکان بالای کیجون",
        turns_on(_above_cloud) & (C("tenkan") > C("kijun")),
    ),
    "ichimoku_tk_cross_above_cloud": (
        "ichimoku",
        "buy",
        "تقاطع تنکان و کیجون بالای ابر",
        cross_up(C("tenkan"), C("kijun")) & _above_cloud,
    ),
    "close_under_cloud": ("ichimoku", "sell", "بسته شدن زیر ابر ایچیموکو", turns_on(_below_cloud)),
    "breakout_20_vol": (
        "support_resistance",
        "buy",
        "شکست مقاومت ۲۰ روزه با حجم دو برابر",
        cross_up(cl, C("hi20")) & (C("vr") > 2),
    ),
    "breakdown_20": ("support_resistance", "sell", "شکست حمایت ۲۰ روزه", cross_up(C("lo20"), cl)),
    "new_52w_high": ("support_resistance", "buy", "سقف تازهٔ ۵۲ هفته", cross_up(cl, C("hi250"))),
    "new_52w_low": ("support_resistance", "sell", "کف تازهٔ ۵۲ هفته", cross_up(C("lo250"), cl)),
    "pivot_r1_break": (
        "support_resistance",
        "buy",
        "بسته شدن بالای مقاومت اول پیوت",
        cross_up(cl, C("r1")),
    ),
    "pivot_s1_break": (
        "support_resistance",
        "sell",
        "بسته شدن زیر حمایت اول پیوت",
        cross_up(C("s1"), cl),
    ),
    "fib_618_bounce": (
        "fibonacci",
        "buy",
        "برگشت از سطح ۶۱٫۸٪ فیبوناچی",
        (C("low") <= C("fib618"))
        & (cl > C("fib618"))
        & (C("ret1") > 0)
        & ~((lag(C("low")) <= lag(C("fib618"))) & (lag(cl) > lag(C("fib618")))).fill_null(False),
    ),
    "rsi_bull_divergence": (
        "divergence",
        "buy",
        "واگرایی مثبت RSI",
        turns_on(
            (cl <= C("lo20c"))
            & (cl < C("prev_lo20"))
            & (C("rsi") > C("prev_rsi_min") + 5)
            & (C("rsi") < 40)
        ),
    ),
    "rsi_bear_divergence": (
        "divergence",
        "sell",
        "واگرایی منفی RSI",
        turns_on(
            (cl >= C("hi20c"))
            & (cl > C("prev_hi20c"))
            & (C("rsi") < C("prev_rsi_max") - 5)
            & (C("rsi") > 60)
        ),
    ),
    "gap_down": ("gap_fill", "buy", "گشایش با شکاف منفی ۳٪ (انتظار پر شدن)", C("gap") < -0.03),
    "gap_up": ("gap_fill", "sell", "گشایش با شکاف مثبت ۳٪ (انتظار پر شدن)", C("gap") > 0.03),
    "suspicious_volume_up": (
        "rel_volume",
        "buy",
        "حجم مشکوک با رشد و ورود حقیقی",
        turns_on((C("vr") > 3) & (C("ret1") > 0) & (C("net_i") > 0)),
    ),
    "suspicious_volume_down": (
        "rel_volume",
        "sell",
        "حجم مشکوک با افت و خروج حقیقی",
        turns_on((C("vr") > 3) & (C("ret1") < 0) & (C("net_i") < 0)),
    ),
    "heavy_real_money_in": (
        "net_flow",
        "buy",
        "ورود سنگین پول حقیقی",
        turns_on((C("net_i") > 0.2) & (C("power") > 2)),
    ),
    "heavy_real_money_out": (
        "net_flow",
        "sell",
        "خروج سنگین پول حقیقی",
        turns_on((C("net_i") < -0.2) & (C("power") < 0.5)),
    ),
    "power_over_2_three_days": (
        "buy_power",
        "buy",
        "قدرت خریدار بالای ۲ سه روز پشت‌سرهم",
        turns_on(C("power_hi").rolling_sum(3, min_samples=3).over(G) == 3),
    ),
    "per_capita_buy_high": (
        "per_capita_buy",
        "buy",
        "سرانهٔ خرید ۵ روزه ۱٫۵ برابر سرانهٔ فروش",
        turns_on(C("power5") > 1.5),
    ),
    "smart_money_combo": (
        "smart_money",
        "buy",
        "ترکیب پول هوشمند (قدرت، حجم، بالای میانگین)",
        turns_on((C("power") > 1.5) & (C("vr") > 2) & (cl > C("sma20")) & (C("ret1") > 0)),
    ),
    "drop_5d_10pct": (
        "return_n",
        "buy",
        "افت ۱۰٪ در ۵ روز (برگشت کوتاه)",
        turns_on(C("ret5") < -0.10),
    ),
    "rise_20d_30pct": (
        "return_n",
        "buy",
        "رشد ۳۰٪ در ۲۰ روز (ادامهٔ روند)",
        turns_on(C("ret20") > 0.30),
    ),
    "fvg_bull_retest": (
        "fvg",
        "buy",
        "برگشت به شکاف ارزش منصفانهٔ صعودی (FVG)",
        turns_on(
            (C("low") <= C("fb_top_y"))
            & (cl > C("fb_bot_y"))
            & C("fb_age_y").is_between(1, FVG_AGE)
        ),
    ),
    "fvg_bear_retest": (
        "fvg",
        "sell",
        "برگشت به شکاف ارزش منصفانهٔ نزولی (FVG)",
        turns_on(
            (C("high") >= C("fs_bot_y"))
            & (cl < C("fs_top_y"))
            & C("fs_age_y").is_between(1, FVG_AGE)
        ),
    ),
    "ifvg_bull": (
        "ifvg",
        "buy",
        "شکست رو به بالای FVG نزولی (iFVG صعودی)",
        cross_up(cl, C("fs_top_y")) & C("fs_age_y").is_between(1, FVG_AGE),
    ),
    "ifvg_bear": (
        "ifvg",
        "sell",
        "شکست رو به پایین FVG صعودی (iFVG نزولی)",
        cross_up(C("fb_bot_y"), cl) & C("fb_age_y").is_between(1, FVG_AGE),
    ),
    "elliott_wave3": ("elliott", "buy", "الیوت: پایان موج ۲ و شروع موج ۳", C("ew_w3")),
    "elliott_impulse_done": ("elliott", "sell", "الیوت: پایان موج ۵ صعودی", C("ew_5")),
    "elliott_abc_done": ("elliott", "buy", "الیوت: پایان اصلاح ABC", C("ew_abc")),
}


def with_outcomes(p: pl.DataFrame) -> pl.DataFrame:
    """Forward returns from the close of t+1, the liquid flag and the same-day excess."""
    entry = lag(cl, -1)
    p = p.with_columns(*[(lag(cl, -1 - h) / entry - 1).alias(f"f{h}") for h in H])
    p = p.with_columns(
        entry_up_locked=lag(C("lock_up"), -1).fill_null(False),
        entry_dn_locked=lag(C("lock_dn"), -1).fill_null(False),
    ).filter(C("n") >= MIN_HISTORY - 1)
    p = p.with_columns(
        liquid=(C("vmed20").rank("average").over("date") / pl.len().over("date"))
        >= 1 - LIQUID_SHARE,
        year=C("date").dt.year(),
    )
    # Each entry is compared with the liquid symbols one could also have traded that day:
    # ``x``/``u`` all of them, ``xb``/``ub`` those not locked up (buys), ``xs``/``us`` those not
    # locked down (sells). ``u`` is their share that went up, for the direction test.
    out = []
    for sfx, keep in (
        ("", C("liquid")),
        ("b", C("liquid") & ~C("entry_up_locked")),
        ("s", C("liquid") & ~C("entry_dn_locked")),
    ):
        for h in H:
            f = C(f"f{h}")
            out.append((f - f.filter(keep).mean().over("date")).alias(f"x{sfx}{h}"))
            up = (f > 0).cast(pl.Float64)
            out.append(up.filter(keep & f.is_not_null()).mean().over("date").alias(f"u{sfx}{h}"))
    return p.with_columns(out)


def flags(p: pl.DataFrame) -> pl.DataFrame:
    return p.with_columns(*[e.fill_null(False).alias("s_" + k) for k, (*_, e) in SIGNALS.items()])


def _f(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x)
    return None if np.isnan(v) else v


def _h(ok: pl.DataFrame, h: int, split: Any, sfx: str = "") -> dict[str, Any] | None:
    x_, u_ = f"x{sfx}{h}", f"u{sfx}{h}"
    ok = ok.filter(C(x_).is_not_null()).with_columns(C(x_).alias(f"x{h}"), C(u_).alias(f"u{h}"))
    if ok.height < 50:
        return None
    halves = [ok.filter(C("date") < split), ok.filter(C("date") >= split)]
    yr = ok.group_by("year").agg(C(f"x{h}").mean(), pl.len()).filter(C("len") >= 20)
    ym = yr[f"x{h}"].to_numpy()
    up = (ok[f"f{h}"] > 0).cast(pl.Float64)
    return {
        "n": ok.height,
        "excess_mean": float(ok[f"x{h}"].mean()),  # type: ignore[arg-type]
        "excess_median": float(ok[f"x{h}"].median()),  # type: ignore[arg-type]
        "beat": float((ok[f"x{h}"] > 0).mean()),  # type: ignore[arg-type]
        "up": float(up.mean()),  # type: ignore[arg-type]
        "up_all": float(ok[f"u{h}"].mean()),  # type: ignore[arg-type]
        "halves": [_f(x[f"x{h}"].mean()) if x.height else None for x in halves],
        "halves_up_edge": [
            _f(((x[f"f{h}"] > 0).cast(pl.Float64) - x[f"u{h}"]).mean()) if x.height else None
            for x in halves
        ],
        "years": len(ym),
        "years_pos": float((ym > 0).mean()) if len(ym) else None,
    }


def signal_stats(sub: pl.DataFrame, split: Any, sfx: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"n": sub.height, "symbols": sub[G].n_unique()}
    for h in H:
        out[f"h{h}"] = _h(sub, h, split, sfx)
    return out


def verdict(side: str, s: dict[str, Any], cost: float) -> dict[str, Any]:
    """``profit``: the first horizon whose signed mean excess beats the cost in both halves and
    is right in most years; ``backfires``: the signed excess is below minus the cost in both halves
    at 20 or 60 candles; ``direction``: short horizons where the up (or down) share beats all
    symbols by DIR_EDGE in both halves; ``reverse_small``: at 20 candles the move went against
    the textbook in both halves, by less than the cost."""
    sign = 1 if side == "buy" else -1
    profit = None
    for h in PROFIT_H:
        x = s.get(f"h{h}")
        if not x or None in x["halves"]:
            continue
        a, b = (sign * v for v in x["halves"])
        yp = x["years_pos"] if sign == 1 else 1 - (x["years_pos"] or 0)
        if a > cost and b > cost and (yp or 0) >= MIN_YEARS_SHARE:
            profit = h
            break
    backfires = False
    for h in (20, 60):
        x = s.get(f"h{h}")
        if x and None not in x["halves"] and all(sign * v < -cost for v in x["halves"]):
            backfires = True
    direction = [
        h
        for h in SHORT
        if (x := s.get(f"h{h}"))
        and None not in x["halves_up_edge"]
        and all(sign * v >= DIR_EDGE for v in x["halves_up_edge"])
    ]
    x20 = s.get("h20")
    reverse = bool(x20 and None not in x20["halves"] and all(sign * v < 0 for v in x20["halves"]))
    if x20 is None:
        label = "too_few"
    elif profit:
        label = "works"
    elif backfires:
        label = "backfires"
    elif direction:
        label = "direction_only"
    elif reverse:
        label = "reverse_small"  # the other way round in both halves, but below the cost
    else:
        label = "no_edge"
    return {"label": label, "profit_horizon": profit, "direction_horizons": direction}


def history(sig: pl.DataFrame, cost: float) -> dict[str, Any]:
    liq = sig.filter(C("liquid"))
    days = liq["date"].unique().sort()
    split = days[len(days) // 2]
    out: dict[str, Any] = {
        "split_date": str(split),
        "first": str(days[0]),
        "last": str(days[-1]),
        "base": signal_stats(liq, split),
        "signals": {},
    }
    for k, (term, side, title, _) in SIGNALS.items():
        fired = liq.filter(C("s_" + k))
        lk = "entry_up_locked" if side == "buy" else "entry_dn_locked"
        locked = C(lk)
        s = signal_stats(fired.filter(~locked), split, "b" if side == "buy" else "s")
        with_locked = _h(fired, 20, split)
        out["signals"][k] = {
            "term": term,
            "side": side,
            "title": title,
            **s,
            **verdict(side, s, cost),
            "locked_share": float(fired[lk].mean()) if fired.height else None,  # type: ignore[arg-type]
            "x20_with_locked": with_locked["excess_mean"] if with_locked else None,
        }
    return out


NOW_COLS = (
    "close", "rsi", "macd", "macd_sig", "stoch_k", "stoch_d", "willr", "mfi", "adx", "pdi", "mdi",
    "atr_pct", "bb_up", "bb_dn", "sma20", "sma50", "sma200", "ema12", "ema26", "vwap20", "tenkan",
    "kijun", "cloud_top", "cloud_bot", "hi20", "lo20", "hi250", "lo250", "hi120", "lo120",
    "fib618", "pivot", "r1", "s1", "obv_chg20", "vr", "net5", "power5",
)  # fmt: skip


def current(sig: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """Each symbol's last indicator values and the signals it fired in its last RECENT days."""
    s = sig.sort(G, "date")
    last = s.group_by(G).agg(*[C(c).last() for c in ("date", *NOW_COLS)])
    tail = s.group_by(G).tail(RECENT).with_columns(ago=pl.int_range(pl.len(), 0, -1).over(G) - 1)
    fired: dict[int, list[dict[str, Any]]] = {}
    keys = list(SIGNALS)
    long = (
        tail.select(G, "date", "ago", *["s_" + k for k in keys])
        .unpivot(index=[G, "date", "ago"], variable_name="k", value_name="on")
        .filter(C("on"))
    )
    for r in long.sort("ago").iter_rows(named=True):
        lst = fired.setdefault(int(r[G]), [])
        k = r["k"][2:]
        if all(x["key"] != k for x in lst):
            lst.append({"key": k, "date": str(r["date"]), "ago": int(r["ago"])})
    out: dict[int, dict[str, Any]] = {}
    for r in last.iter_rows(named=True):
        out[int(r[G])] = {
            "date": str(r["date"]),
            **{c: _f(r[c]) for c in NOW_COLS},
            "fired": fired.get(int(r[G]), []),
        }
    return out


def risk(sig: pl.DataFrame, rf_annual: float | None) -> dict[int, dict[str, Any]]:
    """The last 250 trading days per symbol (longer than a year when it was halted):
    volatility, 1-day 95% VaR, max drawdown, Sharpe and
    Sortino (excess over the one-year treasury yield when known)."""
    s = sig.sort(G, "date").group_by(G).tail(MIN_HISTORY)
    out: dict[int, dict[str, Any]] = {}
    rf_d = (1 + rf_annual) ** (1 / 250) - 1 if rf_annual is not None else 0.0
    for (iid,), g0 in s.group_by(G):
        g = g0.sort("date")
        r = g["ret1"].drop_nulls().to_numpy()
        c = g["close"].to_numpy()
        if len(r) < 200:
            continue
        vol = float(r.std(ddof=1))
        ex = r - rf_d
        down = ex[ex < 0]
        dsd = float(np.sqrt((down**2).sum() / len(ex))) if len(down) else 0.0
        peak = np.maximum.accumulate(c)
        out[int(iid)] = {
            "vol_ann": vol * np.sqrt(250),
            "var95": float(-np.quantile(r, 0.05)),
            "max_dd": float((c / peak - 1).min()),
            "ret_1y": float(c[-1] / c[0] - 1),
            "sharpe": float(ex.mean() / vol * np.sqrt(250)) if vol > 0 else None,
            "sortino": float(ex.mean() / dsd * np.sqrt(250)) if dsd > 0 else None,
            "days": len(r),
            "from": str(g["date"][0]),
        }
    return out
