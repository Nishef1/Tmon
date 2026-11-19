"""Derived columns of every stock, built only from tables already stored (no new data source).

Prices, volume and value, real/legal flows, the reduced order book, shareholders, share counts,
statements and the dollar rate are combined into the columns a trader looks for on a market
screen: period returns, distance from the daily limits and from the highs, volume against its
averages, beta, net buying, order values, float, index impact, valuation multiples and so on.

Nothing here feeds the model or the verdict. Each column says in :data:`CATALOG` what it is; the
few that are an owner-side estimate (float, index weight) or an untested count (the two scores,
the candle pattern) are labelled as such. A symbol without the data behind a column gets ``None``
for it, never a fill-in value.

The price block is the only heavy step (five years of bars of every stock). It is kept for exactly
as long as the bars behind it are unchanged (a fingerprint of the data, never a clock).
"""

from __future__ import annotations

import datetime as dt
import statistics
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from tmon.core.engine_config import get_engine_config
from tmon.domain.enums import InstrumentType
from tmon.features import fundamentals
from tmon.features.adjustment import apply_adjustments
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    MacroSeries,
    MarketIndexDaily,
    OrderBookDaily,
    PriceAdjustment,
    PriceDaily,
    Shareholder,
)

Value = float | str | None
Row = dict[str, Value]

HISTORY_DAYS = 1900  # calendar days of bars loaded: five years and the warm-up of the averages
MAX_DAY_MOVE = 0.5  # a larger one-day move is a first listing day or a stale reference price
USD_SERIES = "usd_free"
DEFAULT_BAND = 0.03  # daily price band when the bar stores no limit (docs/01, unverified)

RETURN_DAYS = {
    "ret_1w": 7,
    "ret_1m": 30,
    "ret_3m": 90,
    "ret_6m": 182,
    "ret_1y": 365,
    "ret_3y": 1096,
    "ret_5y": 1826,
}


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    group: str
    kind: str  # percent | ratio | multiple | money | count | price | score | text
    hint: str = ""
    default: bool = False  # shown without the user choosing it


GROUPS = {
    "returns": "بازدهی",
    "range": "دامنه، سقف‌ها و سطوح",
    "activity": "حجم و ارزش معاملات",
    "risk": "ریسک (بتا)",
    "flow": "حقیقی و حقوقی",
    "book": "سفارش‌های روی تابلو",
    "size": "اندازه، شناوری و اثر روی شاخص",
    "growth": "رشد",
    "margins": "سودآوری",
    "balance": "ساختار مالی",
    "multiples": "ارزش‌گذاری",
    "scores": "امتیازها و الگوها",
    "listing": "پذیرش و سال مالی",
}

NO_STMT = "صورت مالی این نماد ذخیره نشده است"
NO_BOOK = "تابلوی ذخیره‌شده فقط برای ۱۶۰ نمادِ پرمعامله هست"

