"""One symbol's full dashboard: price block, volume statistics, real/legal money flow, fund NAV and
the final decision (buy / hold / sell / none) with its reasons. Everything is read from stored
daily tables and the latest ranking document; nothing is estimated here."""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.returns import day_change
from tmon.api.routers.recommendations import instrument_out
from tmon.api.schemas import (
    DashDecision,
    DashEvent,
    DashFlow,
    DashFund,
    DashFundamental,
    DashHolding,
    DashHorizon,
    DashMeeting,
    DashPrice,
    DashRanges,
    DashShareChange,
    DashSignal,
    DashTurning,
    InstrumentDashboard,
    TurningHorizon,
    TurningState,
    TurningTrigger,
)
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import to_tehran, utcnow
from tmon.domain.fundamentals import Fundamental, fundamental
from tmon.storage.models import (
    ClientTypeDaily,
    CorporateEvent,
    FundNav,
    Instrument,
    PriceDaily,
    SectorName,
    ShareChange,
)
from tmon.storage.objectstore import get_object_store
from tmon.tools.turning_points import KEY as TURNING_KEY
from tmon.tools.v2_ranking import KEY

log = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

SIGNAL_FA = {
    "ind_buy_power": "قدرت خریدار حقیقی",
    "rv_20": "آرام‌بودن قیمت",
    "dist_high_52w": "نزدیکی به سقف یک‌ساله",
    "mom_12_1": "روند ۱۲ ماههٔ قیمت",
}
SIGNAL_WHAT = {
    "ind_buy_power": "خریداران حقیقی چقدر بیشتر از فروشندگان حقیقی پول وارد سهم کرده‌اند",
    "rv_20": "قیمت در ۲۰ روز اخیر چقدر کم‌نوسان بوده است (آرام‌تر یعنی ریسک کمتر)",
    "dist_high_52w": "قیمت امروز چقدر به بالاترین قیمت یک سال اخیر نزدیک است",
    "mom_12_1": "قیمت در یک سال گذشته (به‌جز ماه آخر) چقدر رشد کرده است",
}
HOLD_DAYS = 20  # the horizon the evidence table is read at, in trading days
LABEL = {"buy": "خرید", "hold": "نگهداری", "sell": "فروش", "none": "تصمیمی نیست"}
TYPE_FA = {
    "bond": "اوراق بدهی",
    "right": "حق‌تقدم",
    "future": "قرارداد آتی",
    "commodity_certificate": "گواهی کالایی",
    "other": "ابزار غیرسهامی",
}


def _kind(instrument_type: str) -> str:
    if instrument_type.startswith("etf_"):
        return "صندوق قابل معامله"
    if instrument_type.startswith("option_"):
        return "اختیار معامله"
    return TYPE_FA.get(instrument_type, "ابزار غیرسهامی")


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}٪".replace(".", "٫")


