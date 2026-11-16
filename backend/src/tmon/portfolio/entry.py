"""Entry and exit timing: what the model's score cannot say.

The score ranks stocks by what they did *after a close*, so every measured gain starts from the
previous official close (پایانی). A buyer never gets that price: the order fills at the day's own
price, which after a gap is already above it. Whatever the gap took is gone from the gain the
score promised. On top of that, the stock may close green on the official price (a volume-weighted
average) while the last trade, the price a seller gets, is lower.

This module turns that into three things:

* :func:`review_entry`  grades one purchase against the day's range, the gap, the last trade and
                        the edge the score promised ("did we overpay, and was it a bad time").
* :func:`guard`         the same questions asked *before* buying, from today's live range.
* :func:`fade_table` / :func:`fit_open_model`  the evidence behind both, measured on the stored
                        history and refitted whenever new days arrive (no fixed weights).

Everything is in rial. Nothing here is cached by time; the history tables are re-read only when
their data fingerprint changes.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.portfolio.liveprice import Bar
from tmon.storage.models import PriceDaily

GAP_EDGES = (-1.0, -0.01, 0.005, 0.015, 0.025, 1.0)
GAP_LABELS = (
    "بازگشایی بیش از ۱٪ پایین‌تر",
    "نزدیک قیمت دیروز",
    "۰٫۵ تا ۱٫۵٪ بالاتر",
    "۱٫۵ تا ۲٫۵٪ بالاتر",
    "بیش از ۲٫۵٪ بالاتر (نزدیک سقف مجاز)",
)
WINDOW_DAYS = 260
MIN_DAYS_FOR_STATS = 40
FM_HALF_LIFE = 60.0  # days: older daily fits count half as much every 60 days
MIN_T = 1.5  # a feature below this has no evidence and gets weight 0
RIDGE = 1.0
FEATURES: dict[str, str] = {
    "gap": "فاصلهٔ قیمت بازگشایی تا پایانی دیروز",
    "pos_prev": "جای پایانی دیروز در بازهٔ دیروز",
    "ret_prev": "بازده دیروز",
    "ret5": "بازده ۵ روز گذشته",
}


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}٪".replace(".", "٫")


# ---------------------------------------------------------------------------------------------
# evidence from the stored history


@dataclass(frozen=True)
class Panel:
    """Daily bars of the liquid stocks as aligned arrays (one row per symbol-day)."""

    day: np.ndarray
    iid: np.ndarray
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    last: np.ndarray
    c: np.ndarray
    pc: np.ndarray
    v: np.ndarray
    nxt_open: np.ndarray  # next trading day's open of the same symbol (nan when none)
    adj_ok: np.ndarray  # the next day's reference price is this day's close: no adjustment
    pc5: np.ndarray  # reference close five trading days earlier
    pc1: np.ndarray  # reference close one trading day earlier
    prev_h: np.ndarray
    prev_lo: np.ndarray
    prev_c: np.ndarray


_memo: dict[tuple[object, ...], Panel | None] = {}


def _fingerprint(session: Session) -> tuple[object, ...]:
    return (
        session.scalar(select(func.max(PriceDaily.date))),
        session.scalar(select(func.count()).select_from(PriceDaily)),
    )


def panel(session: Session) -> Panel | None:
    """The last :data:`WINDOW_DAYS` market days of the most traded symbols, or None when there
    is too little history. Re-read only when the price table changes."""
    stamp = _fingerprint(session)
    if stamp in _memo:
        return _memo[stamp]
    last_day = stamp[0]
    if not isinstance(last_day, dt.date):
        return None
    days = list(
        session.scalars(
            select(PriceDaily.date)
            .distinct()
            .where(PriceDaily.date <= last_day)
            .order_by(PriceDaily.date.desc())
            .limit(WINDOW_DAYS + 25)
        )
    )
    if len(days) < MIN_DAYS_FOR_STATS + 25:
        _memo.clear()
        _memo[stamp] = None
        return None
    first_day = min(days)
    liquid = [
        int(i)
        for (i,) in session.execute(
            select(PriceDaily.instrument_id)
            .where(PriceDaily.date >= first_day, PriceDaily.value > 0)
            .group_by(PriceDaily.instrument_id)
            .order_by(func.avg(PriceDaily.value).desc())
            .limit(300)
        )
    ]
    rows = session.execute(
        select(
            PriceDaily.instrument_id,
            PriceDaily.date,
            PriceDaily.open,
            PriceDaily.high,
            PriceDaily.low,
            PriceDaily.last,
            PriceDaily.close,
            PriceDaily.prev_close,
            PriceDaily.volume,
        )
        .where(
            PriceDaily.instrument_id.in_(liquid),
            PriceDaily.date >= first_day,
            PriceDaily.open > 0,
            PriceDaily.high > 0,
            PriceDaily.low > 0,
            PriceDaily.last > 0,
            PriceDaily.close > 0,
            PriceDaily.prev_close > 0,
            PriceDaily.volume > 0,
        )
        .order_by(PriceDaily.instrument_id, PriceDaily.date)
    ).all()
    cols: dict[str, list[float]] = {k: [] for k in Panel.__dataclass_fields__}
    by: dict[int, list[Any]] = {}
    for r in rows:
        by.setdefault(int(r[0]), []).append(r)
    for iid, rs in by.items():
        for k, r in enumerate(rs):
            if k < 6:
                continue  # need five earlier days for the 5-day return
            nxt = rs[k + 1] if k + 1 < len(rs) else None
            ref_next = float(nxt[7]) if nxt is not None else float("nan")
            close, last = float(r[6]), float(r[5])
            ok = nxt is not None and (abs(ref_next - close) < 1.0 or abs(ref_next - last) < 1.0)
            cols["day"].append(r[1].toordinal())
            cols["iid"].append(iid)
            cols["o"].append(float(r[2]))
            cols["h"].append(float(r[3]))
            cols["lo"].append(float(r[4]))
            cols["last"].append(last)
            cols["c"].append(close)
            cols["pc"].append(float(r[7]))
            cols["v"].append(float(r[8]))
            cols["nxt_open"].append(float(nxt[2]) if nxt is not None else float("nan"))
            cols["adj_ok"].append(1.0 if ok else 0.0)
            cols["pc5"].append(float(rs[k - 5][7]))
            cols["pc1"].append(float(rs[k - 1][7]))
            cols["prev_h"].append(float(rs[k - 1][3]))
            cols["prev_lo"].append(float(rs[k - 1][4]))
            cols["prev_c"].append(float(rs[k - 1][6]))
    out = Panel(**{k: np.asarray(v, dtype=float) for k, v in cols.items()})
    _memo.clear()
    _memo[stamp] = out if len(out.day) else None
    return _memo[stamp]


def fade_table(session: Session) -> dict[str, Any] | None:
    """How a day that *opens* a given distance above yesterday's close went afterwards, over the
    stored history of the liquid symbols: the open-to-last move, the share of such days that end
    below the open, and how often the open was already within half a percent of the day's high."""
    p = panel(session)
    if p is None:
        return None
    gap = p.o / p.pc - 1
    keep = (np.abs(gap) < 0.055) & (p.adj_ok > 0)
    rows: list[dict[str, Any]] = []
    for i in range(len(GAP_LABELS)):
        lo, hi = GAP_EDGES[i], GAP_EDGES[i + 1]
        m = keep & (gap > lo) & (gap <= hi)
        n = int(m.sum())
        if n < 50:
            continue
        ol = p.last[m] / p.o[m] - 1
        nxt = p.nxt_open[m] / p.o[m] - 1
        nxt = nxt[np.isfinite(nxt)]
        rows.append(
            {
                "label": GAP_LABELS[i],
                "low": lo,
                "high": hi,
                "n": n,
                "open_to_last": float(ol.mean()),
                "share_below_open": float((ol < 0).mean()),
                "open_to_next_open": float(nxt.mean()) if len(nxt) else None,
                "share_open_near_high": float(((p.h[m] / p.o[m] - 1) < 0.005).mean()),
            }
        )
    days = len(np.unique(p.day))
    return {"days": days, "rows": rows}


