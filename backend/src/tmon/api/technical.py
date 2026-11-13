"""The glossary-signals document (``tmon.tools.ta_signals``) turned into plain readings.

``technical_out`` is the symbol's part for its dashboard, ``signals_out`` the tested history for
the glossary. Every sentence follows the stored numbers; none of it feeds the verdict.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from tmon.api.schemas import (
    DashRisk,
    DashTaFired,
    DashTaValue,
    DashTechnical,
    TaHorizon,
    TaSignal,
    TaSignalsOut,
)
from tmon.core.config import get_settings
from tmon.storage.objectstore import get_object_store
from tmon.tools.ta_signals import KEY

log = logging.getLogger(__name__)
CACHE_SECONDS = 300
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def load_doc(key: str) -> dict[str, Any] | None:
    """A stored research document, parsed once every few minutes (they run to a few MB)."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        doc: dict[str, Any] | None = json.loads(
            get_object_store().get(get_settings().minio_artifact_bucket, key)
        )
    except (FileNotFoundError, KeyError):
        doc = None
    except Exception:  # store unreachable: leave the card out instead of failing the page
        log.warning("%s unreadable", key, exc_info=True)
        doc = None
    _cache[key] = (time.monotonic(), doc)
    return doc


def ta_doc() -> dict[str, Any] | None:
    return load_doc(KEY)


def _pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f}٪".replace("-", "−")


def _abs_pct(x: float, digits: int = 1) -> str:
    return f"{abs(x) * 100:.{digits}f}٪"


def verdict_sentence(s: dict[str, Any], cost: float) -> str:
    """One plain sentence on what the reading did in the past, from its stored numbers."""
    label, side = s["label"], s["side"]
    sign = 1 if side == "buy" else -1
    word = "خرید" if side == "buy" else "فروش"
    if label == "works":
        h = s["profit_horizon"]
        x = s[f"h{h}"]
        better = "بهتر" if x["excess_mean"] > 0 else "بدتر"
        return (
            f"در گذشته جواب داده: {h} روز بعد به‌طور میانگین {_abs_pct(x['excess_mean'])} {better} "
            "از "
            f"بازار بوده و در هر دو نیمهٔ تاریخچه بیش از کارمزد ({_abs_pct(cost)}). "
            f"نشانهٔ {word} قابل اعتنا."
        )
    if label == "backfires":
        return (
            f"برعکس کتاب عمل کرده: بعد از این نشانهٔ {word}، سهم در هر دو نیمهٔ تاریخچه بیش از "
            "کارمزد خلاف جهت رفته."
        )
    if label == "direction_only":
        h = s["direction_horizons"][0]
        x = s[f"h{h}"]
        up, base = (x["up"], x["up_all"]) if sign == 1 else (1 - x["up"], 1 - x["up_all"])
        move = "بالا" if sign == 1 else "پایین"
        return (
            f"جهت {h} روز بعد را کمی بیشتر از معمول درست گفته ({round(up * 100)} از ۱۰۰ بار "
            f"{move} رفته، در برابر {round(base * 100)} برای همهٔ سهم‌ها)، ولی سودش به کارمزد "
            "نمی‌رسد. فقط برای زمان‌بندی، نه دلیل خرید یا فروش."
        )
    if label == "reverse_small":
        x = s["h20"]
        return (
            f"در هر دو نیمهٔ تاریخچه خلاف کتاب رفته ({_pct(x['excess_mean'])} نسبت به بازار در "
            "۲۰ روز)، ولی کمتر از کارمزد. به آن تکیه نکنید."
        )
    if label == "too_few":
        return "موارد کافی برای داوری نیست."
    return "در تاریخچهٔ بورس تهران نه سود روشنی داشته نه جهت را بهتر از شانس گفته."


def _horizons(s: dict[str, Any], hs: list[int]) -> list[TaHorizon]:
    out = []
    for h in hs:
        x = s.get(f"h{h}")
        if x:
            out.append(TaHorizon(h=h, **{k: x[k] for k in TaHorizon.model_fields if k in x}))
    return out


