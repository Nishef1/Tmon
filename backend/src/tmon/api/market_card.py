"""The market card (ADR 0004 sections 3 and 7): how much of the capital the model keeps in equities
today and why, and, when that share is positive, the most traded equity funds with their NAV
premium. The funds are shown as the way to hold the market itself; they get no verdict and no
past test (``untested``). Used by the ranking page, the home page and the portfolio advice."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.schemas import MarketCard, MarketFund
from tmon.core.engine_config import get_engine_config
from tmon.storage.models import FundNav, Instrument, PriceDaily

FUNDS_SHOWN = 5
FUNDS_NOTE = (
    "آزموده نشده: برای صندوق‌ها هیچ حکم و آزمون گذشته‌ای نداریم. «صندوق‌های سهامی پرمعامله» فقط "
    "راهی ساده برای داشتن خود بازار است؛ پیش از خرید، قیمت را با ارزش خالص دارایی (NAV) بسنجید: "
    "قیمتی بسیار بالاتر از NAV یعنی حباب."
)


def market_reasons(exposure: dict[str, Any] | None) -> list[str]:
    """Why the share is what it is, in plain words, from the four exposure factors."""
    if not exposure or exposure.get("exposure") is None:
        return []
    cfg = get_engine_config().v2.exposure
    out: list[str] = []
    trend, mom, stress = exposure.get("trend"), exposure.get("abs_mom"), exposure.get("stress")
    if trend is not None:
        out.append(
            f"روند: شاخص هم‌وزن {'بالای' if trend >= 0.5 else 'زیر'} میانگین "
            f"{cfg.trend_window_days} روزهٔ خودش است."
        )
    if mom is not None:
        out.append(
            f"مومنتوم مطلق: بازدهی {cfg.abs_mom_days} روزهٔ شاخص "
            f"{'بیشتر از' if mom >= 0.5 else 'کمتر از'} بازدهی اوراق خزانه در همان مدت است."
        )
    if stress is not None:
        share = round((1.0 - float(stress)) * 100, 1)
        out.append(f"فشار صف فروش: میانگین ۵ روز اخیر، {share}٪ نمادها در صف فروش بوده‌اند.")
    return out


def market_funds(session: Session) -> list[MarketFund]:
    """The most traded equity funds on the last stored day, with the premium of the last price over
    the redemption NAV where the fund's NAV is stored (``None`` otherwise)."""
    day = session.scalar(select(func.max(PriceDaily.date)))
    if day is None:
        return []
    rows = session.execute(
        select(Instrument, PriceDaily)
        .join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
        .where(
            PriceDaily.date == day,
            Instrument.instrument_type == "etf_equity",
            PriceDaily.value.is_not(None),
        )
        .order_by(PriceDaily.value.desc())
        .limit(FUNDS_SHOWN)
    ).all()
    out: list[MarketFund] = []
    for ins, p in rows:
        nav = session.execute(
            select(FundNav.cancel_nav, FundNav.date)
            .where(FundNav.instrument_id == ins.id, FundNav.cancel_nav.is_not(None))
            .order_by(FundNav.date.desc())
            .limit(1)
        ).first()
        close = None if p.close is None else float(p.close)
        nav_value = None if nav is None or nav[0] is None else float(nav[0])
        out.append(
            MarketFund(
                instrument_id=ins.id,
                symbol=ins.symbol_fa,
                name=ins.name_fa,
                value=float(p.value or 0),
                close=close,
                nav=nav_value,
                nav_date=None if nav is None else nav[1],
                premium=(close / nav_value - 1.0) if close and nav_value else None,
            )
        )
    return out


def market_card(session: Session, doc: dict[str, Any]) -> MarketCard | None:
    """``None`` when the ranking document has no exposure."""
    exp = doc.get("exposure") or {}
    share = exp.get("exposure")
    if share is None:
        return None
    positive = float(share) > 1e-9
    return MarketCard(
        exposure=float(share),
        date=doc.get("exposure_date"),
        positive=positive,
        reasons=market_reasons(exp),
        funds=market_funds(session) if positive else [],
        funds_note=FUNDS_NOTE if positive else "",
    )
