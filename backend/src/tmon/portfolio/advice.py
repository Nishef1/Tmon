"""What to do with a portfolio: keep, sell, switch, and what to buy with the cash.

Everything comes from the model's daily ranking document (``tmon.tools.v2_ranking``): each scored
stock has a cross-sectional score (0..1, the share of the basket it beats) and a zone (buy / hold /
avoid). A holding in the avoid zone, or in a sell queue, is weak. A switch is suggested only when a
buy-zone stock is far enough ahead that the measured top-minus-bottom excess return of the model
over 20 days is larger than the round-trip cost of selling one and buying the other; otherwise the
cost would eat the gain. When the ranking itself has not passed its validation gate
(``recommendation_allowed`` false) every suggestion is marked as unvalidated.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.dashboard import _turning_doc, final_verdict
from tmon.core.config import get_settings
from tmon.portfolio import liveprice
from tmon.storage.models import Holding, Instrument, Portfolio, PriceDaily
from tmon.storage.objectstore import get_object_store
from tmon.tools.v2_ranking import KEY

log = logging.getLogger(__name__)

ROUND_TRIP = 0.017512
SWITCH_GAP = 0.25  # score gap (share of the basket) a switch must clear
MAX_BUYS = 5
NO_BUY_FA = (
    "امروز هیچ نمادی هم در محدودهٔ خرید است و هم آزمون ماهانه پس از کارمزد برتری‌اش را تأیید کرده؛ "
    "همان حکمی که صفحهٔ هر سهم نشان می‌دهد. نقد نگه دارید و عجله نکنید."
)
ZONE_FA = {"buy": "خرید", "hold": "نگهداری", "avoid": "فروش", None: "بدون امتیاز"}


def ranking_doc() -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, KEY)
    except Exception:
        log.info("ranking document not available", exc_info=True)
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


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
    verdict: str | None = None  # the verdict the stock page shows: buy / hold / sell


def _scored(doc: dict[str, Any] | None, turn: dict[str, Any] | None = None) -> dict[int, Scored]:
    if not doc:
        return {}
    uni = doc.get("universe") or []
    ordered = sorted((u for u in uni if u.get("score") is not None), key=lambda u: -u["score"])
    rank = {int(u["id"]): i + 1 for i, u in enumerate(ordered)}

    def verdict(u: dict[str, Any]) -> str | None:
        sig = {k: x for k, x in (u.get("signals") or {}).items() if x is not None}
        v = final_verdict(doc, u.get("zone"), sig, turn, int(u["id"]))
        return v if v in ("buy", "hold", "sell") else None

    return {
        int(u["id"]): Scored(
            int(u["id"]),
            u.get("score"),
            u.get("zone"),
            str(u.get("queue_state") or "none"),
            bool(u.get("halted")),
            rank.get(int(u["id"])),
            bool(u.get("partial")),
            u.get("signals_as_of"),
            verdict(u),
        )
        for u in uni
    }


def _edge(doc: dict[str, Any] | None) -> float | None:
    """Measured top-minus-bottom excess return over 20 days (the switch's expected gain)."""
    for e in (doc or {}).get("evidence") or []:
        if e.get("horizon_days") == 20:
            return float(e.get("top_excess", 0)) - float(e.get("bottom_excess", 0))
    return None


def _holding_verdict(h: Holding, sc: Scored | None, price: float | None) -> tuple[str, list[str]]:
    """One verdict per holding, from the same ``final_verdict`` the stock page shows.

    ``strong``  the page says buy (the held stock is in the model's buy zone and the tested month
                supports it);  ``hold`` the page says hold;  ``weak`` the page says sell;
    ``sell``    an urgent exit (stop level reached, or the sell queue);  ``watch`` no score.
    The price is the last trade, the one a seller gets."""
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
        f"امتیاز مدل {sc.score:.2f} (رتبهٔ {sc.rank}) در ناحیهٔ «{ZONE_FA.get(sc.zone, sc.zone)}»."
    )
    if sc.partial:
        reasons.append("امتیاز از بخشی از نشانه‌ها ساخته شده (سابقهٔ کوتاه)؛ با احتیاط بخوانید.")
    if sc.queue_state == "sell_queue":
        reasons.append("در صف فروش است؛ فروش فوری ممکن نیست و خطر ادامهٔ ریزش هست.")
        return "sell", reasons
    if pnl is not None:
        reasons.append(f"سود/زیان فعلی {pnl * 100:+.1f}٪ نسبت به میانگین خرید (آخرین معامله).")
    if sc.verdict == "sell":
        return "weak", reasons
    if sc.verdict == "buy":
        return "strong", reasons
    if sc.zone == "buy":
        # the zone says buy but the tested month does not carry it: same as the stock page, wait
        reasons.append("امتیاز بالاست ولی آزمون ماه گذشته پس از کارمزد برتری را تأیید نکرده است.")
    return "hold", reasons


VERDICT_FA = {
    "strong": "نگهداری — در محدودهٔ خرید مدل",
    "hold": "نگهداری",
    "weak": "فروش — مدل آن را در محدودهٔ فروش می‌بیند",
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
    candidates = sorted(
        (
            s
            for s in scored.values()
            if s.verdict == "buy"
            and s.score is not None
            and not s.halted
            and s.queue_state == "none"
            and s.id not in held
        ),
        key=lambda s: -(s.score or 0),
    )
    ids = sorted(held | {c.id for c in candidates[:20]})
    prices = last_prices(session, ids, live=True)
    names = {
        i.id: (i.symbol_fa, i.name_fa)
        for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    edge = _edge(doc)
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
            "verdict": s.verdict,
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
        verdict, reasons = _holding_verdict(h, sc, last)
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
                "pnl_pct": (last / h.avg_price - 1) if last and h.avg_price else None,
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
        best = next((x for x in candidates if x.id not in used), None)
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
    picks = [c for c in candidates if c.id not in used][:MAX_BUYS]
    if cash > 0 and picks:
        per = cash / len(picks)
        for pick in picks:
            row = cand_out(pick)
            price = row["last"]
            shares = int(per // (price * (1 + cost / 2))) if price else 0
            if shares > 0:
                buys.append({**row, "shares": shares, "amount": shares * price})
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
        "buy_note": None if candidates else NO_BUY_FA,
        "candidates": [cand_out(c) for c in candidates[:10]],
    }