CATALOG: tuple[Col, ...] = (
    Col("ret_1w", "بازدهی هفته", "returns", "percent", "قیمت پایانی تعدیل‌شده، ۷ روز تقویمی", True),
    Col("ret_1m", "بازدهی ماه", "returns", "percent", "۳۰ روز تقویمی", True),
    Col("ret_3m", "بازدهی ۳ ماه", "returns", "percent", "۹۰ روز تقویمی"),
    Col("ret_6m", "بازدهی ۶ ماه", "returns", "percent", "۱۸۲ روز تقویمی"),
    Col("ret_1y", "بازدهی سال", "returns", "percent", "۳۶۵ روز تقویمی", True),
    Col("ret_3y", "بازدهی ۳ سال", "returns", "percent", "نمادی که آن زمان نبوده خالی است"),
    Col("ret_5y", "بازدهی ۵ سال", "returns", "percent", "نمادی که آن زمان نبوده خالی است"),
    Col(
        "dist_ceiling",
        "فاصله تا سقف مجاز",
        "range",
        "percent",
        "قیمت پایانی نسبت به سقف روز؛ صفر یعنی روی سقف",
    ),
    Col(
        "dist_floor",
        "فاصله از کف مجاز",
        "range",
        "percent",
        "قیمت پایانی نسبت به کف روز؛ صفر یعنی روی کف",
    ),
    Col(
        "to_high_3m",
        "تا سقف ۳ ماهه",
        "range",
        "percent",
        "قیمت پایانی نسبت به بالاترین قیمت ۹۰ روز اخیر",
    ),
    Col(
        "to_high_1y",
        "تا سقف یک‌ساله",
        "range",
        "percent",
        "قیمت پایانی نسبت به بالاترین قیمت ۳۶۵ روز اخیر",
        True,
    ),
    Col(
        "support",
        "حمایت نزدیک",
        "range",
        "price",
        "بالاترین کف موضعی زیر قیمت در ۱۲۰ روز (قیمت تعدیل‌شده)",
    ),
    Col("support_dist", "فاصله تا حمایت", "range", "percent", "قیمت پایانی نسبت به حمایت"),
    Col(
        "resistance", "مقاومت نزدیک", "range", "price", "پایین‌ترین سقف موضعی بالای قیمت در ۱۲۰ روز"
    ),
    Col("resistance_dist", "فاصله تا مقاومت", "range", "percent", "قیمت پایانی نسبت به مقاومت"),
    Col(
        "vol_vs_30",
        "حجم نسبت به میانگین ۳۰ روز",
        "activity",
        "multiple",
        "حجم امروز ÷ میانگین ۳۰ روز معاملاتی پیش از امروز",
        True,
    ),
    Col(
        "vol_vs_200",
        "حجم نسبت به میانگین ۲۰۰ روز",
        "activity",
        "multiple",
        "حداقل ۱۰۰ روز سابقه لازم است",
    ),
    Col(
        "value_vs_30",
        "ارزش نسبت به میانگین ۳۰ روز",
        "activity",
        "multiple",
        "ارزش معاملهٔ امروز ÷ میانگین ۳۰ روز",
    ),
    Col(
        "value_vs_200",
        "ارزش نسبت به میانگین ۲۰۰ روز",
        "activity",
        "multiple",
        "حداقل ۱۰۰ روز سابقه لازم است",
    ),
    Col("avg_vol_90", "میانگین حجم ۹۰ روز", "activity", "count", "سهم"),
    Col("avg_vol_200", "میانگین حجم ۲۰۰ روز", "activity", "count", "سهم"),
    Col(
        "vol_to_float", "حجم به سهام شناور", "activity", "percent", "حجم امروز ÷ سهام شناورِ برآوردی"
    ),
    Col(
        "value_to_mcap",
        "ارزش به ارزش بازار",
        "activity",
        "percent",
        "ارزش معاملهٔ امروز ÷ ارزش بازار",
    ),
    Col(
        "beta_90d", "بتا ۹۰ روزه", "risk", "ratio", "بازده روزانه در برابر شاخص کل، ۹۰ روز معاملاتی"
    ),
    Col("beta_60w", "بتا ۶۰ هفته‌ای", "risk", "ratio", "بازده هفتگی در برابر شاخص کل"),
    Col("beta_36m", "بتا ۳۶ ماهه", "risk", "ratio", "بازده ماهانه در برابر شاخص کل"),
    Col(
        "real_net_pct",
        "خرید خالص حقیقی (سهم از ارزش)",
        "flow",
        "percent",
        "(خرید − فروش حقیقی) ÷ ارزش معامله",
        True,
    ),
    Col(
        "legal_net_pct",
        "خرید خالص حقوقی (سهم از ارزش)",
        "flow",
        "percent",
        "(خرید − فروش حقوقی) ÷ ارزش معامله",
    ),
    Col(
        "real_net_5d_pct",
        "خرید خالص حقیقی ۵ روز",
        "flow",
        "percent",
        "جمع ۵ روز ÷ جمع ارزش همان روزها",
    ),
    Col(
        "real_net_20d_pct",
        "خرید خالص حقیقی ۲۰ روز",
        "flow",
        "percent",
        "جمع ۲۰ روز ÷ جمع ارزش همان روزها",
    ),
    Col(
        "real_net_vs_avg",
        "خرید خالص حقیقی نسبی",
        "flow",
        "percent",
        "خرید خالص حقیقی امروز ÷ میانگین ارزش روزانه ۳۰ روز",
    ),
    Col("real_buy_power", "قدرت خریدار حقیقی", "flow", "ratio", "سرانهٔ خرید ÷ سرانهٔ فروش حقیقی"),
    Col("legal_buy_power", "قدرت خریدار حقوقی", "flow", "ratio", "سرانهٔ خرید ÷ سرانهٔ فروش حقوقی"),
    Col("buy_order_value", "ارزش سفارش خرید", "book", "money", NO_BOOK),
    Col("sell_order_value", "ارزش سفارش فروش", "book", "money", NO_BOOK),
    Col(
        "net_order_value",
        "ارزش خالص سفارش",
        "book",
        "money",
        "خرید − فروش در بهترین قیمت پایان جلسه",
    ),
    Col(
        "demand_pressure",
        "فشار تقاضا",
        "book",
        "ratio",
        "(حجم خرید − فروش) ÷ جمع، پنج ردیف تابلو؛ از −۱ تا +۱",
    ),
    Col("queue_value", "ارزش صف", "book", "money", "مثبت صف خرید، منفی صف فروش، در پایان جلسه"),
    Col(
        "peak_queue_value",
        "ارزش بزرگ‌ترین صف",
        "book",
        "money",
        "بزرگ‌ترین صف یک‌طرفهٔ روز × قیمت پایانی",
    ),
    Col("shares", "تعداد سهام", "size", "count"),
    Col("mcap", "ارزش بازار", "size", "money", "تعداد سهام × قیمت پایانی", True),
    Col(
        "float_pct",
        "سهم شناور (برآورد)",
        "size",
        "percent",
        "۱۰۰٪ منهای سهم سهامداران بالای ۱٪؛ رقم رسمی بورس نیست",
    ),
    Col("float_shares", "سهام شناور (برآورد)", "size", "count", "برآورد از فهرست سهامداران عمده"),
    Col("float_value", "ارزش شناور (برآورد)", "size", "money", "سهام شناور × قیمت پایانی"),
    Col(
        "index_weight",
        "وزن در شاخص کل (برآورد)",
        "size",
        "percent",
        "ارزش بازار ÷ جمع ارزش بازار نمادهای امروز",
    ),
    Col(
        "index_impact",
        "اثر امروز روی شاخص کل (برآورد)",
        "size",
        "percent",
        "وزن × بازدهی امروز، به درصدِ شاخص",
    ),
    Col("industry_value_share", "سهم از ارزش معاملات صنعت", "size", "percent"),
    Col("industry_mcap_share", "سهم از ارزش بازار صنعت", "size", "percent"),
    Col("price_usd", "قیمت به دلار", "size", "ratio", "قیمت پایانی ÷ نرخ دلار آزاد همان روز"),
    Col("mcap_usd", "ارزش بازار به دلار", "size", "money", "ارزش بازار ÷ نرخ دلار آزاد"),
    Col(
        "rev_yoy",
        "رشد درآمد نسبت به سال قبل",
        "growth",
        "percent",
        "همان دوره‌ی سال قبل؛ " + NO_STMT,
    ),
    Col(
        "net_yoy", "رشد سود خالص نسبت به سال قبل", "growth", "percent", "پایهٔ منفی یا صفر رشد ندارد"
    ),
    Col("rev_qoq", "رشد درآمد نسبت به فصل قبل", "growth", "percent", "فصل از تفاضل دو صورت تجمعی"),
    Col("net_qoq", "رشد سود خالص نسبت به فصل قبل", "growth", "percent"),
    Col("gross_margin", "حاشیه سود ناخالص", "margins", "percent", "سود ناخالص ÷ درآمد عملیاتی"),
    Col("op_margin", "حاشیه سود عملیاتی", "margins", "percent"),
    Col("net_margin", "حاشیه سود خالص", "margins", "percent"),
    Col(
        "roe",
        "بازده حقوق صاحبان سهام",
        "margins",
        "percent",
        "سود ۱۲ ماههٔ منتهی به آخرین صورت ÷ حقوق مالکانه",
    ),
    Col("roa", "بازده دارایی‌ها", "margins", "percent", "سود ۱۲ ماهه ÷ جمع دارایی‌ها"),
    Col("debt_to_assets", "بدهی به دارایی", "balance", "ratio", "جمع بدهی‌ها ÷ جمع دارایی‌ها"),
    Col("fin_debt_to_equity", "تسهیلات مالی به حقوق مالکانه", "balance", "ratio"),
    Col("current_ratio", "نسبت جاری", "balance", "ratio", "دارایی جاری ÷ بدهی جاری"),
    Col(
        "pe_ttm",
        "P/E (۱۲ ماهه)",
        "multiples",
        "multiple",
        "ارزش بازار ÷ سود خالص ۱۲ ماهه؛ زیان‌ده خالی است",
        True,
    ),
    Col("ps_ttm", "P/S", "multiples", "multiple", "ارزش بازار ÷ درآمد ۱۲ ماهه"),
    Col("pb", "P/B", "multiples", "multiple", "ارزش بازار ÷ حقوق مالکانه"),
    Col(
        "tech_score",
        "امتیاز تکنیکال",
        "scores",
        "score",
        "درصد شش شرط برقرار (بالای میانگین ۲۰/۵۰/۲۰۰ روزه، RSI بالای ۵۰، MACD مثبت، "
        "بازده ماه مثبت)؛ شمارش است نه پیش‌بینی و آزمون‌نشده",
    ),
    Col(
        "fund_score",
        "امتیاز بنیادی",
        "scores",
        "score",
        "درصد شش شرط برقرار (رشد درآمد و سود، حاشیه و ROE مثبت، نسبت جاری بالای ۱، "
        "بدهی کمتر از دارایی)؛ آزمون‌نشده",
    ),
    Col(
        "pattern",
        "الگوی کندل امروز",
        "scores",
        "text",
        "تعریف کتابی (دوجی، چکش، ستارهٔ دنباله‌دار، بلعیدن)؛ آزمون‌نشده",
    ),
    Col(
        "first_day",
        "اولین روز معامله",
        "listing",
        "text",
        "اولین روز ثبت‌شده؛ از ۱۳۸۰ به قبل داده نداریم",
    ),
    Col("ipo_price", "قیمت پایهٔ اولین روز", "listing", "price", "قیمت مرجع روز اول، ریال"),
    Col("fiscal_year_end", "پایان سال مالی", "listing", "text", NO_STMT),
)
BY_KEY = {c.key: c for c in CATALOG}
TEXT_KEYS = {c.key for c in CATALOG if c.kind == "text"}