def signals_out(doc: dict[str, Any] | None) -> TaSignalsOut:
    if not doc:
        return TaSignalsOut(available=False)
    cost = doc["round_trip_cost"]
    return TaSignalsOut(
        available=True,
        as_of=doc["as_of"],
        round_trip_cost=cost,
        dir_edge=doc.get("dir_edge"),
        history_first=doc["first"],
        history_last=doc["last"],
        split_date=doc["split_date"],
        signals=[
            TaSignal(
                key=k,
                term=s["term"],
                side=s["side"],
                title=s["title"],
                label=s["label"],
                verdict=verdict_sentence(s, cost),
                n=s["n"],
                symbols=s["symbols"],
                locked_share=s.get("locked_share"),
                x20_with_locked=s.get("x20_with_locked"),
                profit_horizon=s.get("profit_horizon"),
                direction_horizons=s.get("direction_horizons") or [],
                horizons=_horizons(s, doc["horizons"]),
            )
            for k, s in doc["signals"].items()
        ],
    )


def _level(x: float, lo: float, hi: float) -> str:
    return "buy" if x <= lo else "sell" if x >= hi else "neutral"


def _values(v: dict[str, Any]) -> list[DashTaValue]:
    """Each indicator with the reading a textbook gives it; the tone is that textbook side."""
    out: list[DashTaValue] = []
    c = v.get("close")

    def add(key: str, term: str, name: str, value: Any, unit: str, reading: str, tone: str) -> None:
        out.append(
            DashTaValue(
                key=key,
                term=term,
                name=name,
                value=value,
                unit=unit,
                reading=reading,
                tone=tone,
            )
        )

    def side_of(level: Any, name: str, term: str, key: str, unit: str = "price") -> None:
        if c is None or level is None:
            return
        up = c > level
        add(
            key,
            term,
            name,
            level,
            unit,
            f"قیمت {abs(c / level - 1) * 100:.1f}٪ {'بالای' if up else 'زیر'} آن است",
            "buy" if up else "sell",
        )

    if (r := v.get("rsi")) is not None:
        txt = "اشباع فروش (زیر ۳۰)" if r < 30 else "اشباع خرید (بالای ۷۰)" if r > 70 else "میانه"
        add("rsi", "rsi", "RSI ۱۴ روزه", r, "num", txt, _level(r, 30, 70))
    if (m := v.get("macd")) is not None and (sg := v.get("macd_sig")) is not None:
        up = m > sg
        add(
            "macd",
            "macd",
            "مکدی منهای خط سیگنال",
            m - sg,
            "price",
            f"مکدی {'بالای' if up else 'زیر'} خط سیگنال، {'بالای' if m > 0 else 'زیر'} صفر",
            "buy" if up else "sell",
        )
    if (k := v.get("stoch_k")) is not None:
        d = v.get("stoch_d")
        txt = "زیر ۲۰" if k < 20 else "بالای ۸۰" if k > 80 else "میانه"
        if d is not None:
            txt += f"؛ %K {'بالای' if k > d else 'زیر'} %D"
        add("stoch", "stochastic", "استوکاستیک %K", k, "num", txt, _level(k, 20, 80))
    if (w := v.get("willr")) is not None:
        txt = "میانه"
        if w < -80:
            txt = "زیر −۸۰ (اشباع فروش)"
        elif w > -20:
            txt = "بالای −۲۰ (اشباع خرید)"
        add("willr", "stochastic", "ویلیامز %R", w, "num", txt, _level(w, -80, -20))
    if (mf := v.get("mfi")) is not None:
        txt = "زیر ۲۰" if mf < 20 else "بالای ۸۰" if mf > 80 else "میانه"
        add("mfi", "mfi", "MFI ۱۴ روزه", mf, "num", txt, _level(mf, 20, 80))
    if (a := v.get("adx")) is not None:
        pdi, mdi = v.get("pdi") or 0, v.get("mdi") or 0
        if a < 20:
            txt, tone = "روند ضعیف یا بی‌روند (زیر ۲۰)", "neutral"
        else:
            strong = "قوی" if a > 25 else "متوسط"
            way = "صعودی" if pdi > mdi else "نزولی"
            txt = f"روند {strong} {way} (+DI {pdi:.0f}، −DI {mdi:.0f})"
            tone = "buy" if pdi > mdi else "sell"
        add("adx", "adx", "ADX ۱۴ روزه", a, "num", txt, tone)
    if (at := v.get("atr_pct")) is not None:
        add(
            "atr",
            "atr",
            "ATR (درصد قیمت)",
            at,
            "pct",
            f"نوسان معمول یک روز حدود {at * 100:.1f}٪ قیمت",
            "neutral",
        )
    if c is not None and v.get("bb_up") is not None and v.get("bb_dn") is not None:
        up, dn = v["bb_up"], v["bb_dn"]
        pos = (c - dn) / (up - dn) if up > dn else 0.5
        txt = (
            "بالای باند بالا"
            if c > up
            else "زیر باند پایین"
            if c < dn
            else (f"داخل باندها ({round(pos * 100)}٪ از پایین تا بالا)")
        )
        add(
            "bollinger",
            "bollinger",
            "جای قیمت در باند بولینگر",
            pos,
            "pct",
            txt,
            "buy" if c < dn else "sell" if c > up else "neutral",
        )
    side_of(v.get("sma20"), "میانگین ساده ۲۰ روزه", "sma", "sma20")
    side_of(v.get("sma50"), "میانگین ساده ۵۰ روزه", "sma", "sma50")
    side_of(v.get("sma200"), "میانگین ساده ۲۰۰ روزه", "sma", "sma200")
    if (e12 := v.get("ema12")) is not None and (e26 := v.get("ema26")) is not None:
        add(
            "ema",
            "ema",
            "EMA ۱۲ منهای EMA ۲۶",
            e12 - e26,
            "price",
            f"EMA ۱۲ {'بالای' if e12 > e26 else 'زیر'} EMA ۲۶",
            "buy" if e12 > e26 else "sell",
        )
    side_of(v.get("vwap20"), "VWAP بیست‌روزه", "vwap", "vwap20")
    if c is not None and v.get("cloud_top") is not None and v.get("cloud_bot") is not None:
        top, bot = v["cloud_top"], v["cloud_bot"]
        where = "بالای ابر" if c > top else "زیر ابر" if c < bot else "داخل ابر"
        tk = ""
        if v.get("tenkan") is not None and v.get("kijun") is not None:
            tk = f"؛ تنکان {'بالای' if v['tenkan'] > v['kijun'] else 'زیر'} کیجون"
        add(
            "ichimoku",
            "ichimoku",
            "ایچیموکو: لبهٔ بالای ابر",
            top,
            "price",
            where + tk,
            "buy" if c > top else "sell" if c < bot else "neutral",
        )
    if c is not None and v.get("hi20") and v.get("lo20"):
        add(
            "res20",
            "support_resistance",
            "مقاومت ۲۰ روزه (بالاترین)",
            v["hi20"],
            "price",
            f"{(v['hi20'] / c - 1) * 100:.1f}٪ بالاتر از قیمت" if c <= v["hi20"] else "شکسته شده",
            "buy" if c > v["hi20"] else "neutral",
        )
        add(
            "sup20",
            "support_resistance",
            "حمایت ۲۰ روزه (پایین‌ترین)",
            v["lo20"],
            "price",
            f"{(1 - v['lo20'] / c) * 100:.1f}٪ پایین‌تر از قیمت" if c >= v["lo20"] else "شکسته شده",
            "sell" if c < v["lo20"] else "neutral",
        )
    if c is not None and v.get("hi250") and v.get("lo250"):
        add(
            "hi52",
            "support_resistance",
            "سقف ۵۲ هفته",
            v["hi250"],
            "price",
            f"قیمت {(1 - c / v['hi250']) * 100:.0f}٪ زیر سقف" if c <= v["hi250"] else "سقف تازه",
            "neutral",
        )
        add(
            "lo52",
            "support_resistance",
            "کف ۵۲ هفته",
            v["lo250"],
            "price",
            f"قیمت {(c / v['lo250'] - 1) * 100:.0f}٪ بالای کف" if c >= v["lo250"] else "کف تازه",
            "neutral",
        )
    if c is not None and v.get("fib618"):
        add(
            "fib618",
            "fibonacci",
            "فیبوناچی ۶۱٫۸٪ (دامنهٔ ۱۲۰ روز)",
            v["fib618"],
            "price",
            f"قیمت {abs(c / v['fib618'] - 1) * 100:.1f}٪ {'بالای' if c > v['fib618'] else 'زیر'} "
            "این سطح",
            "neutral",
        )
    if c is not None and v.get("pivot") and v.get("r1") and v.get("s1"):
        add(
            "pivot",
            "support_resistance",
            "پیوت دیروز (مقاومت اول / حمایت اول)",
            v["pivot"],
            "price",
            f"R1 {v['r1']:,.0f} · S1 {v['s1']:,.0f}",
            "buy" if c > v["r1"] else "sell" if c < v["s1"] else "neutral",
        )
    if (o := v.get("obv_chg20")) is not None:
        add(
            "obv",
            "obv",
            "OBV: تغییر ۲۰ روزه به نسبت حجم",
            o,
            "pct",
            "حجم روزهای مثبت بیشتر بوده" if o > 0 else "حجم روزهای منفی بیشتر بوده",
            "buy" if o > 0.1 else "sell" if o < -0.1 else "neutral",
        )
    if (vr := v.get("vr")) is not None:
        txt = "حجم مشکوک (بیش از ۳ برابر)" if vr > 3 else "بالاتر از معمول" if vr > 1.5 else "عادی"
        add("vr", "rel_volume", "حجم امروز به میانگین ۲۰ روز", vr, "x", txt, "neutral")
    if (p5 := v.get("power5")) is not None:
        txt = "خریداران حقیقی درشت‌تر" if p5 > 1 else "فروشندگان حقیقی درشت‌تر"
        add(
            "power5",
            "per_capita_buy",
            "قدرت خریدار (میانگین ۵ روز)",
            p5,
            "x",
            txt,
            "buy" if p5 > 1.5 else "sell" if p5 < 0.67 else "neutral",
        )
    if (n5 := v.get("net5")) is not None:
        add(
            "net5",
            "net_flow",
            "ورود پول حقیقی (۵ روز، سهم از ارزش)",
            n5,
            "pct",
            "ورود" if n5 > 0 else "خروج",
            "neutral",
        )
    return out