def _price(rows: list[PriceDaily]) -> DashPrice | None:
    if not rows:
        return None
    p = rows[0]
    vols = [float(r.volume or 0) for r in rows]
    prior30 = [v for v in vols[1:31] if v > 0]

    def avg(n: int) -> float | None:
        w = [v for v in vols[:n] if v > 0]
        return sum(w) / len(w) if len(w) >= max(3, n // 2) else None

    prev = _f(p.prev_close)
    return DashPrice(
        date=str(p.date),
        open=_f(p.open),
        high=_f(p.high),
        low=_f(p.low),
        last=_f(p.last),
        close=_f(p.close),
        prev_close=prev,
        last_change=(float(p.last) / prev - 1) if p.last and prev else None,
        close_change=day_change(_f(p.close), prev),
        limit_up=_f(p.limit_up),
        limit_down=_f(p.limit_down),
        trades=p.trades,
        volume=_f(p.volume),
        value=_f(p.value),
        base_volume=_f(p.base_volume),
        avg_volume_10=avg(10),
        avg_volume_22=avg(22),
        volume_ratio_30=(vols[0] / (sum(prior30) / len(prior30))) if prior30 and vols[0] else None,
    )


def _per_capita(r: ClientTypeDaily) -> tuple[float | None, float | None]:
    b = float(r.buy_value_i) / r.buy_count_i if r.buy_value_i and r.buy_count_i else None
    s = float(r.sell_value_i) / r.sell_count_i if r.sell_value_i and r.sell_count_i else None
    return b, s


def _flow(rows: list[ClientTypeDaily]) -> DashFlow | None:
    if not rows:
        return None
    c = rows[0]
    b0, s0 = _per_capita(c)
    hist = [_per_capita(r) for r in rows[:10]]
    bs = [b for b, _ in hist if b]
    ss = [s for _, s in hist if s]
    ab = statistics.fmean(bs) if bs else None
    asl = statistics.fmean(ss) if ss else None
    net_v = (
        float(c.buy_value_i) - float(c.sell_value_i)
        if c.buy_value_i is not None and c.sell_value_i is not None
        else None
    )
    net_q = (
        float(c.buy_volume_i) - float(c.sell_volume_i)
        if c.buy_volume_i is not None and c.sell_volume_i is not None
        else None
    )
    return DashFlow(
        date=str(c.date),
        buy_volume_i=_f(c.buy_volume_i),
        buy_volume_n=_f(c.buy_volume_n),
        sell_volume_i=_f(c.sell_volume_i),
        sell_volume_n=_f(c.sell_volume_n),
        buy_count_i=c.buy_count_i,
        buy_count_n=c.buy_count_n,
        sell_count_i=c.sell_count_i,
        sell_count_n=c.sell_count_n,
        per_capita_buy=b0,
        per_capita_sell=s0,
        power=(b0 / s0) if b0 and s0 else None,
        net_real_value=net_v,
        net_real_volume=net_q,
        avg10_per_capita_buy=ab,
        avg10_per_capita_sell=asl,
        avg10_power=(ab / asl) if ab and asl else None,
    )


def _ranking_doc() -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, KEY)
    except (FileNotFoundError, KeyError):
        return None
    except Exception:  # store unreachable: say "not computed" instead of failing the page
        log.warning("ranking document unreadable", exc_info=True)
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


STAGE_FA = {
    "invitation": "دعوت به مجمع عادی سالیانه",
    "egm_invitation": "دعوت به مجمع فوق‌العاده",
    "ordinary_extraordinary_invitation": "دعوت به مجمع عادی به‌طور فوق‌العاده",
    "decisions": "تصمیمات مجمع",
    "decisions_summary": "خلاصه تصمیمات مجمع",
    "dividend_schedule": "زمان‌بندی پرداخت سود",
    "board_proposal": "پیشنهاد هیئت‌مدیره برای افزایش سرمایه",
    "board_decision": "تصمیم هیئت‌مدیره دربارهٔ افزایش سرمایه",
    "auditor_opinion": "گزارش بازرس دربارهٔ افزایش سرمایه",
    "registered": "ثبت افزایش سرمایه",
    "meeting_cancelled": "لغو مجمع",
    "public_subscription_extended": "تمدید مهلت پذیره‌نویسی",
    "rights_deadline_extended": "تمدید مهلت حق تقدم",
}
INVITATION_STAGES = ("invitation", "egm_invitation", "ordinary_extraordinary_invitation")
# letters that only repeat an earlier one add nothing to the list
_SKIP_STAGES = ("decisions_registered", "dividend_schedule_prior_years", "documents")


def _meeting(events: list[CorporateEvent], today: dt.date) -> DashMeeting | None:
    """The nearest assembly that has not met yet and was not cancelled after its invitation."""
    best: DashMeeting | None = None
    for e in events:
        if e.stage not in INVITATION_STAGES or e.event_date is None or e.event_date < today:
            continue
        cancelled = any(
            c.stage == "meeting_cancelled"
            and c.announced_at is not None
            and e.announced_at is not None
            and c.announced_at >= e.announced_at
            for c in events
        )
        if cancelled:
            continue
        cand = DashMeeting(
            date=e.event_date,
            kind=STAGE_FA.get(e.stage or "", "مجمع"),
            days_left=(e.event_date - today).days,
            title=e.title or "",
        )
        if best is None or cand.date < best.date:
            best = cand
    return best