# ---------------------------------------------------------------- price block

_cache: dict[tuple[object, ...], dict[int, Row]] = {}
_lock = threading.Lock()
_compute_lock = threading.Lock()


def _fingerprint(session: Session, last: dt.date) -> tuple[object, ...]:
    """What the block is computed from. A new or removed bar changes the row count of the whole
    window (answered from the date index); a corrected recent bar changes the fetch time and sums
    of the last 30 days; a re-adjustment changes the adjustment table."""
    since = last - timedelta(days=HISTORY_DAYS)
    recent = last - timedelta(days=30)
    n = session.scalar(
        select(func.count()).where(PriceDaily.date >= since, PriceDaily.date <= last)
    )
    bars = session.execute(
        select(
            func.max(PriceDaily.fetched_at),
            func.sum(PriceDaily.close),
            func.sum(PriceDaily.volume),
        ).where(PriceDaily.date >= recent, PriceDaily.date <= last)
    ).one()
    adj = session.execute(
        select(func.count(), func.sum(PriceAdjustment.adj_factor)).where(
            PriceAdjustment.date <= last
        )
    ).one()
    idx = session.execute(
        select(func.count(), func.max(MarketIndexDaily.date)).where(MarketIndexDaily.date <= last)
    ).one()
    return (last, n, *tuple(bars), *tuple(adj), *tuple(idx))


