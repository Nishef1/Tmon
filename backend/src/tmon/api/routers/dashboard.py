"""One symbol's full dashboard: price block, volume statistics, real/legal money flow, fund NAV and
the final decision (buy / hold / sell / none) with its reasons. Everything is read from stored
daily tables and the latest ranking document; nothing is estimated here."""

from __future__ import annotations

import datetime as dt
import logging
import statistics
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.entry import entry_doc, entry_out
from tmon.api.returns import day_change
from tmon.api.schemas import (
    DashDecision,
    DashDrivers,
    DashEvent,
    DashFlow,
    DashFund,
    DashFundamental,
    DashHolding,
    DashHorizon,
    DashMeeting,
    DashPeer,
    DashPeers,
    DashPrice,
    DashRanges,
    DashRide,
    DashShareChange,
    DashSignal,
    DashTurning,
    DriverMove,
    InstrumentDashboard,
    RideHistory,
    TurningHorizon,
    TurningState,
    TurningTrigger,
    TurningWarning,
    ZoneHorizon,
    instrument_out,
)
from tmon.api.technical import ta_doc, technical_out
from tmon.api.trade_state import market_days, trade_state
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import tehran_today
from tmon.domain.fundamentals import Fundamental, fundamental
from tmon.engine.verdict import (
    GRADE_FA,
    Verdict,
    final_verdict,
    state_meta,
    verdict_config,
    verdict_fields,
    zone_of,
)
from tmon.engine.verdict import fa_number as _n
from tmon.storage.models import (
    ClientTypeDaily,
    CorporateEvent,
    FundNav,
    Instrument,
    PriceDaily,
    SectorName,
    ShareChange,
)
from tmon.storage.objectstore import read_artifact
from tmon.tools.stock_drivers import KEY as DRIVERS_KEY
from tmon.tools.turning_points import KEY as TURNING_KEY
from tmon.tools.v2_ranking import KEY, MIN_RANK_DAYS

log = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

SIGNAL_FA = {
    "ind_buy_power": "قدرت خریدار حقیقی",
    "rv_20": "کم‌نوسان بودن قیمت",
    "dist_high_52w": "نزدیکی به سقف یک‌ساله",
    "mom_12_1": "روند ۱۲ ماههٔ قیمت",
}
SIGNAL_WHAT = {
    "ind_buy_power": "خریداران حقیقی چقدر بیشتر از فروشندگان حقیقی پول وارد سهم کرده‌اند",
    "rv_20": "قیمت در ۲۰ روز اخیر روزبه‌روز چقدر کم بالا و پایین رفته است؛ هرچه تکان‌های روزانه "
    "کوچک‌تر، امتیاز این بخش بیشتر. روزهای صف خرید یا فروش هم تکان کمی دارند و امتیاز را "
    "بالا می‌برند",
    "dist_high_52w": "قیمت امروز چقدر به بالاترین قیمت یک سال اخیر نزدیک است",
    "mom_12_1": "قیمت در یک سال گذشته (به‌جز ماه آخر) چقدر رشد کرده است",
}
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


def _volume_power(r: ClientTypeDaily) -> float | None:
    """Buyer power from shares per buyer over shares per seller. The latest day often comes from a
    source that has volumes and counts but no values; the two ratios agree because one day's buy and
    sell prices are close."""
    if not (r.buy_volume_i and r.buy_count_i and r.sell_volume_i and r.sell_count_i):
        return None
    return (float(r.buy_volume_i) / r.buy_count_i) / (float(r.sell_volume_i) / r.sell_count_i)


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
        power=(b0 / s0) if b0 and s0 else _volume_power(c),
        net_real_value=net_v,
        net_real_volume=net_q,
        avg10_per_capita_buy=ab,
        avg10_per_capita_sell=asl,
        avg10_power=(ab / asl) if ab and asl else None,
    )


def _ranking_doc() -> dict[str, Any] | None:
    return _stored_doc(KEY)


