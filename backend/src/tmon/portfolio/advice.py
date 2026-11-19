"""What to do with a portfolio: keep, sell, switch, and what to buy with the cash.

Everything comes from the model's daily ranking document (``tmon.tools.v2_ranking``): each scored
stock has a cross-sectional score (0..1, the share of the basket it beats) and a band inside the
liquid basket (candidate / middle / avoid, ADR 0004 section 5), turned into the verdict of the
stock page by ``final_verdict``. A holding in the avoid zone, or in a sell queue, is weak. A switch
is suggested only when a candidate is far enough ahead that the measured top-minus-bottom excess
return of the model over 20 days is larger than the round-trip cost of selling one and buying the
other; otherwise the cost would eat the gain. Free cash is offered to candidates only (never one in
a buy queue), sized by cash times the market's exposure; with a positive exposure and no candidate
it is offered to the market itself, and with exposure zero nothing is offered. When the ranking
itself has not passed its validation gate (``recommendation_allowed`` false) every suggestion is
marked as unvalidated.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.market_card import market_card
from tmon.api.routers.dashboard import _turning_doc
from tmon.core.timeutil import tehran_today
from tmon.domain.compare import Release, inflation_since, real_return
from tmon.engine.verdict import final_verdict
from tmon.portfolio import liveprice
from tmon.storage.models import Holding, Instrument, MacroSeries, Portfolio, PriceDaily
from tmon.storage.objectstore import read_artifact
from tmon.tools.v2_ranking import KEY

log = logging.getLogger(__name__)

ROUND_TRIP = 0.017512
GRADE_LABEL = {"proven": "ثابت‌شده", "probable": "احتمالی", "unproven": "ثابت‌نشده"}
SWITCH_GAP = 0.25  # score gap (share of the basket) a switch must clear
MAX_BUYS = 5
NO_CANDIDATE_FA = (
    "امروز نامزد خریدِ قابل‌خرید نداریم: نامزدها یا در صف خرید هستند یا وضعیت خودشان مانع است."
)
MARKET_OFF_FA = (
    "امروز سهم سرمایه در سهام صفر است (روند یا مومنتوم بازار منفی، یا صف فروش سنگین)؛ "
    "هیچ خریدی پیشنهاد نمی‌شود. نقد نگه دارید."
)
BUYABLE = ("buy", "candidate")  # the codes of ``final_verdict`` that can be ordered today
SHOWN = ("buy", "candidate", "candidate_queue")  # candidates worth listing, buyable or not
BAND_FA = {
    "candidate": "نامزد خرید",
    "middle": "میانه",
    "avoid": "ناحیهٔ پایین",
    None: "بدون امتیاز",
}


def ranking_doc() -> dict[str, Any] | None:
    try:
        return read_artifact(KEY)
    except Exception:
        log.info("ranking document not available", exc_info=True)
        return None


def last_prices(
    session: Session, ids: list[int], *, live: bool = False
) -> dict[int, tuple[float, float | None, str]]:
    """Newest day's ``(last trade, official close, date)`` per instrument.

    The last trade (آخرین) is what a seller gets, so values and stop levels use it; the official
    close (پایانی, a volume-weighted average) can sit above it on a day that "closed green" while
    the last trades were lower. Where a day has no last trade the close stands in.

    With ``live`` an instrument whose exchange day is newer than the stored one (market open, or
    the evening cycle not yet run) is priced from the exchange instead of the previous day."""
    if not ids:
        return {}
    sub = (
        select(PriceDaily.instrument_id, func.max(PriceDaily.date).label("d"))
        .where(PriceDaily.instrument_id.in_(ids), PriceDaily.close.is_not(None))
        .group_by(PriceDaily.instrument_id)
        .subquery()
    )
    rows = session.execute(
        select(PriceDaily.instrument_id, PriceDaily.last, PriceDaily.close, PriceDaily.date).join(
            sub, (sub.c.instrument_id == PriceDaily.instrument_id) & (sub.c.d == PriceDaily.date)
        )
    )
    out: dict[int, tuple[float, float | None, str]] = {}
    for i, last, close, d in rows:
        price = float(last) if last else (float(close) if close else 0.0)
        if price:
            out[int(i)] = (price, float(close) if close else None, d.isoformat())
    if live:
        have = {i: dt.date.fromisoformat(v[2]) for i, v in out.items()}
        fresh = liveprice.live_marks(session, {i: have.get(i) for i in ids})
        for i, (price, close, day) in fresh.items():
            out[i] = (price, close, day.isoformat())
    return out


@dataclass(frozen=True)
class Scored:
    id: int
    score: float | None
    zone: str | None
    queue_state: str
    halted: bool
    rank: int | None  # 1 = best among the scored
    partial: bool = False  # scored from fewer than the four signals (short history)
    signals_as_of: str | None = None
    verdict: str | None = (
        None  # colour key of the stock page verdict: buy / candidate / hold / sell
    )
    band: str | None = None  # candidate / middle / avoid inside the liquid basket
    code: str | None = None  # the stock page's answer for someone who does not own it
    holder_code: str | None = None  # ... and for an owner
    grade_label: str | None = None  # evidence grade of the band's zone


def _scored(doc: dict[str, Any] | None, turn: dict[str, Any] | None = None) -> dict[int, Scored]:
    if not doc:
        return {}
    uni = doc.get("universe") or []
    ordered = sorted((u for u in uni if u.get("score") is not None), key=lambda u: -u["score"])
    rank = {int(u["id"]): i + 1 for i, u in enumerate(ordered)}

    out: dict[int, Scored] = {}
    for u in uni:
        v = final_verdict(doc, u, turn, int(u["id"]))
        out[int(u["id"])] = Scored(
            int(u["id"]),
            u.get("score"),
            u.get("zone"),
            str(u.get("queue_state") or "none"),
            bool(u.get("halted")),
            rank.get(int(u["id"])),
            bool(u.get("partial")),
            u.get("signals_as_of"),
            v.key if v else None,
            v.band if v else None,
            v.code if v else None,
            v.holder_code if v else None,
            GRADE_LABEL.get(v.grade or "") if v and v.grade else None,
        )
    return out


def _edge(doc: dict[str, Any] | None) -> float | None:
    """Measured top-minus-bottom excess return over 20 days (the switch's expected gain)."""
    for e in (doc or {}).get("evidence") or []:
        if e.get("horizon_days") == 20:
            return float(e.get("top_excess", 0)) - float(e.get("bottom_excess", 0))
    return None


def _holding_verdict(
    h: Holding, sc: Scored | None, price: float | None, *, market_off: bool = False
) -> tuple[str, list[str]]:
    """One verdict per holding, from the same ``final_verdict`` the stock page shows.

    ``strong``  the held stock is a candidate (top of the liquid basket); ``hold`` the page says
                keep it; ``weak`` the page says to weigh a sale (its zone lags the market and that
                is backed by evidence); ``sell`` an urgent exit (stop level reached, or the sell
                queue);  ``watch`` no score. With ``market_off`` (exposure zero) the verdict stays
                and a market warning is added. The price is the last trade, the one a seller
                gets."""
    reasons: list[str] = []
    pnl = (price / h.avg_price - 1) if price and h.avg_price else None
    if h.stop_price and price and price <= h.stop_price:
        return "sell", [f"قیمت ({price:,.0f}) به حد ضرر تعیین‌شده ({h.stop_price:,.0f}) رسیده است."]
    if sc is None or sc.score is None:
        reasons.append(
            "مدل برای این نماد امتیازی ندارد (کم‌معامله یا داده ناقص)؛ فقط هشدارهای لحظه‌ای فعال است."
        )
        return "watch", reasons
    reasons.append(
        f"امتیاز مدل {sc.score:.2f} (رتبهٔ {sc.rank}) در ناحیهٔ «{BAND_FA.get(sc.band, '—')}» "
        "بین سهم‌های پرمعامله."
    )
    if sc.partial:
        reasons.append("امتیاز از بخشی از نشانه‌ها ساخته شده (سابقهٔ کوتاه)؛ با احتیاط بخوانید.")
    if sc.queue_state == "sell_queue":
        reasons.append("در صف فروش است؛ فروش فوری ممکن نیست و خطر ادامهٔ ریزش هست.")
        return "sell", reasons
    if market_off:
        reasons.append("هشدار بازار: سهم سرمایه در سهام امروز صفر است؛ بازار در کل خوب نیست.")
    if sc.band == "avoid" and sc.holder_code != "consider_sell":
        # same as the stock page: a low score whose lag is not proven is no reason to sell
        reasons.append(
            f"ولی عقب‌ماندگی این ناحیه در گذشته هنوز ثابت نشده (شواهد: {sc.grade_label})، پس فروش "
            "لازم نیست؛ خرید تازه نکنید و حد ضرر بگذارید."
        )
    if pnl is not None:
        reasons.append(f"سود/زیان فعلی {pnl * 100:+.1f}٪ نسبت به میانگین خرید (آخرین معامله).")
    if sc.holder_code == "consider_sell":
        return "weak", reasons
    if sc.band == "candidate":
        return "strong", reasons
    return "hold", reasons


INFLATION_BAR_FA = (
    "سود فقط وقتی واقعی است که از تورم جلو بیفتد. در سه سال گذشته شاخص کل در بیشتر بازه‌های "
    "۱۲ ماهه از تورم عقب ماند، و از معامله‌های بسته‌شدهٔ قاعدهٔ روند فقط حدود ۱۷ از هر ۱۰۰ "
    "پس از تورم سود داد؛ جابه‌جایی بیشتر هم این را بهتر نکرد."
)  # measured in docs/reports/inflation-hurdle-2026-11.md


def _cpi_releases(session: Session) -> list[Release]:
    return [
        Release(m.ref_period, m.release_date or m.ref_period, m.value, m.source_url)
        for m in session.scalars(
            select(MacroSeries).where(MacroSeries.series == "cpi_mom", MacroSeries.source == "sci")
        )
    ]


def inflation_check(
    mom: list[Release], bought_on: dt.date | None, pnl: float | None, today: dt.date
) -> tuple[dict[str, Any], str | None]:
    """The portfolio's bar (docs/07): the gain since the buy day against consumer prices over the
    same days. Returns the fields for the holding and one plain sentence, or ``None`` fields when
    the buy day or the price is unknown."""
    empty: dict[str, Any] = {
        "inflation_since_buy": None,
        "real_pnl_pct": None,
        "ahead_of_inflation": None,
    }
    if bought_on is None:
        return empty, "تاریخ خرید ثبت نشده، پس سنجش با تورم ممکن نیست؛ تاریخ خرید را وارد کنید."
    inf = inflation_since(mom, bought_on, today)
    if inf is None or pnl is None:
        return empty, None
    real = real_return(pnl, inf.value)
    fields = {
        "inflation_since_buy": inf.value,
        "real_pnl_pct": real,
        "ahead_of_inflation": real > 0,
        "inflation_estimated_days": inf.estimated_days,
    }
    text = (
        f"تورم از روز خرید حدود {inf.value * 100:.1f}٪ بوده؛ بازده پس از کم کردن تورم "
        f"{real * 100:+.1f}٪ است"
    )
    if real > 0:
        text += "، یعنی از تورم جلو است و سود واقعی دارد."
    elif pnl > 0:
        text += "؛ سود اسمی دارید ولی از تورم عقب است، پس هنوز سود واقعی نیست."
    else:
        text += "؛ هم زیان اسمی دارد و هم از تورم عقب است."
    if inf.estimated_days:
        text += f" تورم {inf.estimated_days} روز آخر هنوز منتشر نشده و با نرخ آخرین ماه حساب شد."
    return fields, text


VERDICT_FA = {
    "strong": "نگه‌دار — نامزد خرید مدل",
    "hold": "نگه‌دار",
    "weak": "فروش را بسنجید — ناحیهٔ پایین، با شواهد",
    "sell": "فروش فوری",
    "watch": "زیر نظر",
}


def advise(session: Session, portfolio: Portfolio) -> dict[str, Any]:
    doc = ranking_doc()
    scored = _scored(doc, _turning_doc())
    holdings = list(
        session.scalars(
            select(Holding).where(Holding.portfolio_id == portfolio.id, Holding.shares > 0)
        )
    )
    held = {h.instrument_id for h in holdings}
    # candidates worth listing; one in a buy queue stays in the list, flagged not buyable, and is
    # never ordered. With exposure zero the verdict is "wait: market", so nobody is listed.
    candidates = sorted(
        (
            s
            for s in scored.values()
            if s.code in SHOWN and s.score is not None and not s.halted and s.id not in held
        ),
        key=lambda s: -(s.score or 0),
    )
    # an equity fund has no verdict of its own (it appears in the market card instead), as on the
    # ranking page and the symbol page
    kinds = dict(
        session.execute(
            select(Instrument.id, Instrument.instrument_type).where(
                Instrument.id.in_([c.id for c in candidates])
            )
        ).all()
    )
    candidates = [c for c in candidates if kinds.get(c.id, "stock") == "stock"]
    buyable = [c for c in candidates if c.code in BUYABLE and c.queue_state == "none"]
    exposure = ((doc or {}).get("exposure") or {}).get("exposure")
    market_off = exposure is not None and exposure <= 1e-9
    ids = sorted(held | {c.id for c in candidates[:20]})
    prices = last_prices(session, ids, live=True)
    names = {
        i.id: (i.symbol_fa, i.name_fa)
        for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    edge = _edge(doc)
    cpi = _cpi_releases(session)
    today = tehran_today()
    validated = bool((doc or {}).get("recommendation_allowed"))
    cost = float((doc or {}).get("round_trip_cost") or ROUND_TRIP)

    def cand_out(s: Scored) -> dict[str, Any]:
        sym, name = names.get(s.id, (str(s.id), None))
        c = prices.get(s.id)
        return {
            "instrument_id": s.id,
            "symbol": sym,
            "name": name,
            "score": s.score,
            "rank": s.rank,
            "zone": s.zone,
            "band": s.band,
            "verdict": s.verdict,
            "code": s.code,
            "grade_label": s.grade_label,
            "queue_state": s.queue_state,
            "buyable": s in buyable,
            "last": c[0] if c else None,
            "close": c[1] if c else None,
        }

    out_h: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    used: set[int] = set()
    value = 0.0
    for h in holdings:
        sc = scored.get(h.instrument_id)
        c = prices.get(h.instrument_id)
        last = c[0] if c else None
        close = c[1] if c else None
        verdict, reasons = _holding_verdict(h, sc, last, market_off=market_off)
        pnl = (last / h.avg_price - 1) if last and h.avg_price else None
        infl, infl_text = inflation_check(cpi, h.bought_on, pnl, today)
        if infl_text:
            reasons.append(infl_text)
        sym, name = names.get(h.instrument_id, (str(h.instrument_id), None))
        mv = (last or h.avg_price) * h.shares
        value += mv
        out_h.append(
            {
                "holding_id": h.id,
                "instrument_id": h.instrument_id,
                "symbol": sym,
                "name": name,
                "shares": h.shares,
                "avg_price": h.avg_price,
                "last": last,
                "close": close,
                "close_date": c[2] if c else None,
                "market_value": mv,
                "pnl_pct": pnl,
                **infl,
                "pnl_pct_close": (close / h.avg_price - 1) if close and h.avg_price else None,
                "score": sc.score if sc else None,
                "rank": sc.rank if sc else None,
                "zone": sc.zone if sc else None,
                "queue_state": sc.queue_state if sc else None,
                "verdict": verdict,
                "verdict_fa": VERDICT_FA[verdict],
                "reasons": reasons,
            }
        )
        if verdict not in ("weak", "sell") or sc is None or sc.score is None:
            continue
        best = next((x for x in buyable if x.id not in used), None)
        if best is None or best.score is None:
            continue
        gap = best.score - sc.score
        # expected gain of the swap, scaled from the model's measured top-minus-bottom edge
        gain = edge * gap if edge is not None else None
        if verdict == "weak" and (gap < SWITCH_GAP or gain is None or gain <= cost):
            continue
        used.add(best.id)
        buy = cand_out(best)
        switches.append(
            {
                "sell": {"instrument_id": h.instrument_id, "symbol": sym, "score": sc.score},
                "buy": buy,
                "score_gap": gap,
                "expected_gain_20d": gain,
                "round_trip_cost": cost,
                "reason": (
                    f"{buy['symbol']} امتیاز {best.score:.2f} دارد در برابر "
                    f"{sc.score:.2f}؛ برتری ۲۰ روزهٔ برآوردی "
                    + (f"{gain * 100:.1f}٪" if gain is not None else "نامعلوم")
                    + f" بیشتر از هزینهٔ رفت‌وبرگشت {cost * 100:.2f}٪ است."
                ),
            }
        )

    buys: list[dict[str, Any]] = []
    cash = float(portfolio.cash or 0)
    share = 1.0 if exposure is None else float(exposure)
    budget = cash * share  # the equity part of the free cash, as the market card states it
    picks = [c for c in buyable if c.id not in used][:MAX_BUYS]
    if budget > 0 and picks:
        per = budget / len(picks)
        for pick in picks:
            row = cand_out(pick)
            price = row["last"]
            shares = int(per // (price * (1 + cost / 2))) if price else 0
            if shares > 0:
                buys.append({**row, "shares": shares, "amount": shares * price})
    card = market_card(session, doc) if doc else None
    market_buy = None
    if cash > 0 and not market_off and not picks and card is not None:
        market_buy = {
            "amount": budget,
            "text": (
                "نامزد خریدِ قابل‌خرید نیست؛ پس برای بخش سهامی نقد، خودِ بازار را بگیرید: سبد "
                "سهم‌های پرمعامله (هم‌وزن) یا یک صندوق سهامی پرمعامله. این پیشنهاد آزموده نشده "
                "است و سودی را تضمین نمی‌کند؛ بازار هم می‌تواند بیفتد."
            ),
        }
    if market_off:
        buy_note: str | None = MARKET_OFF_FA
    elif not buyable:
        buy_note = NO_CANDIDATE_FA
    else:
        buy_note = None
    return {
        "as_of": (doc or {}).get("as_of"),
        "validated": validated,
        "note": (
            "رتبه‌بندی مدل از آزمون اعتبار گذشته است."
            if validated
            else "رتبه‌بندی فعلی از آزمون اعتبار عبور نکرده است؛ "
            "پیشنهادها فقط برای بررسی است، نه توصیهٔ قطعی."
        ),
        "market_value": value,
        "cash": cash,
        "holdings": out_h,
        "switches": switches,
        "buys": buys,
        "buy_note": buy_note,
        "inflation_note": INFLATION_BAR_FA,
        "exposure": exposure,
        "market": None if card is None else card.model_dump(mode="json"),
        "market_buy": market_buy,
        "candidates": [] if market_off else [cand_out(c) for c in candidates[:10]],
    }