def _events_out(events: list[CorporateEvent]) -> list[DashEvent]:
    out: list[DashEvent] = []
    for e in events:
        if e.stage in _SKIP_STAGES:
            continue
        out.append(
            DashEvent(
                date=e.event_date or e.announced_at,
                label=STAGE_FA.get(e.stage or "", e.title or "رویداد شرکتی"),
                title=e.title,
            )
        )
    return out[:8]


def fundamental_out(inst: Instrument, close: float | None, group: str | None) -> DashFundamental:
    tags = inst.tags or {}
    f: Fundamental = fundamental(_f(tags.get("eps")), _f(tags.get("sector_pe")), close, group)
    return DashFundamental(
        eps=f.eps,
        pe=f.pe,
        sector_pe=f.sector_pe,
        vs_sector=f.vs_sector,
        verdict=f.verdict,
        text=f.text,
    )


def _none(headline: str, reasons: list[str] | None = None, **extra: Any) -> DashDecision:
    return DashDecision(
        verdict="none", label=LABEL["none"], headline=headline, reasons=reasons or [], **extra
    )


MISSING_FA = {
    "ind_buy_power": "قدرت خریدار حقیقی",
    "rv_20": "نوسان ۲۰ روزه",
    "dist_high_52w": "فاصله از سقف یک‌ساله",
    "mom_12_1": "روند ۱۲ ماهه (به حدود یک سال سابقهٔ معامله نیاز دارد)",
}


def _signals(sig: dict[str, float]) -> list[DashSignal]:
    """All four signals, best first; ``pct`` is the share of scored stocks this one beats."""
    out = []
    for k, v in sorted(((k, v) for k, v in sig.items() if v is not None), key=lambda kv: -kv[1]):
        pct = v * 100
        out.append(
            DashSignal(
                key=k,
                name=SIGNAL_FA.get(k, k),
                pct=pct,
                text=f"{SIGNAL_WHAT.get(k, '')}؛ از {pct:.0f}٪ سهم‌ها بهتر است.",
            )
        )
    return out


def _signal_lines(sig: dict[str, float]) -> list[str]:
    best = _signals(sig)
    if not best:
        return []
    top, low = best[0], best[-1]
    out = [f"نقطهٔ قوت: {top.name}؛ بهتر از {top.pct:.0f}٪ سهم‌های دیگر."]
    if low.key != top.key:
        out.append(f"نقطهٔ ضعف: {low.name}؛ فقط از {low.pct:.0f}٪ سهم‌ها بهتر است.")
    return out


SUMMARY = {
    "buy": "در میان سهم‌های بازار جزو ۱۰٪ برتر امتیاز است؛ یعنی چند نشانهٔ خوب را با هم دارد.",
    "hold": "وضعش نسبتاً خوب است: اگر دارید نگه دارید؛ برای خرید تازه صبر کنید تا به ناحیهٔ "
    "خرید برسد.",
    "sell": "امتیازش در میان ضعیف‌ترین‌هاست: خرید نکنید و اگر دارید فروش را بسنجید.",
}


HORIZONS_FA = {
    1: ("D1", "فردا (۱ روز)"),
    5: ("W1", "یک هفته (۵ روز معاملاتی)"),
    20: ("M1", "یک ماه (۲۰ روز معاملاتی)"),
    60: ("Q1", "سه ماه (۶۰ روز معاملاتی)"),
}
MIN_NET_EDGE = 0.01  # declared in advance: past net excess must clear 1% (survivorship bias, noise)
MIN_T = 3.0  # and be statistically solid (Bonferroni-like bar used in the R1 report)


def _n(x: float, digits: int = 1, sign: bool = False) -> str:
    """A number with the Persian decimal separator."""
    return f"{x:{'+' if sign else ''}.{digits}f}".replace(".", "٫")