def _ema(x: np.ndarray[Any, Any], n: int) -> np.ndarray[Any, Any]:
    out = np.empty_like(x, dtype=float)
    a = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi(closes: np.ndarray[Any, Any], n: int = 14) -> float | None:
    """Wilder's RSI of the last bar; ``None`` below ``n + 1`` closes."""
    if len(closes) < n + 1:
        return None
    d = np.diff(closes)
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = gain[:n].mean(), loss[:n].mean()
    for g, ls in zip(gain[n:], loss[n:], strict=True):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + ls) / n
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def macd_hist(closes: np.ndarray[Any, Any]) -> float | None:
    if len(closes) < 35:
        return None
    line = _ema(closes, 12) - _ema(closes, 26)
    return float(line[-1] - _ema(line, 9)[-1])


def swing_levels(
    high: np.ndarray[Any, Any], low: np.ndarray[Any, Any], close: float, k: int = 3
) -> tuple[float | None, float | None]:
    """Nearest confirmed swing low under ``close`` and swing high over it. A swing point is the
    extreme of the ``k`` bars on each side, so the last ``k`` bars cannot be one yet."""
    n = len(low)
    supports: list[float] = []
    resistances: list[float] = []
    for i in range(k, n - k):
        if (
            low[i] < low[i - k : i].min()
            and low[i] <= low[i + 1 : i + k + 1].min()
            and low[i] < close
        ):
            supports.append(float(low[i]))
        if (
            high[i] > high[i - k : i].max()
            and high[i] >= high[i + 1 : i + k + 1].max()
            and high[i] > close
        ):
            resistances.append(float(high[i]))
    return (max(supports) if supports else None, min(resistances) if resistances else None)


def candle_pattern(
    o: np.ndarray[Any, Any],
    h: np.ndarray[Any, Any],
    lo: np.ndarray[Any, Any],
    c: np.ndarray[Any, Any],
) -> str | None:
    """Textbook pattern of the last bar (and the one before for engulfing); ``None`` when none."""
    if len(c) < 1:
        return None
    rng = h[-1] - lo[-1]
    if rng <= 0:  # a bar locked at one price says nothing
        return None
    body = abs(c[-1] - o[-1])
    lower, upper = min(o[-1], c[-1]) - lo[-1], h[-1] - max(o[-1], c[-1])
    if len(c) >= 2:
        po, pc = o[-2], c[-2]
        if pc < po and c[-1] > o[-1] and o[-1] <= pc and c[-1] >= po:
            return "بلعیدن صعودی"
        if pc > po and c[-1] < o[-1] and o[-1] >= pc and c[-1] <= po:
            return "بلعیدن نزولی"
    if body > 0 and lower >= 2 * body and upper <= body:
        return "چکش"
    if body > 0 and upper >= 2 * body and lower <= body:
        return "ستارهٔ دنباله‌دار"
    if body <= 0.1 * rng:
        return "دوجی"
    return None


