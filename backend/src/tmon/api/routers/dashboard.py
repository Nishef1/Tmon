"""One symbol's full dashboard: price block, volume statistics, real/legal money flow, fund NAV and
the final decision (buy / hold / sell / none) with its reasons. Everything is read from stored
daily tables and the latest ranking document; nothing is estimated here."""

from __future__ import annotations

import json
import logging
import statistics
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import instrument_out
from tmon.api.schemas import (
    DashDecision,
    DashFlow,
    DashFund,
    DashPrice,
    InstrumentDashboard,
)
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.storage.models import (
    ClientTypeDaily,
    FundNav,
    Instrument,
    PriceDaily,
    SectorName,
    ShareChange,
)
from tmon.storage.objectstore import get_object_store
from tmon.tools.v2_ranking import KEY

log = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

SIGNAL_FA = {
    "ind_buy_power": "قدرت خریدار حقیقی",
    "rv_20": "آرام‌بودن نوسان ۲۰ روزه",
    "dist_high_52w": "نزدیکی به سقف یک‌ساله",
    "mom_12_1": "روند ۱۲ ماههٔ قیمت",
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
        close_change=(float(p.close) / prev - 1) if p.close and prev else None,
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


def _signal_lines(sig: dict[str, float]) -> list[str]:
    best = sorted(((k, v) for k, v in sig.items() if v is not None), key=lambda kv: -kv[1])
    if not best:
        return []
    top, low = best[0], best[-1]
    out = [f"قوی‌ترین نشانه: {SIGNAL_FA.get(top[0], top[0])} ({top[1] * 100:.0f} از ۱۰۰)."]
    if low[0] != top[0]:
        out.append(f"ضعیف‌ترین نشانه: {SIGNAL_FA.get(low[0], low[0])} ({low[1] * 100:.0f} از ۱۰۰).")
    return out


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
            f"قاعده: {_pct(bt)} برترِ رتبه‌بندی خرید، تا {_pct(ht)} برتر نگهداری و بقیه فروش/پرهیز."
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
            "هنوز آزمون‌های اعتبار مدل کامل نگذشته‌اند؛ این جایگاه یک رتبه‌بندی است، نه توصیهٔ مطمئن."
        )
    head = {
        "buy": "در ناحیهٔ خرید مدل است.",
        "hold": "در ناحیهٔ نگهداری مدل است؛ خرید تازه توصیه نمی‌شود.",
        "sell": "در ناحیهٔ ضعیف مدل است؛ خرید نکنید و اگر دارید فروش را بسنجید.",
    }[verdict]
    if not in_basket:
        head += " (کم‌اعتبار: خارج از سبد پرمعامله)"
    return DashDecision(
        verdict=verdict,
        label=LABEL[verdict],
        advice_allowed=allowed and in_basket,
        headline=head,
        reasons=reasons,
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
        decision=decide(inst, _ranking_doc(), statistics.median(vals) if vals else None),
    )