def _signed(x: float) -> str:
    return f"{x * 100:+.2f}٪".replace(".", "٫")


def _horizon_decision(
    h: int, ev: dict[str, Any], zone: str, cost: float, sig: dict[str, float], advice_base: bool
) -> DashHorizon:
    """Buy / hold / sell for one holding period from the symbol's zone and what that zone's past
    excess return was at this period, net of the round-trip cost. Nothing is fitted here."""
    key, label = HORIZONS_FA[h]
    top, bot = ev.get("top_excess"), ev.get("bottom_excess")
    t = ev.get("excess_t")
    net = None if top is None else top - cost
    reasons: list[str] = []
    if top is not None:
        reasons.append(
            f"در گذشته نمادهای ۱۰٪ برتر مدل، {label} بعد، به‌طور میانگین {_signed(top)} بیشتر از "
            f"میانهٔ بازار بازده داشته‌اند (نمونه: {ev.get('n_days')} روز؛ آمارهٔ t = "
            f"{_n(t or 0)}). هزینهٔ رفت‌وبرگشت خرید و فروش {_n(cost * 100, 2)}٪ است؛ پس خالص "
            f"{_signed(net or 0)}."
        )
    for k, name in SIGNAL_FA.items():
        s_ev = (ev.get("signals") or {}).get(k)
        v = sig.get(k)
        if not s_ev or s_ev.get("ic") is None or v is None:
            continue
        solid = (s_ev.get("t") or 0) >= 2.0
        reasons.append(
            f"{name}: این نماد از {v * 100:.0f}٪ سهم‌ها بهتر است؛ "
            + (
                f"این سیگنال در این بازه اثر معنی‌دار داشته (IC {_n(s_ev['ic'], 3, True)}، "
                f"t {_n(s_ev['t'])})."
                if solid
                else f"اما در این بازه اثر معنی‌داری نداشته (IC {_n(s_ev['ic'], 3, True)}، t "
                f"{_n(s_ev.get('t') or 0)})، پس روی تصمیم این بازه وزنی ندارد."
            )
        )
    solid_edge = net is not None and t is not None and net >= MIN_NET_EDGE and t >= MIN_T
    if zone == "buy":
        if solid_edge:
            verdict, head = "buy", f"برای {label}: خرید؛ مازاد گذشته پس از هزینه معنی‌دار است."
        elif net is not None and net > 0:
            verdict = "hold"
            why = (
                f"مازاد پس از هزینه ({_signed(net)}) از حداقل {_pct(MIN_NET_EDGE)} کمتر است"
                if net < MIN_NET_EDGE
                else f"اطمینان آماری کافی نیست (t = {_n(t or 0)}، حداقل {_n(MIN_T, 0)})"
            )
            head = f"برای {label}: خرید توصیه نمی‌شود؛ {why}."
        else:
            verdict = "hold"
            head = f"برای {label}: معامله نکنید؛ مازاد گذشته کمتر از هزینهٔ رفت‌وبرگشت است."
    elif zone == "hold":
        verdict, head = "hold", f"برای {label}: نگهداری؛ نماد در ناحیهٔ میانی مدل است."
    elif bot is not None and bot < -cost / 2:
        verdict = "sell"
        head = (
            f"برای {label}: فروش یا پرهیز؛ گروه ضعیف مدل در گذشته زیر بازار بوده ({_signed(bot)})."
        )
    else:
        verdict = "hold"
        head = (
            f"برای {label}: امتیاز پایین است ولی گروه ضعیف در این بازه زیر بازار نبوده"
            + (f" ({_signed(bot)})" if bot is not None else "")
            + "؛ دلیل آماری برای فروش وجود ندارد."
        )
    return DashHorizon(
        key=key,
        label=label,
        days=h,
        verdict=verdict,
        verdict_label=LABEL[verdict],
        headline=head,
        reasons=reasons,
        top_excess=top,
        cost=cost,
        net_excess=net,
        ic=ev.get("ic"),
        ic_t=ev.get("ic_t"),
    )