def bucket_for(table: dict[str, Any] | None, gap: float | None) -> dict[str, Any] | None:
    if not table or gap is None:
        return None
    for r in table["rows"]:
        if r["low"] < gap <= r["high"]:
            return dict(r)
    return None


def fit_open_model(session: Session) -> dict[str, Any] | None:
    """Weights of what is known at the open, fitted afresh on the stored history.

    Every market day gives one cross-sectional ridge fit of the same-day open-to-last move on the
    standardised features (Fama-MacBeth). The weight of a feature is the exponentially weighted
    mean of its daily coefficients (half life :data:`FM_HALF_LIFE` days, so recent days count
    more) and is zeroed when its t-statistic is below :data:`MIN_T`. Re-run whenever new days
    arrive; nothing is fixed by hand."""
    p = panel(session)
    if p is None:
        return None
    gap = p.o / p.pc - 1
    rng = p.prev_h - p.prev_lo
    feats = {
        "gap": gap,
        "pos_prev": np.where(rng > 0, (p.prev_c - p.prev_lo) / np.where(rng > 0, rng, 1), 0.5),
        "ret_prev": p.pc / p.pc1 - 1,
        "ret5": p.pc / p.pc5 - 1,
    }
    y = p.last / p.o - 1
    ok = (np.abs(gap) < 0.055) & (p.adj_ok > 0) & np.isfinite(y)
    keys = list(feats)
    days = np.unique(p.day[ok])
    betas: list[np.ndarray] = []
    used: list[float] = []
    for d in days:
        m = ok & (p.day == d)
        if m.sum() < 30:
            continue
        mat = np.column_stack([feats[k][m] for k in keys])
        sd = mat.std(axis=0)
        if (sd == 0).any():
            continue
        z = (mat - mat.mean(axis=0)) / sd
        t = y[m] - y[m].mean()
        beta = np.linalg.solve(z.T @ z + RIDGE * np.eye(len(keys)), z.T @ t)
        betas.append(beta)
        used.append(float(d))
    if len(betas) < MIN_DAYS_FOR_STATS:
        return None
    bm = np.vstack(betas)
    age = max(used) - np.asarray(used)
    w = 0.5 ** (age / FM_HALF_LIFE)
    w /= w.sum()
    mean = (bm * w[:, None]).sum(axis=0)
    se = bm.std(axis=0, ddof=1) / np.sqrt(len(bm))
    tstat = np.where(se > 0, bm.mean(axis=0) / np.where(se > 0, se, 1), 0.0)
    fitted: list[dict[str, Any]] = []
    for i, k in enumerate(keys):
        use = abs(float(tstat[i])) >= MIN_T
        fitted.append(
            {
                "key": k,
                "label": FEATURES[k],
                "beta": float(mean[i]),
                "t": float(tstat[i]),
                "weight": float(mean[i]) if use else 0.0,
                "mean": float(feats[k][ok].mean()),
                "sd": float(feats[k][ok].std()),
            }
        )
    return {
        "days": len(bm),
        "as_of": dt.date.fromordinal(int(max(used))).isoformat(),
        "features": fitted,
    }