STAGE_FA = {
    "invitation": "دعوت به مجمع عادی سالیانه",
    "egm_invitation": "دعوت به مجمع فوق‌العاده",
    "ordinary_extraordinary_invitation": "دعوت به مجمع عادی به‌طور فوق‌العاده",
    "decisions": "تصمیمات مجمع",
    "decisions_summary": "خلاصهٔ تصمیمات مجمع",
    "dividend_schedule": "زمان‌بندی پرداخت سود",
    "board_proposal": "پیشنهاد هیئت‌مدیره برای افزایش سرمایه",
    "board_decision": "تصمیم هیئت‌مدیره دربارهٔ افزایش سرمایه",
    "auditor_opinion": "گزارش بازرس دربارهٔ افزایش سرمایه",
    "registered": "ثبت افزایش سرمایه",
    "meeting_cancelled": "لغو مجمع",
    "public_subscription_extended": "تمدید مهلت پذیره‌نویسی",
    "rights_deadline_extended": "تمدید مهلت حق‌تقدم",
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


SUMMARY = {
    "buy": "امتیازش در نیمهٔ بالای سهم‌های پرمعامله است و شواهد این ناحیه ثابت‌شده است.",
    "candidate": "امتیازش در نیمهٔ بالای سهم‌های پرمعامله است؛ نامزد خرید است، ولی شواهد این ناحیه "
    "هنوز ثابت نشده و این توصیه نیست.",
    "candidate_queue": "نامزد خرید است ولی در صف خرید است؛ خرید امروز عملاً ممکن نیست.",
    "wait": "امتیازش بالاست، اما وضعیت خود سهم در گذشته از بازار جلو نزده: فعلاً صبر کنید.",
    "with_market": "امتیازش در ناحیهٔ خرید نیست و عقب‌ماندگی‌اش هم ثابت نشده: همراه بازار بمانید.",
    "avoid": "امتیازش در ناحیهٔ پایین است و عقب‌ماندگی این ناحیه شواهد دارد: نخرید.",
    "wait_market": "بازار امروز می‌گوید سهام نخرید: صبر کنید.",
    "hold": "اگر دارید نگه دارید.",
    "consider_sell": "اگر دارید فروش را بسنجید.",
}


HORIZONS_FA = {
    1: ("D1", "یک روز (۱ روز معاملاتی)"),
    5: ("W1", "یک هفته (۵ روز معاملاتی)"),
    20: ("M1", "یک ماه (۲۰ روز معاملاتی)"),
    60: ("Q1", "سه ماه (۶۰ روز معاملاتی)"),
    120: ("H1", "شش ماه (۱۲۰ روز معاملاتی)"),
}
_ZONE_STATUS = {"ثابت‌شده": "proven", "احتمالی": "probable", "ثابت‌نشده": "unproven"}


def _by_horizon(doc: dict[str, Any], band: str | None) -> list[ZoneHorizon]:
    """The stock's zone at every horizon the ranking measured (docs/reports/horizon-profile-
    2026-11.md). Nothing for the middle band: it has no zone record to show."""
    if band not in ("candidate", "avoid"):
        return []
    h_verdict = int(verdict_config(doc)["horizon_days"])
    out: list[ZoneHorizon] = []
    for key in sorted((doc.get("zones") or {}), key=int):
        h = int(key)
        z = zone_of(doc, band, h)
        if not z or h not in HORIZONS_FA or z.get("net") is None:
            continue
        loss = z["net_h1"] < 0 and z["net_h2"] < 0
        out.append(
            ZoneHorizon(
                days=h,
                label=HORIZONS_FA[h][1].split(" (")[0],
                net=z["net"],
                net_h1=z["net_h1"],
                net_h2=z["net_h2"],
                windows=int(doc["zones"][key].get("days", 0)) // h,
                status="loss" if loss else _ZONE_STATUS.get(z.get("grade", ""), "unproven"),
                verdict_horizon=h == h_verdict,
            )
        )
    return out


def decision_fields(d: DashDecision) -> dict[str, Any]:
    """The same fields from a symbol page decision (screener and search rows)."""
    return {
        k: getattr(d, k)
        for k in (
            "code",
            "holder_code",
            "holder_verdict",
            "holder_label",
            "band",
            "grade",
            "grade_label",
        )
    }


def _verdict_card(doc: dict[str, Any], v: Verdict, sig: dict[str, float]) -> DashHorizon | None:
    """The one horizon card the page shows: the verdict horizon, its zone record, the signals."""
    cost = doc.get("round_trip_cost")
    h = int(verdict_config(doc)["horizon_days"])
    if cost is None or h not in HORIZONS_FA:
        return None
    key, label = HORIZONS_FA[h]
    ev: dict[str, Any] = next(
        (e for e in doc.get("evidence", []) if e.get("horizon_days") == h), {}
    )
    z = zone_of(doc, "avoid" if v.band == "avoid" else "candidate", h) or {}
    net = z.get("net")
    reasons = [
        "اعداد این صفحه از روزهای معاملاتی گذشته به دست آمده‌اند: در هر روز، بین ۱۰۰ سهم پرنقد "
        "(بدون سهم‌های قفل صف خرید که خریدنی نیستند) سهم‌ها را به ده گروه امتیاز تقسیم کرده‌ایم "
        f"و بازدهی {label} بعد هر گروه را با میانگین همان ۱۰۰ سهم سنجیده‌ایم."
    ]
    for k, name in SIGNAL_FA.items():
        s_ev = (ev.get("signals") or {}).get(k)
        if not s_ev or s_ev.get("ic") is None or sig.get(k) is None:
            continue
        solid = (s_ev.get("t") or 0) >= 2.0
        reasons.append(
            f"{name}: "
            + (
                "برای این بازه در گذشته واقعاً به پیش‌بینی کمک کرده است"
                if solid
                else "برای این بازه به‌تنهایی در گذشته کمکی به پیش‌بینی نکرده، ولی در امتیاز ترکیبی "
                "مثل بقیه حساب می‌شود"
            )
            + f" (برای کارشناس: IC {_n(s_ev['ic'], 3, True)}، t {_n(s_ev.get('t') or 0)})."
        )
    return DashHorizon(
        key=key,
        label=label,
        days=h,
        verdict=v.key,
        verdict_label=v.label,
        weak=False,
        vetoed=v.vetoed,
        headline=v.headline,
        reasons=reasons,
        top_excess=None if net is None or v.band == "avoid" else net + float(cost),
        cost=float(cost),
        net_excess=net,
        ic=ev.get("ic"),
        ic_t=ev.get("ic_t"),
    )


def _holding(v: Verdict, doc: dict[str, Any], advice: bool) -> DashHolding:
    h = int(verdict_config(doc)["horizon_days"])
    z = zone_of(doc, "avoid" if v.band == "avoid" else "candidate", h) or {}
    lines = [
        f"این ناحیه برای نگه‌داشتن سهم حدود {h} روز کاری بورس (حدود سه ماه) سنجیده شده، "
        "نه برای خرید و فروش در همان روز؛ برای نوسان‌گیری روزانه آزمایش نشده است."
    ]
    if v.code in ("buy", "candidate", "candidate_queue"):
        if z.get("net") is not None:
            lines.append(
                "سود اضافهٔ بالا میانگین گذشته است، نه قول؛ بعضی از سهم‌های این ناحیه زیان داده‌اند."
            )
        lines.append(
            "زمان فروش: سهم را به یک پرتفوی اضافه کنید تا هشدار خروج دقیقه‌ای (صف فروش، عرضهٔ "
            "سنگین، خروج پول حقیقی، خبر بد) بگیرید. فروش ساده از روی این صفحه گفته نمی‌شود؛ "
            "فقط قاعدهٔ جابه‌جایی پرتفوی و هشدارهای خروج می‌گویند «بفروش»."
        )
        lines.append(
            "اگر سهم صف خرید است، خرید عملاً ممکن نیست؛ با سفارش درشت و بدون برنامه وارد صف نشوید."
        )
    elif v.code in ("with_market", "wait", "wait_market"):
        lines.append(
            "اگر سهم را دارید نگه دارید و هشدارهای پرتفوی را دنبال کنید؛ خرید تازه وقتی منطقی "
            "است که سهم نامزد خرید شود."
        )
    else:
        lines.append("خرید تازه نکنید. اگر دارید، فروش را بسنجید.")
    if not advice:
        lines.append("این‌ها آمار گذشته‌اند و هنوز توصیهٔ مطمئن نیستند (همهٔ آزمون‌ها تمام نشده).")
    return DashHolding(horizon_days=h, expected_excess=z.get("net"), lines=lines)


def _zone_from(top_frac: object) -> float | None:
    """Gauge value where the zone of the top ``top_frac`` share starts (1 - frac, on 0-100)."""
    return (
        None if not isinstance(top_frac, int | float) else round((1.0 - float(top_frac)) * 100, 1)
    )


def decide(
    inst: Instrument,
    doc: dict[str, Any] | None,
    median_value: float | None,
    turn_doc: dict[str, Any] | None = None,
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
                f"در یک روز معمولی از ۲۰ روز اخیر حدود {median_value / 1e10:.1f} میلیارد تومان از "
                f"این سهم معامله شده؛ حداقل لازم برای ورود به فهرست {floor / 1e10:.1f} "
                "میلیارد تومان است."
            )
        return _none(
            "این نماد در فهرست پرمعامله‌های مدل نیست؛ تصمیمی برایش صادر نمی‌شود.",
            reasons,
            as_of=as_of,
            basket_size=size,
        )
    if row is None and uni is not None and uni.get("score") is None:
        if uni.get("too_new"):
            n, need = int(uni.get("history_days") or 0), MIN_RANK_DAYS
            return _none(
                "امتیازی برای این نماد محاسبه نشد: نماد تازه وارد بازار شده است "
                f"و فقط {n} روز معامله دارد.",
                [
                    f"مدل دست‌کم {need} روز معاملاتی (حدود یک سال) سابقه می‌خواهد؛ روند ۱۲ ماهه و "
                    "فاصله از سقف یک‌ساله بدون آن معنا ندارند و رتبه‌بندی با دادهٔ ناقص "
                    "گمراه‌کننده است.",
                ],
                as_of=as_of,
                basket_size=size,
            )
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
    # the position among the stocks the home list shows (liquid, no funds, nothing stuck in a sell
    # queue), not the raw rank over every symbol
    in_rows = [
        r
        for r in rows
        if r.get("in_basket", True)
        and not str(r.get("name") or "").startswith("صندوق")
        and r.get("queue_state") != "sell_queue"
    ]
    basket_rank = 1 + sum(1 for r in in_rows if r["rank"] < row["rank"]) if row else None
    base: dict[str, Any] = {
        "as_of": as_of,
        "rank": basket_rank,
        "basket_size": len(in_rows) or size,
        "score": score,
        "gauge": None if score is None else score * 100,
        "in_basket": in_basket,
        "zone_hold_from": _zone_from(doc.get("hold_top_frac")),
        "zone_buy_from": _zone_from(doc.get("buy_top_frac")),
    }
    queue = src.get("queue_state")
    base["queue_state"] = queue
    if queue == "sell_queue":
        return _none(
            "امروز تصمیمی نیست: نماد در صف فروش است و عملاً قابل معامله نیست.",
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
    v = final_verdict(doc, src, turn_doc, inst.id)
    if v is None:
        return _none("رتبه‌بندی مدل با قاعدهٔ تازه هنوز محاسبه نشده است.", **base)
    if row is not None:
        reasons = [
            f"امتیاز ترکیبی {(score or 0) * 100:.0f} از ۱۰۰ یعنی از حدود "
            f"{(score or 0) * 100:.0f}٪ نمادهای امتیازدار بازار بهتر است؛ در فهرست امروز "
            f"({len(in_rows)} سهم پرمعامله) رتبهٔ {basket_rank} را دارد."
        ]
    else:
        pos = sum(1 for u in scored if u["score"] > (score or 0)) + 1
        reasons = [
            f"امتیاز ترکیبی {(score or 0) * 100:.0f} از ۱۰۰ (۱۰۰ = بهترین)؛ رتبهٔ {pos} "
            f"از {len(scored)} نماد دارای امتیاز."
        ]
    if queue == "buy_queue":
        reasons.append(
            "در صف خرید است: سهم قوی است ولی سفارش خرید امروز ممکن است پر نشود؛ "
            "به قیمت سقف صف نخرید مگر بخواهید در نوبت بمانید."
        )
    vc = verdict_config(doc)
    where = {"candidate": "نیمهٔ بالا", "middle": "میانه", "avoid": "ناحیهٔ پایین"}[v.band]
    reasons.append(
        f"قاعدهٔ کار: بین ۱۰۰ سهم پرمعامله، {vc['candidate_top_frac'] * 100:.0f}٪ بالا "
        f"«نامزد خرید»، {vc['avoid_bottom_frac'] * 100:.0f}٪ پایین «ناحیهٔ پایین» و بقیه "
        "«میانه» است؛ این سهم در "
        f"«{where}» است"
        + (
            f" (جایگاه {round((src.get('basket_pct') or 0) * 100)} از ۱۰۰)."
            if src.get("basket_pct") is not None
            else "."
        )
    )
    if not in_basket:
        floor = get_engine_config().universe.min_median_value_20d
        mv = src.get("median_value")
        line = (
            "این نماد از ۱۰۰ سهم پرمعامله‌ای که آزمون‌های اعتبار روی آن‌ها انجام شده جزو آن‌ها نیست؛ "
            "امتیازش با همان فرمول و نسبت به همان سهم‌ها محاسبه شده، اما دقت آن برای نماد "
            "کم‌معامله اثبات نشده است."
        )
        if mv:
            line += (
                f" در یک روز معمولی حدود {mv / 1e10:.1f} میلیارد تومان از آن معامله می‌شود"
                f" (حداقل لازم برای ورود به آزمون‌ها {floor / 1e10:.1f} میلیارد تومان)."
            )
        reasons.append(line)
    elif not allowed:
        reasons.append(
            "آزمون‌های اعتبار مدل هنوز کامل نگذشته‌اند؛ این جایگاه یک رتبه‌بندی آماری است، "
            "نه توصیهٔ مطمئن."
        )
    card = _verdict_card(doc, v, src.get("signals") or {})
    head = v.headline
    if not in_basket:
        head += " (با احتیاط: این سهم کم‌معامله است و مدل روی آن آزموده نشده)"
    advice = allowed and in_basket
    return DashDecision(
        verdict=v.key,
        label=v.label,
        code=v.code,
        holder_code=v.holder_code,
        holder_verdict=v.holder_key,
        holder_label=v.holder_label,
        holder_headline=v.holder_headline,
        band=v.band,
        grade=v.grade,
        grade_label=None if v.grade is None else GRADE_FA[v.grade],
        market_warning=v.market_warning,
        weak=v.band == "avoid" and v.code != "avoid",
        advice_allowed=advice,
        headline=head,
        reasons=reasons,
        summary=SUMMARY[v.code],
        signals=_signals(src.get("signals") or {}),
        holding=_holding(v, doc, advice),
        horizons=[] if card is None else [card],
        by_horizon=_by_horizon(doc, v.band),
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
    rank_doc, turn_doc = _ranking_doc(), _turning_doc()
    drv_doc = _stored_doc(DRIVERS_KEY) if inst.instrument_type == "stock" else None
    fa = None
    if inst.instrument_type == "stock":
        fa = fundamental_out(inst, close, sector.name if sector else None)
    state, last_trade, idle_days = trade_state(session, instrument_id, market_days(session))
    return InstrumentDashboard(
        instrument=instrument_out(inst),
        trade_state=state,
        last_trade_date=last_trade,
        idle_days=idle_days,
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
        meeting=_meeting(events, tehran_today()),
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
        decision=decide(inst, rank_doc, statistics.median(vals) if vals else None, turn_doc),
        turning=turning_out(turn_doc, inst.id),
        peers=peers_out(session, inst, sector.name if sector else None, rank_doc, turn_doc),
        drivers=drivers_out(drv_doc, inst.id) if inst.instrument_type == "stock" else None,
        technical=technical_out(ta_doc(), inst.id, _beta(drv_doc, inst.id)),
        entry=entry_out(entry_doc(), inst.id),
    )


def _beta(doc: dict[str, Any] | None, instrument_id: int) -> float | None:
    x = ((doc or {}).get("symbols") or {}).get(str(instrument_id)) or {}
    b = x.get("beta_index")
    return float(b) if b is not None else None


def _stored_doc(key: str) -> dict[str, Any] | None:
    try:
        return read_artifact(key)
    except Exception:  # store unreachable: leave the card out instead of failing the page
        log.warning("%s unreadable", key, exc_info=True)
        return None


def _turning_doc() -> dict[str, Any] | None:
    return _stored_doc(TURNING_KEY)


DRIVER_WEAK = 0.1  # |extra move per 1% dollar| below this reads as "no clear tie"
DRIVER_CORR = 0.3  # a copper or Brent correlation worth a sentence


def _driver_lines(
    x: dict[str, Any], moves: list[DriverMove], days: int, mkt: dict[str, Any] | None = None
) -> list[str]:
    out: list[str] = []
    bi, r2 = x.get("beta_index"), x.get("r2")
    if bi is not None and r2 is not None:
        pace = (
            "تندتر از بازار بالا و پایین می‌رود"
            if bi > 1.2
            else "کمتر از بازار بالا و پایین می‌رود"
            if bi < 0.8
            else "تقریباً هم‌اندازهٔ بازار حرکت می‌کند"
        )
        out.append(
            f"وقتی شاخص کل بورس ۱۰٪ بالا یا پایین رفته، این سهم معمولاً حدود "
            f"{_n(abs(bi) * 10, 0)}٪ جابه‌جا شده؛ یعنی {pace}. حرکت شاخص و دلار روی هم حدود "
            f"{_n(max(r2, 0) * 100, 0)}٪ از نوسان هفتگی این سهم را توضیح می‌دهد و بقیه به خود "
            f"شرکت و خبرهایش برمی‌گردد (سه سال اخیر، {x.get('weeks')} هفته)."
        )
    bu = x.get("beta_usd")
    if bu is not None:
        if bu >= DRIVER_WEAK:
            out.append(
                f"وقتی دلار آزاد ۱۰٪ گران شده، این سهم جدا از حرکت کل بازار حدود "
                f"{_n(bu * 10, 1)}٪ بیشتر بالا رفته؛ یعنی از گرانی دلار سود برده (سهم «دلاری»)."
            )
        elif bu <= -DRIVER_WEAK:
            out.append(
                f"وقتی دلار آزاد ۱۰٪ گران شده، این سهم جدا از حرکت کل بازار حدود "
                f"{_n(-bu * 10, 1)}٪ کمتر بالا رفته؛ یعنی گرانی دلار به نفعش نبوده."
            )
        else:
            out.append("گرانی یا ارزانی دلار، جدا از حرکت کل بازار، اثر روشنی روی این سهم نداشته.")
    for key, what in (("corr_copper", "قیمت جهانی مس"), ("corr_brent", "قیمت جهانی نفت برنت")):
        c = x.get(key)
        if c is not None and abs(c) >= DRIVER_CORR:
            way = "هم‌جهت" if c > 0 else "خلاف جهت"
            out.append(
                f"ماه‌به‌ماه بیشتر وقت‌ها {way} با {what} حرکت کرده (همبستگی {_n(c, 2, True)}؛ "
                "۰ یعنی بی‌ربط و ۱ یعنی کاملاً هم‌جهت)."
            )
    pc, yrs = x.get("usd_pctl"), x.get("usd_years")
    if pc is not None and yrs:
        level = "گران" if pc >= 0.8 else "ارزان" if pc <= 0.2 else "میانه"
        out.append(
            f"قیمت این سهم به دلار از {_n(pc * 100, 0)}٪ روزهای {_n(yrs, 0)} سال گذشته بالاتر "
            f"است (به دلار نسبتاً {level})؛ "
            f"{_n(abs(x.get('usd_from_peak') or 0) * 100, 0)}٪ زیر گران‌ترین روزش. این فقط برای "
            "مقایسه است: در آزمون ما «ارزان به دلار» به‌تنهایی سهم بهتر را جدا نکرد."
        )
    bad = [m for m in moves if m.kind in ("war", "sanction", "unrest")]
    if len(bad) >= 3:
        beat = sum(1 for m in bad if m.stock > m.index)
        out.append(
            f"پس از {len(bad)} رویداد بد (جنگ، تحریم، اعتراض)، این سهم در {days} روز معاملاتی بعد "
            f"{beat} بار از شاخص کل بهتر و {len(bad) - beat} بار بدتر بوده."
        )
    mkt = mkt or {}
    if int(mkt.get("n") or 0) >= 3 and mkt.get("usd_n"):
        out.append(
            f"در کل بازار، {days} روز معاملاتی پس از {_n(mkt['n'], 0)} خبر بد جدا از هم، دلار آزاد "
            f"{_n(mkt['usd_up'], 0)} بار از {_n(mkt['usd_n'], 0)} بار و شاخص کل "
            f"{_n(mkt['index_up'], 0)} بار از {_n(mkt['n'], 0)} بار بالاتر بود؛ "
            "یعنی خبر بد در بورس تهران همیشه به معنای ریزش شاخص نبوده است."
        )
    return out


def drivers_out(doc: dict[str, Any] | None, instrument_id: int) -> DashDrivers | None:
    """The stock's part of the drivers document with plain sentences; None when it has none."""
    if not doc:
        return None
    x = (doc.get("symbols") or {}).get(str(instrument_id))
    if not x:
        return None
    events = doc.get("events") or []
    days = int(doc.get("event_days") or 20)
    moves = [
        DriverMove(
            date=events[k]["date"],
            kind=events[k]["kind"],
            title=events[k]["title_fa"],
            source=events[k]["source"],
            stock=st,
            index=ix,
        )
        for k, st, ix in x.get("moves", [])
        if k < len(events)
    ]
    fields = {k: x.get(k) for k in DashDrivers.model_fields if k in x and k != "moves"}
    return DashDrivers(
        as_of=doc["as_of"],
        event_days=days,
        moves=moves[::-1],
        lines=_driver_lines(x, moves, days, doc.get("market_bad")),
        **fields,
    )


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


def _warning(w: dict[str, Any] | None, cur: dict[str, Any]) -> TurningWarning | None:
    if not w or not cur.get("warn_date"):
        return None
    return TurningWarning(
        title=w["title"],
        meaning=w["meaning"],
        date=dt.date.fromisoformat(cur["warn_date"]),
        days_ago=int(cur.get("warn_ago") or 0),
        recent_days=int(w.get("recent_days") or 20),
        n=int(w.get("n") or 0),
        symbols=w.get("symbols"),
        horizons=[
            TurningHorizon(horizon_days=d, **w[f"h{d}"]) for d in (20, 60, 120) if w.get(f"h{d}")
        ],
        halves_excess_60=[(b.get("h60") or {}).get("excess_mean") for b in w.get("halves", [])],
    )


def _ride(meta: dict[str, Any] | None, cur: dict[str, Any] | None) -> DashRide | None:
    if not meta or not cur:
        return None
    h = meta.get("history") or {}
    return DashRide(
        **cur,
        near_high=meta["near_high"],
        trail=meta["trail"],
        max_hold_days=meta["max_hold_days"],
        grade=meta["grade"],
        history_years=meta["history_years"],
        history=RideHistory(**h) if h.get("n") else None,
    )


def turning_out(doc: dict[str, Any] | None, instrument_id: int) -> DashTurning | None:
    """The symbol's part of the turning-point document; None when it has no state (under a year
    of history) or the document was never written."""
    if not doc:
        return None
    cur = (doc.get("symbols") or {}).get(str(instrument_id))
    if not cur or not cur.get("state"):
        return None
    meta = state_meta(doc)
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
        warning=_warning(doc.get("warning"), cur),
        ride=_ride(doc.get("trend_ride"), cur.get("ride")),
    )


PEERS_SHOWN = 6


def rank_peers(
    peers: list[Instrument],
    self_id: int,
    rank_doc: dict[str, Any] | None,
    turn_doc: dict[str, Any] | None,
    closes: dict[int, float],
) -> DashPeers:
    """Order the stocks of one group by composite score (unscored last) and keep the best few,
    always including the symbol itself."""
    uni = {u["id"]: u for u in (rank_doc or {}).get("universe", [])}
    basket = {r["symbol"] for r in (rank_doc or {}).get("rows", [])}
    states = (turn_doc or {}).get("symbols") or {}
    titles = {k: m["title"] for k, m in state_meta(turn_doc).items()}
    tones = ((turn_doc or {}).get("history") or {}).get("states") or {}
    items: list[DashPeer] = []
    for p in peers:
        if p.id != self_id and p.id not in uni and str(p.id) not in states:
            continue  # not traded lately: neither ranked nor given a state
        u = uni.get(p.id) or {}
        score = u.get("score")
        v = final_verdict(rank_doc, u, turn_doc, p.id) if rank_doc and score is not None else None
        st = states.get(str(p.id)) or {}
        key = st.get("state")
        eps = _f((p.tags or {}).get("eps"))
        close = closes.get(p.id)
        items.append(
            DashPeer(
                id=p.id,
                symbol=p.symbol_fa,
                name=p.name_fa,
                score=None if score is None else score * 100,
                verdict=v.key if v else "none",
                **verdict_fields(v),
                in_basket=p.symbol_fa in basket,
                pe=close / eps if eps and eps > 0 and close else None,
                ret60=st.get("ret60"),
                dd=st.get("dd"),
                turning_key=key,
                turning_title=titles.get(key) if key else None,
                turning_tone=(tones.get(key) or {}).get("tone") if key else None,
                is_self=p.id == self_id,
            )
        )
    items.sort(key=lambda x: (x.score is None, -(x.score or 0), x.symbol))
    scored = [x for x in items if x.score is not None]
    me = next((x for x in items if x.is_self), None)
    shown = items[:PEERS_SHOWN]
    if me is not None and me not in shown:
        shown.append(me)
    return DashPeers(
        position=scored.index(me) + 1 if me is not None and me.score is not None else None,
        scored=len(scored),
        total=len(items),
        items=shown,
    )


def peers_out(
    session: Session,
    inst: Instrument,
    sector_name: str | None,
    rank_doc: dict[str, Any] | None,
    turn_doc: dict[str, Any] | None,
) -> DashPeers | None:
    """The symbol among the stocks of its industry group; None for non-stocks or a lone stock."""
    if inst.instrument_type != "stock" or not inst.sector_code:
        return None
    peers = list(
        session.scalars(
            select(Instrument).where(
                Instrument.sector_code == inst.sector_code,
                Instrument.instrument_type == "stock",
                Instrument.delisted_at.is_(None),
            )
        )
    )
    if len(peers) < 2:
        return None
    closes: dict[int, float] = {}
    as_of = (rank_doc or {}).get("as_of")
    if as_of:
        rows = session.execute(
            select(PriceDaily.instrument_id, PriceDaily.close).where(
                PriceDaily.date == dt.date.fromisoformat(as_of),
                PriceDaily.instrument_id.in_([p.id for p in peers]),
            )
        )
        closes = {i: float(c) for i, c in rows if c}
    out = rank_peers(peers, inst.id, rank_doc, turn_doc, closes)
    if out.total < 2:
        return None
    out.sector_name = sector_name
    return out