def _horizons(doc: dict[str, Any], zone: str, sig: dict[str, float]) -> list[DashHorizon]:
    cost = doc.get("round_trip_cost")
    if cost is None:
        return []
    by_h = {e["horizon_days"]: e for e in doc.get("evidence", [])}
    return [
        _horizon_decision(h, by_h[h], zone, float(cost), sig, True)
        for h in HORIZONS_FA
        if h in by_h
    ]


def _holding(verdict: str, doc: dict[str, Any], advice: bool) -> DashHolding:
    ev = next((e for e in doc.get("evidence", []) if e.get("horizon_days") == HOLD_DAYS), None)
    edge = ev.get("top_excess") if ev else None
    lines = [
        f"مدل برای نگهداری حدود {HOLD_DAYS} روز معاملاتی (حدود یک ماه) ساخته شده است، نه برای "
        "خرید و فروش در همان روز؛ آزمونی روی نگهداری یک‌روزه انجام نشده و نتیجه‌اش معلوم نیست."
    ]
    if verdict == "buy":
        if edge is not None:
            lines.append(
                f"در گذشته سهم‌های گروه برتر در {HOLD_DAYS} روز بعد به‌طور میانگین حدود "
                f"{edge * 100:.1f}٪ بیشتر از میانگین بازار بازده داشته‌اند. این میانگین است؛ برای "
                "یک سهم تضمینی ندارد و بعضی سهم‌های همین گروه ضرر می‌کنند."
            )
        lines.append(
            "کی بفروشم: هر ماه یک‌بار امتیاز را دوباره ببینید. تا وقتی نماد در ناحیهٔ خرید یا "
            "نگهداری است نگه دارید؛ اگر به ناحیهٔ فروش رفت بفروشید."
        )
        lines.append("اگر نماد در صف خرید باشد خرید ممکن نیست؛ با چشم بسته و درشت وارد نشوید.")
    elif verdict == "hold":
        lines.append(
            "اگر سهم را دارید همان‌طور نگه دارید و هر ماه امتیاز را ببینید؛ خرید تازه وقتی "
            "منطقی است که نماد به ناحیهٔ خرید برسد."
        )
    else:
        lines.append("خرید تازه نکنید. اگر دارید، هر ماه امتیاز را ببینید و فروش را بسنجید.")
    if not advice:
        lines.append("این‌ها آمار گذشته‌اند و هنوز توصیهٔ مطمئن نیستند (آزمون‌های اعتبار کامل نشده).")
    return DashHolding(horizon_days=HOLD_DAYS, expected_excess=edge, lines=lines)