def _betas(adj: pl.DataFrame, index: pl.DataFrame, last: dt.date) -> dict[int, Row]:
    """Slope of each stock's returns on the index's, over three window shapes."""
    specs = (
        ("beta_90d", None, 90, 60, 150),
        ("beta_60w", "1w", 60, 40, 430),
        ("beta_36m", "1mo", 36, 24, 1120),
    )
    out: dict[int, Row] = {}
    for name, every, n, min_obs, back in specs:
        since = last - timedelta(days=back)
        d = adj.filter(pl.col("date") >= since).select("instrument_id", "date", "adj_close")
        ix = index.filter(pl.col("date") >= since - timedelta(days=10)).select(
            "date", pl.col("close").alias("ix")
        )
        if every:
            d = (
                d.with_columns(p=pl.col("date").dt.truncate(every))
                .group_by(["instrument_id", "p"])
                .agg(pl.col("date").max().alias("date"), pl.col("adj_close").last())
            )
        else:
            d = d.with_columns(p=pl.col("date"))
        # the index level on each bar's own day (the last index day on or before it)
        d = d.sort("date").join_asof(ix.sort("date"), on="date", strategy="backward")
        j = (
            d.sort(["instrument_id", "p"])
            .with_columns(
                r=pl.col("adj_close") / pl.col("adj_close").shift(1).over("instrument_id") - 1,
                m=pl.col("ix") / pl.col("ix").shift(1).over("instrument_id") - 1,
            )
            .drop_nulls(["r", "m"])
            .filter((pl.col("r").abs() <= 1.0) & (pl.col("m").abs() <= 0.5))
            .group_by("instrument_id", maintain_order=True)
            .tail(n)
        )
        agg = j.group_by("instrument_id").agg(
            pl.len().alias("n"), pl.cov("r", "m").alias("cov"), pl.col("m").var().alias("var")
        )
        for iid, cnt, cov, var in agg.iter_rows():
            if cnt >= min_obs and var and var > 0 and cov is not None:
                out.setdefault(int(iid), {})[name] = float(cov / var)
    return out


def _rows(session: Session, last: dt.date) -> tuple[pl.DataFrame, pl.DataFrame]:
    since = last - timedelta(days=HISTORY_DAYS)
    # Core execution on the connection skips the ORM row machinery, which costs seconds here
    rows = (
        session.connection()
        .execute(
            select(
                PriceDaily.instrument_id,
                # text dates skip the per-row date parser, which is most of the load time
                cast(PriceDaily.date, String),
                PriceDaily.open,
                PriceDaily.high,
                PriceDaily.low,
                PriceDaily.close,
                PriceDaily.prev_close,
                PriceDaily.volume,
                PriceDaily.value,
                PriceDaily.limit_up,
                PriceDaily.limit_down,
            )
            .join(Instrument, Instrument.id == PriceDaily.instrument_id)
            .where(
                Instrument.instrument_type == InstrumentType.STOCK.value,
                PriceDaily.date >= since,
                PriceDaily.date <= last,
                PriceDaily.market_halt.is_(False),
            )
            .order_by(PriceDaily.instrument_id, PriceDaily.date)
        )
        .all()
    )
    names = (
        "instrument_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "volume",
        "value",
        "limit_up",
        "limit_down",
    )
    schema: dict[str, Any] = dict.fromkeys(names, pl.Float64)
    schema.update(instrument_id=pl.Int64, date=pl.String)
    cols = list(zip(*rows, strict=True)) if rows else [()] * len(names)
    raw = (
        pl.DataFrame(dict(zip(names, cols, strict=True)), schema=schema)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .filter(pl.col("close") > 0)
    )
    raw = raw.with_columns(
        pl.col("open").fill_null(pl.col("close")),
        pl.col("high").fill_null(pl.col("close")),
        pl.col("low").fill_null(pl.col("close")),
    )
    cfg = get_engine_config().benchmarks.indices.get("tedpix")
    ix_rows = (
        session.execute(
            select(MarketIndexDaily.date, MarketIndexDaily.close)
            .where(
                MarketIndexDaily.index_code == cfg,
                MarketIndexDaily.date <= last,
                MarketIndexDaily.date >= since,
            )
            .order_by(MarketIndexDaily.date)
        ).all()
        if cfg
        else []
    )
    index = pl.DataFrame(
        {"date": [r[0] for r in ix_rows], "close": [float(r[1]) for r in ix_rows]},
        schema={"date": pl.Date, "close": pl.Float64},
    )
    return raw, index


def _mean_before(a: np.ndarray[Any, Any], n: int, need: int) -> float | None:
    """Mean of the ``n`` positive values before the last one; ``None`` below ``need`` of them."""
    prev = a[:-1][-n:]
    prev = prev[prev > 0]
    return float(prev.mean()) if len(prev) >= need else None


def _mean_last(a: np.ndarray[Any, Any], n: int, need: int) -> float | None:
    tail = a[-n:]
    tail = tail[tail > 0]
    return float(tail.mean()) if len(tail) >= need else None


def _ratio(num: float | None, den: float | None) -> float | None:
    return None if num is None or den is None or den <= 0 else num / den