def drift_from_model(model: dict[str, Any] | None, x: dict[str, float | None]) -> float | None:
    """Expected open-to-last move relative to the day's average, from the fitted weights."""
    if not model:
        return None
    total = 0.0
    seen = False
    for f in model["features"]:
        v = x.get(f["key"])
        if v is None or f["sd"] <= 0 or f["weight"] == 0:
            continue
        total += f["weight"] * (v - f["mean"]) / f["sd"]
        seen = True
    return total if seen else None


# ---------------------------------------------------------------------------------------------
# the review of one purchase and the guard before one


def review_entry(
    paid: float,
    bar: Bar,
    *,
    edge: float | None = None,
    cost: float = 0.0175,
    fade: dict[str, Any] | None = None,
    queue: str | None = None,
) -> dict[str, Any]:
    """Grade one purchase against the day it was made.

    ``edge`` is the past excess return of the buy zone at the holding period the verdict uses
    (before cost); ``fade`` the :func:`fade_table` row for the day's gap. Returns the measures,
    the flags that explain a loss and one plain sentence per flag."""
    ref = bar.yesterday
    last, close = bar.last, bar.close
    premium = paid / ref - 1 if ref else None
    pos = bar.range_pos(paid)
    vs_close = paid / close - 1 if close else None
    now = last / paid - 1 if last else None
    now_close = close / paid - 1 if close else None
    flags: list[dict[str, str]] = []

    def flag(key: str, text: str) -> None:
        flags.append({"key": key, "text": text})

    gap = bar.gap
    at_limit = bool(bar.limit_up and paid >= bar.limit_up * 0.997)
    if at_limit:
        flag(
            "limit_price",
            "با قیمت سقف مجاز خریده‌اید؛ بالاتر از آن چیزی نیست و سود باقیمانده تقریباً "
            "صفر است (و سفارش در صف خرید ممکن است اصلاً اجرا نشود).",
        )
    if premium is not None and premium >= 0.015 and not at_limit:
        flag(
            "gap_chase",
            f"قیمت خرید {_pct(premium)} بالاتر از پایانی دیروز بود؛ امتیاز مدل از پایانی دیروز "
            "حساب شده، نه از قیمتی که واقعاً پرداخت کرده‌اید.",
        )
    if edge is not None and premium is not None:
        left = edge - cost - max(0.0, premium)
        if left <= 0 < edge - cost:
            flag(
                "edge_gone",
                f"برتری گذشتهٔ این گروه پس از کارمزد {_pct(edge - cost)} بود و "
                f"{_pct(max(0.0, premium))} آن را همان لحظهٔ خرید بالاتر پرداخته‌اید؛ "
                "چیزی از مزیت نمانده بود.",
            )
    if pos is not None and pos >= 0.8 and (gap or 0) > 0.01:
        flag(
            "top_of_range",
            f"خرید در {_pct(pos, 0)} بالای بازهٔ همان روز بود، بعد از بازگشایی با شکاف مثبت؛ "
            "معمولاً آن قیمت همان قله‌ای است که بعدش پایین می‌آید.",
        )
    if vs_close is not None and vs_close >= 0.01:
        flag(
            "above_close",
            f"از قیمت پایانی همان روز {_pct(vs_close)} گران‌تر خریده‌اید.",
        )
    if close and ref and last and close > ref and last < paid:
        flag(
            "green_but_loss",
            "کندل سبز بود (پایانی بالاتر از دیروز) ولی پایانی میانگین وزنیِ معاملات است؛ آخرین "
            f"معامله ({last:,.0f}) که قیمتِ فروش شماست پایین‌تر از خرید شماست.",
        )
    if fade and fade.get("open_to_last") is not None and fade["open_to_last"] < -0.003:
        flag(
            "history_fade",
            f"در {fade['n']:,} روز گذشته با شکافی مثل این روز ({fade['label']}) میانگین حرکت "
            f"از قیمت بازگشایی تا آخرین معامله {_pct(fade['open_to_last'])} بود و "
            f"{_pct(fade['share_below_open'], 0)} آن روزها پایین‌تر از قیمت بازگشایی تمام شد.",
        )
    if queue == "buy_queue" and not at_limit and premium is not None and premium > 0.02:
        flag("queue", "سهم صف خرید بود؛ قیمت‌های بالاتر از صف معمولاً فقط ورود زودهنگام‌اند.")

    score = 100.0
    weights = {
        "limit_price": 30,
        "gap_chase": 25,
        "edge_gone": 20,
        "top_of_range": 20,
        "above_close": 10,
        "green_but_loss": 10,
        "history_fade": 10,
        "queue": 5,
    }
    for f in flags:
        score -= weights.get(f["key"], 5)
    score = max(0.0, score)
    grade = "good" if score >= 75 else "fair" if score >= 45 else "poor"
    return {
        "paid": paid,
        "yesterday": ref,
        "first": bar.first,
        "high": bar.high,
        "low": bar.low,
        "last": last,
        "close": close,
        "gap": gap,
        "premium": premium,
        "range_pos": pos,
        "vs_close": vs_close,
        "pnl_last": now,
        "pnl_close": now_close,
        "flags": flags,
        "score": score,
        "grade": grade,
    }