def decide(
    inst: Instrument, doc: dict[str, Any] | None, median_value: float | None
) -> DashDecision:
    """Map the symbol to buy / hold / sell / none with plain-language reasons.

    Every stock that has the four signals gets a score and a gauge. Inside the validated liquid
    basket the verdict is the model's; outside it the same formula is applied but the verdict is
    marked unvalidated and never counts as advice."""
    if inst.instrument_type != "stock":
        kind = _kind(inst.instrument_type)
        return _none(
            f"این نماد {kind} است و مدل خرید/فروش فقط برای سهام ساخته شده است.",
            ["قیمت و پول حقیقی/حقوقی همین صفحه فقط برای اطلاع است و پیشنهاد نیست."],
        )
    if doc is None:
        return _none("رتبه‌بندی مدل هنوز محاسبه نشده است.")
    allowed = bool(doc.get("recommendation_allowed"))
    rows = doc.get("rows", [])
    size = int(doc.get("basket_size") or len(rows))
    as_of = doc.get("as_of")
    row = next((r for r in rows if r["symbol"] == inst.symbol_fa), None)
    uni = next((u for u in doc.get("universe", []) if u["id"] == inst.id), None)
    scored = [u for u in doc.get("universe", []) if u.get("score") is not None]
    if row is None and uni is None and "universe" in doc:
        return _none(
            f"امتیازی برای این نماد محاسبه نشد: در آخرین روز ثبت‌شده ({as_of}) معامله نشده است.",
            ["مدل فقط برای نمادهایی امتیاز می‌دهد که در آخرین روز معامله شده‌اند."],
            as_of=as_of,
            basket_size=size,
        )
    if row is None and uni is None:
        floor = min((r["median_value"] for r in rows if r.get("median_value")), default=None)
        reasons = [
            f"مدل فقط {size} نماد پرمعامله را بررسی می‌کند؛ برای نمادهای کم‌معامله‌تر دقت "
            "آن اثبات نشده و خرید/فروش درشت در آن‌ها قیمت را جابه‌جا می‌کند."
        ]
        if median_value and floor:
            reasons.append(
                f"میانهٔ ارزش معامله این نماد در ۲۰ روز اخیر {median_value / 1e10:.1f} میلیارد "
                f"تومان است؛ حداقل لازم برای ورود به فهرست {floor / 1e10:.1f} میلیارد تومان است."
            )
        return _none(
            "این نماد در فهرست پرمعامله‌های مدل نیست؛ تصمیمی برایش صادر نمی‌شود.",
            reasons,
            as_of=as_of,
            basket_size=size,
        )
    if row is None and uni is not None and uni.get("score") is None:
        if uni.get("halted"):
            why = "امروز متوقف بوده است."
        else:
            miss = "، ".join(MISSING_FA.get(m, m) for m in uni.get("missing", []))
            why = f"دادهٔ لازم برای محاسبهٔ امتیاز کامل نیست (کم: {miss})."
        return _none(f"امتیازی برای این نماد محاسبه نشد: {why}", as_of=as_of, basket_size=size)
    src = row if row is not None else uni
    assert src is not None
    in_basket = row is not None
    zone = src["zone"]
    score = src.get("score")
    base: dict[str, Any] = {
        "as_of": as_of,
        "rank": row["rank"] if row else None,
        "basket_size": size,
        "score": score,
        "gauge": None if score is None else score * 100,
        "in_basket": in_basket,
    }
    queue = src.get("queue_state")
    if queue in ("buy_queue", "sell_queue"):
        side = "خرید" if queue == "buy_queue" else "فروش"
        return _none(
            f"امروز تصمیمی نیست: نماد در صف {side} است و عملاً قابل معامله نیست.",
            [f"امتیاز {(score or 0) * 100:.0f} از ۱۰۰؛ جایگاه مدل فقط پس از خروج از صف معنا دارد."]
            if score is not None
            else [],
            **base,
        )
    if zone in ("excluded", "no_data") or zone is None:
        why = (
            "در صف فروش است و فروشنده بر خریدار غلبه دارد."
            if zone == "excluded"
            else "دادهٔ کافی برای محاسبهٔ امتیاز ندارد."
        )
        return _none(f"امروز تصمیمی نیست: {why}", **base)
    verdict = {"buy": "buy", "hold": "hold", "avoid": "sell"}[zone]
    if row is not None:
        reasons = [
            f"رتبهٔ {row['rank']} از {size} نماد پرمعامله؛ امتیاز ترکیبی "
            f"{(score or 0) * 100:.0f} از ۱۰۰ (۱۰۰ = بهترین)."
        ]
    else:
        pos = sum(1 for u in scored if u["score"] > (score or 0)) + 1
        reasons = [
            f"امتیاز ترکیبی {(score or 0) * 100:.0f} از ۱۰۰ (۱۰۰ = بهترین)؛ رتبهٔ {pos} "
            f"از {len(scored)} نماد دارای امتیاز."
        ]
    reasons += _signal_lines(src.get("signals") or {})
    bt, ht = doc.get("buy_top_frac"), doc.get("hold_top_frac")
    if bt and ht:
        reasons.append(
            f"قاعدهٔ مدل: {_pct(bt)} بالای جدول «خرید»، تا {_pct(ht)} «نگهداری» و بقیه "
            "«فروش/پرهیز» است."
        )
    if not in_basket:
        floor = get_engine_config().universe.min_median_value_20d
        mv = src.get("median_value")
        line = (
            "این نماد از ۱۰۰ سهم پرمعامله‌ای که آزمون‌های اعتبار روی آن‌ها انجام شده بیرون است؛ "
            "امتیازش با همان فرمول و نسبت به همان سهم‌ها محاسبه شده، اما دقت آن برای نماد "
            "کم‌معامله اثبات نشده است."
        )
        if mv:
            line += (
                f" میانهٔ ارزش معاملهٔ ۲۰ روزهٔ آن {mv / 1e10:.1f} میلیارد تومان است"
                f" (حداقل لازم برای ورود به آزمون‌ها {floor / 1e10:.1f} میلیارد تومان)."
            )
        reasons.append(line)
    elif not allowed:
        reasons.append(
            "آزمون‌های اعتبار مدل هنوز کامل نگذشته‌اند؛ این جایگاه یک رتبه‌بندی آماری است، "
            "نه توصیهٔ مطمئن."
        )
    head = {
        "buy": "در ناحیهٔ خرید مدل است.",
        "hold": "در ناحیهٔ نگهداری مدل است؛ خرید تازه توصیه نمی‌شود.",
        "sell": "در ناحیهٔ ضعیف مدل است؛ خرید نکنید و اگر دارید فروش را بسنجید.",
    }[verdict]
    if not in_basket:
        head += " (کم‌اعتبار: خارج از سبد پرمعامله)"
    advice = allowed and in_basket
    return DashDecision(
        verdict=verdict,
        label=LABEL[verdict],
        advice_allowed=advice,
        headline=head,
        reasons=reasons,
        summary=SUMMARY[verdict],
        signals=_signals(src.get("signals") or {}),
        holding=_holding(verdict, doc, advice),
        horizons=_horizons(doc, zone, src.get("signals") or {}),
        **base,
    )