def _one(g: pl.DataFrame, last: dt.date, band: float) -> Row | None:
    dates = g["date"].to_numpy()
    if len(dates) == 0 or dates[-1] != np.datetime64(last):
        return None  # did not trade on the last day
    c, h, lo, o = (g[k].to_numpy() for k in ("adj_close", "adj_high", "adj_low", "adj_open"))
    vol, val = g["adj_volume"].to_numpy(), g["value"].fill_null(0.0).to_numpy()
    r: Row = {}
    for name, back in RETURN_DAYS.items():
        target = np.datetime64(last - timedelta(days=back))
        i = int(np.searchsorted(dates, target, side="right")) - 1
        if i >= 0 and (target - dates[i]) <= np.timedelta64(10, "D") and c[i] > 0:
            r[name] = float(c[-1] / c[i] - 1)
    for name, back in (("to_high_3m", 90), ("to_high_1y", 365)):
        start = np.datetime64(last - timedelta(days=back))
        if dates[0] <= start + np.timedelta64(10, "D"):  # a young symbol has no full range
            hi = h[dates >= start].max()
            r[name] = float(c[-1] / hi - 1) if hi > 0 else None
    r["vol_vs_30"] = _ratio(float(vol[-1]), _mean_before(vol, 30, 10))
    r["vol_vs_200"] = _ratio(float(vol[-1]), _mean_before(vol, 200, 100))
    r["value_vs_30"] = _ratio(float(val[-1]), _mean_before(val, 30, 10))
    r["value_vs_200"] = _ratio(float(val[-1]), _mean_before(val, 200, 100))
    r["avg_vol_90"] = _mean_last(vol, 90, 45)
    r["avg_vol_200"] = _mean_last(vol, 200, 100)
    # price limits: stored when the bar has them, else the band around the reference price
    raw_close, prev = float(g["close"][-1]), g["prev_close"][-1]
    up, dn = g["limit_up"][-1], g["limit_down"][-1]
    if prev and prev > 0:
        up = float(up) if up else prev * (1 + band)
        dn = float(dn) if dn else prev * (1 - band)
        r["dist_ceiling"] = raw_close / up - 1
        r["dist_floor"] = raw_close / dn - 1
    sup, res = swing_levels(h[-120:], lo[-120:], float(c[-1]))
    r["support"], r["resistance"] = sup, res
    r["support_dist"] = float(c[-1] / sup - 1) if sup else None
    r["resistance_dist"] = float(c[-1] / res - 1) if res else None
    r["pattern"] = candle_pattern(o[-2:], h[-2:], lo[-2:], c[-2:])
    # six sign tests; each needs its own history
    checks: list[bool] = [bool(c[-1] > c[-n:].mean()) for n in (20, 50, 200) if len(c) >= n]
    rs, mh = rsi(c[-150:]), macd_hist(c[-200:])
    if rs is not None:
        checks.append(rs > 50)
    if mh is not None:
        checks.append(mh > 0)
    if isinstance(r.get("ret_1m"), float):
        checks.append(float(r["ret_1m"]) > 0)  # type: ignore[arg-type]
    r["tech_score"] = 100.0 * sum(checks) / len(checks) if len(checks) >= 4 else None
    day = raw_close / prev - 1 if prev and prev > 0 else None
    r["_close"], r["_prev"] = raw_close, float(prev) if prev else None
    r["_day"] = day if day is not None and abs(day) <= MAX_DAY_MOVE else None
    r["_volume"], r["_value"] = float(g["volume"][-1] or 0.0), float(val[-1])
    r["_value_avg30"] = _mean_last(val, 30, 10)
    r["_first_date"] = str(dates[0])
    return r


def price_block(session: Session, last: dt.date, band: float = DEFAULT_BAND) -> dict[int, Row]:
    """Per-stock columns that come from bars alone. Kept while the bars are unchanged."""
    key = (*_fingerprint(session, last), band)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    with _compute_lock:  # one request builds it; the others wait and then find it cached
        with _lock:
            hit = _cache.get(key)
        if hit is not None:
            return hit
        out = _build_price_block(session, last, band)
        with _lock:
            _cache.clear()  # only the latest state is ever asked for
            _cache[key] = out
    return out


def _build_price_block(session: Session, last: dt.date, band: float) -> dict[int, Row]:
    raw, index = _rows(session, last)
    out: dict[int, Row] = {}
    if not raw.is_empty():
        adj = apply_adjustments(raw)
        betas = _betas(adj, index, last) if not index.is_empty() else {}
        for k, g in adj.partition_by("instrument_id", as_dict=True, maintain_order=True).items():
            iid = int(k[0] if isinstance(k, tuple) else k)
            row = _one(g, last, band)
            if row is not None:
                row.update(betas.get(iid, {}))
                out[iid] = row
    return out


# ---------------------------------------------------------------- other blocks