def guard(
    bar: Bar,
    *,
    edge: float | None,
    cost: float,
    fade: dict[str, Any] | None,
    drift: float | None = None,
    queue: str | None = None,
    book_imbalance: float | None = None,
    now_minutes: int | None = None,
    breadth: float | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """Is *now* a sensible moment and price to buy? ``edge`` is the past excess return of the buy
    zone before cost; the answer subtracts what today's price already took of it.

    ``now_minutes`` is minutes since 09:00 Tehran time (None outside the session). The live
    pieces (order-book imbalance, market breadth) shift the answer by priors that are *not* yet
    measured on stored intraday history, and say so."""
    price = bar.last
    ref = bar.yesterday
    reasons: list[str] = []
    state = "ok"
    if not price or not ref:
        return {"state": "unknown", "headline": "قیمت زندهٔ امروز در دسترس نیست.", "reasons": []}
    premium = price / ref - 1
    pos = bar.range_pos(price)
    net = None if edge is None else edge - cost
    left = None if net is None else net - max(0.0, premium)
    max_price = None if net is None or net <= 0 else ref * (1 + net)
    worse = {"ok": 0, "wait": 1, "avoid": 2}

    def bump(to: str, text: str) -> None:
        nonlocal state
        if worse[to] > worse[state]:
            state = to
        reasons.append(text)

    if verdict == "sell":
        bump("avoid", "حکم مدل برای این سهم فروش است؛ خرید تازه دلیلی ندارد.")
    elif verdict == "hold":
        bump(
            "wait",
            "مدل برای این سهم خرید نمی‌گوید (حکم: نگهداری)؛ تا وقتی به محدودهٔ خرید نرسیده صبر کنید.",
        )
    if left is not None:
        if net is not None and net <= 0:
            bump("avoid", "پس از کارمزد، برتری گذشتهٔ این گروه صفر یا منفی است؛ ورود توجیه ندارد.")
        elif left <= 0:
            bump(
                "avoid",
                f"قیمت فعلی {_pct(max(0.0, premium))} از پایانی دیروز بالاتر است و برتری پس از "
                f"کارمزد ({_pct(net or 0)}) را کامل خورده است.",
            )
        elif left < (net or 0) * 0.5:
            bump(
                "wait",
                f"از برتری پس از کارمزد ({_pct(net or 0)}) فقط {_pct(left)} مانده است؛ منتظر قیمت "
                "پایین‌تر بمانید.",
            )
    if pos is not None and pos >= 0.8 and premium > 0.01:
        bump("wait", f"قیمت در {_pct(pos, 0)} بالای بازهٔ امروز است؛ خرید در قله بعد از شکاف.")
    if fade and fade.get("open_to_last") is not None and fade["open_to_last"] < -0.003:
        bump(
            "wait",
            f"روزهایی که با شکافی مثل امروز ({fade['label']}) باز شده‌اند، تا آخرین معامله به‌طور "
            f"میانگین {_pct(fade['open_to_last'])} بازده داشته‌اند ({fade['n']:,} روز).",
        )
    if drift is not None and drift < -0.002:
        bump(
            "wait",
            f"مدل بازآموزی‌شده برای امروز {_pct(drift)} حرکت نسبی تا آخر روز را برآورد می‌کند.",
        )
    if bar.limit_up and price >= bar.limit_up * 0.997:
        bump("avoid", "قیمت روی سقف مجاز است؛ خرید در این قیمت سود باقیمانده ندارد و در صف می‌ماند.")
    if queue == "sell_queue":
        bump("avoid", "سهم صف فروش است.")
    if queue == "buy_queue":
        bump("wait", "سهم صف خرید است؛ خرید عملاً ممکن نیست و ورود با سفارش درشت خطرناک است.")
    if book_imbalance is not None:
        if book_imbalance < -0.3:
            bump(
                "wait",
                "حجم عرضه در پنج ردیف تابلو از تقاضا بیشتر است (برآورد اولیه؛ هنوز روی دادهٔ "
                "تابلوی ذخیره‌شده آزموده نشده).",
            )
        elif book_imbalance > 0.5:
            reasons.append("تابلو به سمت خریدار است؛ این به‌تنهایی دلیل خرید نیست.")
    if breadth is not None and breadth > 0.8 and premium > 0.01:
        bump(
            "wait",
            "بیش از ۸۰٪ نمادها امروز بالا باز شده‌اند؛ در چنین روزی شکاف بازار معمولاً پس می‌رود.",
        )
    if now_minutes is not None and now_minutes < 0:
        bump(
            "wait",
            "بازار در پیش‌گشایش است؛ قیمت نمایش‌داده‌شده فقط تعادل تقریبی مزایده است و تا "
            "بازگشایی ممکن است جابه‌جا شود.",
        )
    elif now_minutes is not None and now_minutes < 20:
        bump(
            "wait",
            "هنوز در ۲۰ دقیقهٔ اول بازگشایی هستیم؛ قیمت کشف نشده و به این بازه نمی‌شود تکیه کرد.",
        )
    if state == "ok" and not reasons:
        reasons.append("شکاف کوچک است، قیمت بالای بازهٔ امروز نیست و برتری مدل هنوز باقی است.")
    head = {
        "ok": "ورود از نظر قیمت و زمان قابل قبول است",
        "wait": "صبر کنید؛ قیمت یا زمان مناسب نیست",
        "avoid": "در این قیمت وارد نشوید",
    }[state]
    return {
        "state": state,
        "headline": head,
        "reasons": reasons,
        "price": price,
        "premium": premium,
        "range_pos": pos,
        "edge": edge,
        "net_edge": net,
        "edge_left": left,
        "max_price": max_price,
        "gap": bar.gap,
        "fade": fade,
        "drift": drift,
    }


# ---------------------------------------------------------------------------------------------
# glue: stored days, the ranking document, a portfolio's purchases

HOLD_DAYS = 20  # the horizon the ranking's evidence is read at (trading days)


def edge_and_cost(doc: dict[str, Any] | None) -> tuple[float | None, float]:
    """Past excess return of the buy zone over :data:`HOLD_DAYS` trading days (before cost) and
    the round-trip cost, from the ranking document."""
    cost = float((doc or {}).get("round_trip_cost") or 0.0175)
    for e in (doc or {}).get("evidence") or []:
        if e.get("horizon_days") == HOLD_DAYS and e.get("top_excess") is not None:
            return float(e["top_excess"]), cost
    return None, cost


def bar_from_row(p: PriceDaily) -> Bar | None:
    """A stored day as a :class:`Bar`; None when it has no usable range."""
    if not (p.open and p.high and p.low and p.prev_close):
        return None
    last = float(p.last) if p.last else (float(p.close) if p.close else None)
    return Bar(
        day=p.date,
        first=float(p.open),
        high=float(p.high),
        low=float(p.low),
        last=last,
        close=float(p.close) if p.close else None,
        yesterday=float(p.prev_close),
        limit_up=float(p.limit_up) if p.limit_up else None,
        limit_down=float(p.limit_down) if p.limit_down else None,
        volume=float(p.volume) if p.volume else None,
    )


def open_features(session: Session, instrument_id: int, bar: Bar) -> dict[str, float | None]:
    """What is known at the open for :func:`drift_from_model`, from the days before ``bar``."""
    rows = list(
        session.scalars(
            select(PriceDaily)
            .where(
                PriceDaily.instrument_id == instrument_id,
                PriceDaily.date < (bar.day or dt.date.max),
                PriceDaily.close > 0,
            )
            .order_by(PriceDaily.date.desc())
            .limit(6)
        )
    )
    x: dict[str, float | None] = {"gap": bar.gap, "pos_prev": None, "ret_prev": None, "ret5": None}
    if not rows:
        return x
    y = rows[0]
    # Postgres hands back Decimal; every number is made a float before any arithmetic.
    if y.high and y.low and y.high > y.low and y.close:
        hi, lo = float(y.high), float(y.low)
        x["pos_prev"] = (float(y.close) - lo) / (hi - lo)
    if y.prev_close and bar.yesterday:
        x["ret_prev"] = float(bar.yesterday) / float(y.prev_close) - 1
    if len(rows) >= 5 and rows[4].prev_close and bar.yesterday:
        x["ret5"] = float(bar.yesterday) / float(rows[4].prev_close) - 1
    return x


def lessons(reviews: list[dict[str, Any]]) -> list[str]:
    """What the purchases have in common, in plain sentences. Empty when there is nothing to
    learn yet. Each sentence names the count it rests on."""
    rows = [r for r in reviews if r.get("premium") is not None]
    if not rows:
        return []
    out: list[str] = []
    n = len(rows)
    chase = [r for r in rows if r["premium"] >= 0.015]
    if chase:
        avg = sum(r["premium"] for r in chase) / len(chase)
        out.append(
            f"{len(chase)} از {n} خرید بالاتر از ۱٫۵٪ بالای پایانی دیروز انجام شد (میانگین "
            f"{_pct(avg)}). پیش‌بینی مدل از پایانی دیروز شروع می‌شود؛ هرچه بالاتر بخرید همان مقدار "
            "از سود پیش‌بینی‌شده را از قبل داده‌اید."
        )
    top = [r for r in rows if (r.get("range_pos") or 0) >= 0.8]
    if len(top) >= 2:
        out.append(
            f"{len(top)} خرید در ۲۰٪ بالای بازهٔ همان روز بود. قله‌ی بعد از شکاف معمولاً "
            "همان لحظه‌ای است که فشار فروش شروع می‌شود؛ سفارش حدی پایین‌تر بگذارید."
        )
    green = [r for r in rows if any(f["key"] == "green_but_loss" for f in r["flags"])]
    if green:
        out.append(
            f"{len(green)} خرید در روزی بود که کندل سبز بود ولی آخرین معامله زیر قیمت خرید ماند. "
            "پایانی میانگین وزنی است و آخرین معامله قیمت فروش واقعی شماست؛ هر دو را کنار هم ببینید."
        )
    loss = [r for r in rows if (r.get("pnl_last") or 0) < 0]
    if loss and len(loss) == n and n >= 2:
        out.append(
            "همهٔ خریدهای این دوره با آخرین معامله در زیان‌اند؛ این الگوی ورود است، نه بدشانسی."
        )
    return out


# ---------------------------------------------------------------------------------------------
# the best entry: where a limit order is worth leaving, whatever colour the candle ends up

LADDER_P = (0.85, 0.70, 0.55, 0.40, 0.25, 0.12)  # how often the day's low reached the level
SESSION_MINUTES = 210  # 09:00 to 12:30
TICK = 10.0  # rial; limit prices are placed on this step
MIN_OWN_DAYS = 25
OWN_PRIOR_DAYS = 40.0  # own history counts n / (n + 40) against the market's days like today's


def _wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    order = np.argsort(x)
    x, w = x[order], w[order]
    cum = np.cumsum(w) - 0.5 * w
    cum /= w.sum()
    return float(np.interp(q, cum, x))


def _tick(price: float) -> float:
    return round(price / TICK) * TICK


def entry_plan(
    session: Session,
    instrument_id: int,
    bar: Bar,
    *,
    edge: float | None,
    cost: float,
    in_session: bool,
    now_minutes: int | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """Where to leave a buy limit so the entry is as cheap as the evidence allows.

    The day's lowest price against yesterday's close is read from the stored history: the days of
    all liquid symbols that opened like today (same gap bucket) blended with this symbol's own
    days. From that distribution each ladder step is a price the day's low reached on a known
    share of days. The expected net return of leaving the order at a price is
    ``P(fill) x (target / price - 1 - cost)`` where the target is yesterday's close plus the
    model's tested edge; the step that maximises it is the recommended limit. A limit that is
    not filled by the close is cancelled, not chased. Nothing here looks at the candle's colour.
    """
    p = panel(session)
    ref = bar.yesterday if in_session else (bar.close or bar.last)
    if p is None or not ref:
        return {"available": False, "message": "تاریخچهٔ کافی برای برنامهٔ ورود نیست."}
    gap = bar.gap if in_session else None
    last = bar.last if in_session and bar.last else ref
    dip = p.lo / p.pc - 1
    gaps = p.o / p.pc - 1
    keep = (p.adj_ok > 0) & (np.abs(gaps) < 0.055)
    uni = keep.copy()
    label = None
    if gap is not None:
        for i, text in enumerate(GAP_LABELS):
            if GAP_EDGES[i] < gap <= GAP_EDGES[i + 1]:
                uni = keep & (gaps > GAP_EDGES[i]) & (gaps <= GAP_EDGES[i + 1])
                label = text
                break
    if uni.sum() < 200:  # too thin a bucket: all days
        uni, label = keep.copy(), None
    own_all = keep & (p.iid == instrument_id)
    own = own_all & uni if (own_all & uni).sum() >= MIN_OWN_DAYS else own_all
    n_uni, n_own = int(uni.sum()), int(own.sum())
    x = dip[uni]
    w = np.full(n_uni, 1.0 / n_uni)
    if n_own >= MIN_OWN_DAYS:
        share = n_own / (n_own + OWN_PRIOR_DAYS)
        x = np.concatenate([x, dip[own]])
        w = np.concatenate([w * (1 - share), np.full(n_own, share / n_own)])
    rem = None
    factor = 1.0
    if in_session and now_minutes is not None and now_minutes >= 0:
        rem = max(0, SESSION_MINUTES - now_minutes)
        factor = math.sqrt(rem / SESSION_MINUTES)
    target = ref * (1 + edge) if edge is not None and verdict == "buy" else None
    ladder: list[dict[str, Any]] = []
    for prob in LADDER_P:
        price = _tick(ref * (1 + _wquantile(x, w, prob)))
        if bar.limit_down and price < bar.limit_down:
            price = _tick(bar.limit_down)
        if price >= last:  # at or above where it trades now: that is a market buy, not a limit
            continue
        fill = prob * factor if in_session else prob
        ev = None if target is None else fill * (target / price - 1 - cost)
        ladder.append(
            {
                "fill_prob": fill,
                "day_fill_prob": prob,
                "price": price,
                "vs_now": price / last - 1,
                "vs_ref": price / ref - 1,
                "touched_today": bool(in_session and bar.low and bar.low <= price),
                "ev": ev,
            }
        )
    best = None
    if target is not None:
        pos = [s for s in ladder if (s["ev"] or 0) > 0]
        best = max(pos, key=lambda s: s["ev"]) if pos else None
    now_ev = None if target is None else target / last - 1 - cost
    out: dict[str, Any] = {
        "available": True,
        "mode": "today" if in_session else "next",
        "reference": ref,
        "now": last,
        "ladder": ladder,
        "recommended": best,
        "market_now": {"price": last, "ev": now_ev} if now_ev is not None else None,
        "basis": {
            "market_days": n_uni,
            "own_days": n_own,
            "gap_bucket": label,
            "minutes_left": rem,
        },
        "notes": [
            "احتمال پرشدن از روی کمترین قیمت روزهای گذشته نسبت به پایانی روز قبل به‌دست آمده؛ "
            "سفارشی که تا پایان روز پر نشد لغو می‌شود و دنبال قیمت نروید.",
        ],
    }
    if rem is not None and rem < SESSION_MINUTES:
        out["notes"].append(
            "احتمال‌ها با گذشت وقت کم شده‌اند (برآورد اولیه، هنوز روی دادهٔ دقیقه‌ای آزموده نشده)."
        )
    if target is None:
        out["notes"].append(
            "مدل برای این سهم خرید نمی‌گوید؛ نردبان فقط نشان می‌دهد هر قیمت با چه احتمالی پر "
            "می‌شود و قیمت پیشنهادی ندارد."
        )
        out["headline"] = "مدل خرید نمی‌گوید؛ قیمت پیشنهادی ندارد."
    elif best is not None:
        save = -best["vs_now"]
        out["headline"] = (
            f"سفارش حدی را روی {best['price']:,.0f} بگذارید؛ در گذشته در "
            f"{_pct(best['day_fill_prob'], 0)} روزها کمینهٔ روز به آن رسیده و "
            f"{_pct(save)} ارزان‌تر از قیمت فعلی است."
        ).replace(",", "٬")
        if now_ev is not None and now_ev > 0 and best["ev"] is not None:
            out["notes"].append(
                "خرید همین حالا هم هنوز برتری دارد؛ اگر نگران جاماندن هستید، بخشی را حالا و "
                "بخشی را در قیمت پیشنهادی بخرید."
            )
    else:
        out["headline"] = "در هیچ قیمتی که امروز با احتمال معقول پر شود برتری باقی نمی‌ماند."
    return out