@router.get("/instruments/{instrument_id}/dashboard", response_model=InstrumentDashboard)
def dashboard(instrument_id: int, session: SessionDep) -> InstrumentDashboard:
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    prices = list(
        session.scalars(
            select(PriceDaily)
            .where(PriceDaily.instrument_id == instrument_id)
            .order_by(PriceDaily.date.desc())
            .limit(40)
        )
    )
    flows = list(
        session.scalars(
            select(ClientTypeDaily)
            .where(ClientTypeDaily.instrument_id == instrument_id)
            .order_by(ClientTypeDaily.date.desc())
            .limit(10)
        )
    )
    price = _price(prices)
    sector = session.get(SectorName, inst.sector_code.zfill(2)) if inst.sector_code else None
    sh = session.scalars(
        select(ShareChange)
        .where(ShareChange.instrument_id == instrument_id)
        .order_by(ShareChange.date.desc())
        .limit(1)
    ).first()
    close = price.close if price else None
    fund = None
    nav = session.scalars(
        select(FundNav)
        .where(FundNav.instrument_id == instrument_id)
        .order_by(FundNav.date.desc())
        .limit(1)
    ).first()
    if nav is not None and nav.cancel_nav:
        fund = DashFund(
            nav_date=str(nav.date),
            nav=float(nav.cancel_nav),
            bubble=(close / float(nav.cancel_nav) - 1) if close else None,
        )
    vals = [float(r.value) for r in prices[:20] if r.value]
    events = list(
        session.scalars(
            select(CorporateEvent)
            .where(CorporateEvent.instrument_id == instrument_id)
            .order_by(CorporateEvent.announced_at.desc(), CorporateEvent.id.desc())
            .limit(40)
        )
    )
    changes = list(
        session.scalars(
            select(ShareChange)
            .where(ShareChange.instrument_id == instrument_id)
            .order_by(ShareChange.date.desc())
            .limit(4)
        )
    )
    tags = inst.tags or {}
    base_vol = _f(tags.get("base_volume"))
    ranges = DashRanges(
        week_min=_f(tags.get("week_min")),
        week_max=_f(tags.get("week_max")),
        year_min=_f(tags.get("year_min")),
        year_max=_f(tags.get("year_max")),
    )
    fa = None
    if inst.instrument_type == "stock":
        fa = fundamental_out(inst, close, sector.name if sector else None)
    return InstrumentDashboard(
        instrument=instrument_out(inst),
        isin=inst.isin,
        sector_name=sector.name if sector else None,
        board=inst.board,
        shares=int(sh.shares_new) if sh else None,
        market_cap=(int(sh.shares_new) * close) if sh and close else None,
        price=price,
        flow=_flow(flows),
        fund=fund,
        fundamental=fa,
        base_volume=base_vol,
        ranges=ranges if ranges.year_max else None,
        meeting=_meeting(events, to_tehran(utcnow()).date()),
        events=_events_out(events),
        share_changes=[
            DashShareChange(
                date=c.date,
                shares_old=int(c.shares_old),
                shares_new=int(c.shares_new),
                change_pct=(c.shares_new / c.shares_old - 1) if c.shares_old else None,
            )
            for c in changes
        ],
        decision=decide(inst, _ranking_doc(), statistics.median(vals) if vals else None),
        turning=turning_out(_turning_doc(), inst.id),
    )