def flow_block(session: Session, flow_date: dt.date | None) -> dict[int, Row]:
    if flow_date is None:
        return {}
    rows = session.execute(
        select(
            ClientTypeDaily.instrument_id,
            ClientTypeDaily.date,
            ClientTypeDaily.buy_value_i,
            ClientTypeDaily.sell_value_i,
            ClientTypeDaily.buy_value_n,
            ClientTypeDaily.sell_value_n,
            ClientTypeDaily.buy_count_i,
            ClientTypeDaily.sell_count_i,
            ClientTypeDaily.buy_count_n,
            ClientTypeDaily.sell_count_n,
        )
        .where(
            ClientTypeDaily.date <= flow_date,
            ClientTypeDaily.date >= flow_date - timedelta(days=45),
        )
        .order_by(ClientTypeDaily.instrument_id, ClientTypeDaily.date.desc())
    ).all()
    per: dict[int, list[Any]] = {}
    for r in rows:
        per.setdefault(int(r[0]), []).append(
            (r[0], r[1], *(None if v is None else float(v) for v in r[2:]))
        )
    out: dict[int, Row] = {}
    for iid, rs in per.items():
        if rs[0][1] != flow_date:
            continue
        _, _, bi, si, bn, sn, ci_b, ci_s, cn_b, cn_s = rs[0]
        tot = (bi or 0.0) + (bn or 0.0)
        row: Row = {}
        if tot > 0 and bi is not None and si is not None:
            row["real_net_pct"] = float(bi - si) / tot
        if tot > 0 and bn is not None and sn is not None:
            row["legal_net_pct"] = float(bn - sn) / tot
        row["real_buy_power"] = _ratio(_ratio(bi, ci_b), _ratio(si, ci_s))
        row["legal_buy_power"] = _ratio(_ratio(bn, cn_b), _ratio(sn, cn_s))
        row["_real_net"] = float(bi - si) if bi is not None and si is not None else None
        for name, n, need in (("real_net_5d_pct", 5, 3), ("real_net_20d_pct", 20, 12)):
            part = [x for x in rs[:n] if x[2] is not None and x[3] is not None and x[4] is not None]
            if len(part) >= need:
                den = sum((x[2] or 0.0) + (x[4] or 0.0) for x in part)
                row[name] = sum(x[2] - x[3] for x in part) / den if den > 0 else None
        out[iid] = row
    return out


def book_block(
    session: Session, last: dt.date, closes: dict[int, float]
) -> tuple[dict[int, Row], dt.date | None]:
    day = session.scalar(select(func.max(OrderBookDaily.date)).where(OrderBookDaily.date <= last))
    if day is None:
        return {}, None
    out: dict[int, Row] = {}
    for b in session.scalars(select(OrderBookDaily).where(OrderBookDaily.date == day)):
        bid = (
            None
            if b.close_bid_price is None or b.close_bid_volume is None
            else b.close_bid_price * b.close_bid_volume
        )
        ask = (
            None
            if b.close_ask_price is None or b.close_ask_volume is None
            else b.close_ask_price * b.close_ask_volume
        )
        row: Row = {
            "buy_order_value": bid,
            "sell_order_value": ask,
            "net_order_value": None if bid is None or ask is None else bid - ask,
            "demand_pressure": b.close_imbalance,
        }
        if bid and not (b.close_ask_volume or 0):
            row["queue_value"] = bid
        elif ask and not (b.close_bid_volume or 0):
            row["queue_value"] = -ask
        else:
            row["queue_value"] = 0.0
        px = closes.get(b.instrument_id)
        row["peak_queue_value"] = (
            b.peak_queue_volume * px if b.peak_queue_volume is not None and px else None
        )
        out[b.instrument_id] = row
    return out, day


def usd_rate(session: Session, last: dt.date) -> float | None:
    v = session.scalar(
        select(MacroSeries.value)
        .where(MacroSeries.series == USD_SERIES, MacroSeries.ref_period <= last)
        .order_by(MacroSeries.ref_period.desc())
        .limit(1)
    )
    return None if v is None or v <= 0 else float(v)


def _num(v: Any) -> float | None:
    return None if v is None or isinstance(v, bool | str) else float(v)


@dataclass
class Table:
    as_of: dt.date
    rows: dict[int, Row]
    flow_date: dt.date | None
    book_date: dt.date | None
    usd: float | None
    sectors: dict[int, str]


def _band(session: Session, last: dt.date) -> float:
    from tmon.domain.rules import MissingRuleError, RuleBook

    try:
        pct = RuleBook.from_session(session).value("price_limit", last).get("pct")
    except MissingRuleError:
        return DEFAULT_BAND
    return float(pct) if pct else DEFAULT_BAND