def technical_out(
    doc: dict[str, Any] | None, instrument_id: int, beta_index: float | None = None
) -> DashTechnical | None:
    if not doc:
        return None
    v = doc["now"].get(str(instrument_id))
    if v is None:
        return None
    cost = doc["round_trip_cost"]
    sigs = doc["signals"]
    fired = [
        DashTaFired(
            key=f["key"],
            term=sigs[f["key"]]["term"],
            title=sigs[f["key"]]["title"],
            side=sigs[f["key"]]["side"],
            date=f["date"],
            ago=f["ago"],
            label=sigs[f["key"]]["label"],
            verdict=verdict_sentence(sigs[f["key"]], cost),
        )
        for f in v["fired"]
        if f["key"] in sigs
    ]
    r = doc["risk"].get(str(instrument_id))
    risk = (
        DashRisk(
            from_date=r["from"],
            days=r["days"],
            ret_1y=r["ret_1y"],
            vol_ann=r["vol_ann"],
            var95=r["var95"],
            max_dd=r["max_dd"],
            sharpe=r.get("sharpe"),
            sortino=r.get("sortino"),
            rf_annual=doc.get("rf_annual"),
            beta_index=beta_index,
        )
        if r
        else None
    )
    works = [f for f in fired if f.label == "works"]
    lines = []
    if works:
        for f in works:
            when = "در آخرین روز معامله" if f.ago == 0 else f"{f.ago} روز معاملاتی پیش"
            lines.append(f"«{f.title}» {when} دیده شد. {f.verdict}")
    else:
        lines.append(
            f"از {len(fired)} نشانهٔ کلاسیکی که این سهم در {doc['recent_days']} روز اخیر داده، "
            "هیچ‌کدام در تاریخچهٔ بورس تهران سودی بیش از کارمزد نداشته؛ تصمیم را بر آن‌ها نگذارید."
            if fired
            else f"در {doc['recent_days']} روز اخیر نشانهٔ کلاسیکی دیده نشد."
        )
    return DashTechnical(
        as_of=v["date"],
        recent_days=doc["recent_days"],
        round_trip_cost=cost,
        values=_values(v),
        fired=fired,
        risk=risk,
        lines=lines,
    )