def _turning_doc() -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, TURNING_KEY)
    except (FileNotFoundError, KeyError):
        return None
    except Exception:  # store unreachable: leave the card out instead of failing the page
        log.warning("turning document unreadable", exc_info=True)
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


def _turning_state(key: str, meta: dict[str, Any], h: dict[str, Any]) -> TurningState:
    return TurningState(
        key=key,
        title=meta.get("title", key),
        meaning=meta.get("meaning", ""),
        tone=h.get("tone", "none"),
        skewed=bool(h.get("skewed")),
        n=int(h.get("n") or 0),
        symbols=h.get("symbols"),
        episodes=h.get("episodes"),
        horizons=[
            TurningHorizon(horizon_days=d, **h[f"h{d}"]) for d in (20, 60, 120) if h.get(f"h{d}")
        ],
        mae60_median=h.get("mae60_median"),
        mae60_p10=h.get("mae60_p10"),
        halves_excess_120=[(b.get("h120") or {}).get("excess_mean") for b in h.get("halves", [])],
    )


def turning_out(doc: dict[str, Any] | None, instrument_id: int) -> DashTurning | None:
    """The symbol's part of the turning-point document; None when it has no state (under a year
    of history) or the document was never written."""
    if not doc:
        return None
    cur = (doc.get("symbols") or {}).get(str(instrument_id))
    if not cur or not cur.get("state"):
        return None
    meta = {m["key"]: m for m in doc.get("states", [])}
    hist = doc["history"]
    key = cur["state"]
    base = _turning_state(
        "all",
        {"title": "همهٔ نمادهای نقدشونده", "meaning": "میانگین بازار در همان روزها"},
        {**hist["base"], "tone": "none"},
    )
    return DashTurning(
        as_of=dt.date.fromisoformat(cur["date"]),
        state=_turning_state(key, meta.get(key, {}), hist["states"].get(key, {})),
        base=base,
        triggers=[
            TurningTrigger(
                when=t["when"],
                state=_turning_state(
                    t["to"], meta.get(t["to"], {}), hist["states"].get(t["to"], {})
                ),
            )
            for t in meta.get(key, {}).get("triggers", [])
        ],
        dd=cur.get("dd"),
        ret20=cur.get("ret20"),
        ret60=cur.get("ret60"),
        rsi=cur.get("rsi"),
        net5=cur.get("net5"),
        power5=cur.get("power5"),
        above_sma20=cur.get("above_sma20"),
        liquid=bool(cur.get("liquid")),
        market_bull=(doc.get("market") or {}).get("bull"),
        market_drawdown=(doc.get("market") or {}).get("drawdown"),
        round_trip_cost=float(doc["round_trip_cost"]),
        history_first=dt.date.fromisoformat(hist["first"]),
        history_last=dt.date.fromisoformat(hist["last"]),
        split_date=dt.date.fromisoformat(hist["split_date"]),
    )