def compute(session: Session, last: dt.date, flow_date: dt.date | None) -> Table:
    """Every derived column of every stock that traded on ``last``."""
    prices = price_block(session, last, _band(session, last))
    flows = flow_block(session, flow_date)
    closes = {i: c for i, p in prices.items() if (c := _num(p.get("_close")))}
    books, book_day = book_block(session, last, closes)
    usd = usd_rate(session, last)
    inst = {
        i: (sec, tags or {})
        for i, sec, tags in session.execute(
            select(Instrument.id, Instrument.sector_code, Instrument.tags).where(
                Instrument.id.in_(list(prices))
            )
        )
    }
    holders = {
        int(i): float(p or 0.0)
        for i, p in session.execute(
            select(Shareholder.instrument_id, func.sum(Shareholder.percent)).group_by(
                Shareholder.instrument_id
            )
        )
    }
    statements = fundamentals.load_statements(session)

    mcap: dict[int, float] = {}
    for iid, p in prices.items():
        shares = _num(inst[iid][1].get("shares"))
        close = _num(p.get("_close"))
        if shares and close:
            mcap[iid] = shares * close
    total_mcap = sum(mcap.values())
    sec_value: dict[str, float] = {}
    sec_mcap: dict[str, float] = {}
    for iid, p in prices.items():
        sec = (inst[iid][0] or "").strip()
        sec_value[sec] = sec_value.get(sec, 0.0) + (_num(p.get("_value")) or 0.0)
        sec_mcap[sec] = sec_mcap.get(sec, 0.0) + mcap.get(iid, 0.0)

    rows: dict[int, Row] = {}
    for iid, p in prices.items():
        row: Row = {k: v for k, v in p.items() if not k.startswith("_") or k == "_first_date"}
        row.update({k: v for k, v in flows.get(iid, {}).items() if not k.startswith("_")})
        row.update(books.get(iid, {}))
        sec = (inst[iid][0] or "").strip()
        shares = _num(inst[iid][1].get("shares"))
        close, value = _num(p.get("_close")), _num(p.get("_value"))
        mc = mcap.get(iid)
        row["shares"], row["mcap"] = shares, mc
        if iid in holders and shares:
            fp = max(0.0, 100.0 - holders[iid]) / 100.0
            fs = shares * fp
            row["float_pct"], row["float_shares"] = fp, fs
            row["float_value"] = fs * close if close else None
            row["vol_to_float"] = _ratio(_num(p.get("_volume")), fs)
        row["value_to_mcap"] = _ratio(value, mc)
        weight = mc / total_mcap if mc and total_mcap else None
        row["index_weight"] = weight
        day = _num(p.get("_day"))
        row["index_impact"] = weight * day if weight and day is not None else None
        row["industry_value_share"] = _ratio(value, sec_value.get(sec))
        row["industry_mcap_share"] = _ratio(mc, sec_mcap.get(sec))
        real_net = _num(flows.get(iid, {}).get("_real_net"))
        avg30 = _num(p.get("_value_avg30"))
        if real_net is not None and avg30 and avg30 > 0:
            row["real_net_vs_avg"] = real_net / avg30
        if usd:
            row["price_usd"] = close / usd if close else None
            row["mcap_usd"] = mc / usd if mc else None
        row.update(fundamentals.ratios(statements.get(iid, []), mc))
        rows[iid] = row
    sectors = {i: (inst[i][0] or "").strip() for i in rows}
    return Table(last, rows, flow_date if flows else None, book_day, usd, sectors)


# ---------------------------------------------------------------- one symbol and aggregates


def listing(session: Session, instrument_id: int) -> Row:
    """First stored trading day and the reference price of that day (cheap: one symbol)."""
    first = session.execute(
        select(PriceDaily.date, PriceDaily.prev_close, PriceDaily.open)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date)
        .limit(1)
    ).first()
    if first is None:
        return {}
    px = first[1] or first[2]
    return {"first_day": first[0].isoformat(), "ipo_price": float(px) if px else None}


def medians(rows: list[Row], keys: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in keys:
        xs = [x for r in rows if (x := _num(r.get(k))) is not None]
        out[k] = statistics.median(xs) if xs else None
    return out


def market_summary(session: Session, table: Table) -> dict[str, Value]:
    """Market value in rial and dollars, and the index in both, for the market page."""
    total = sum(m for r in table.rows.values() if (m := _num(r.get("mcap"))) is not None)
    cfg = get_engine_config().benchmarks.indices.get("tedpix")
    out: dict[str, Value] = {"mcap": total or None, "usd": table.usd}
    if table.usd and total:
        out["mcap_usd"] = total / table.usd
    if not cfg or not table.usd:
        return out
    year_ago = table.as_of - timedelta(days=365)

    def level(day: dt.date) -> float | None:
        v = session.scalar(
            select(MarketIndexDaily.close)
            .where(MarketIndexDaily.index_code == cfg, MarketIndexDaily.date <= day)
            .order_by(MarketIndexDaily.date.desc())
            .limit(1)
        )
        return None if v is None else float(v)

    def rate(day: dt.date) -> float | None:
        v = session.scalar(
            select(MacroSeries.value)
            .where(MacroSeries.series == USD_SERIES, MacroSeries.ref_period <= day)
            .order_by(MacroSeries.ref_period.desc())
            .limit(1)
        )
        return None if v is None or v <= 0 else float(v)

    now_ix, then_ix, then_fx = level(table.as_of), level(year_ago), rate(year_ago)
    if now_ix:
        out["index_usd"] = now_ix / table.usd
    if now_ix and then_ix and then_fx:
        out["index_year_rial"] = now_ix / then_ix - 1
        out["index_year_usd"] = (now_ix / table.usd) / (then_ix / then_fx) - 1
    return out
