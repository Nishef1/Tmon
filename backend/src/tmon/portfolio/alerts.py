"""Findings -> stored alerts (once per condition, again only when it gets worse) -> delivery."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.portfolio.notify import ANSWERS, BOT_HOSTS, Message, deliver
from tmon.portfolio.watch import Finding, HoldingView, settings_for
from tmon.storage.models import Holding, Instrument, Portfolio, PortfolioAlert, PriceDaily

ADV_DAYS = 20


def record(
    session: Session, portfolio_id: int, findings: list[Finding], at: dt.datetime
) -> list[PortfolioAlert]:
    """Store the findings that are new or more severe than the last alert of the same key."""
    if not findings:
        return []
    keys = {f.key for f in findings}
    last: dict[str, int] = {}
    for key, sev in session.execute(
        select(PortfolioAlert.dedupe_key, func.max(PortfolioAlert.severity))
        .where(PortfolioAlert.portfolio_id == portfolio_id, PortfolioAlert.dedupe_key.in_(keys))
        .group_by(PortfolioAlert.dedupe_key)
    ):
        last[key] = int(sev)
    out: list[PortfolioAlert] = []
    for f in findings:
        if last.get(f.key, 0) >= f.severity:
            continue
        last[f.key] = f.severity
        a = PortfolioAlert(
            portfolio_id=portfolio_id,
            instrument_id=f.instrument_id,
            kind=f.kind,
            severity=f.severity,
            title=f.title,
            body=f.body,
            data={**f.data, "ask_exit": f.ask_exit},
            dedupe_key=f.key,
            created_at=at,
            delivered=[],
        )
        session.add(a)
        out.append(a)
    session.flush()
    return out


async def dispatch(
    session: Session, portfolio: Portfolio, alerts: list[PortfolioAlert], link_base: str | None
) -> None:
    """Push the alerts that reach the portfolio's push level to all of its channels."""
    cfg = settings_for(portfolio.settings)
    for a in alerts:
        if a.severity < int(cfg["push_min_severity"]) or not portfolio.channels:
            continue
        link = f"{link_base.rstrip('/')}/portfolios/{portfolio.id}" if link_base else None
        msg = Message(
            a.id,
            a.severity,
            f"{portfolio.name}: {a.title}",
            a.body,
            bool((a.data or {}).get("ask_exit")),
            link,
        )
        a.delivered = await deliver(list(portfolio.channels), msg)
    session.flush()


def answer(
    session: Session, alert_id: int, value: str, *, chat_id: str | None = None
) -> PortfolioAlert | None:
    """Store the owner's reply. From a messenger, the chat must be one of the portfolio's own."""
    if value not in ANSWERS:
        return None
    a = session.get(PortfolioAlert, alert_id)
    if a is None:
        return None
    if chat_id is not None:
        p = session.get(Portfolio, a.portfolio_id)
        chats = {
            str(c.get("chat_id")) for c in (p.channels if p else []) if c.get("type") in BOT_HOSTS
        }
        if chat_id not in chats:
            return None
    a.answer = value
    a.answered_at = dt.datetime.now(dt.UTC)
    session.flush()
    return a


def avg_daily_volume(session: Session, ids: list[int]) -> dict[int, float]:
    if not ids:
        return {}
    out: dict[int, float] = {}
    for iid in ids:
        vols = [
            float(v)
            for v in session.scalars(
                select(PriceDaily.volume)
                .where(PriceDaily.instrument_id == iid, PriceDaily.volume > 0)
                .order_by(PriceDaily.date.desc())
                .limit(ADV_DAYS)
            )
            if v is not None
        ]
        if vols:
            out[iid] = sum(vols) / len(vols)
    return out


def holding_views(session: Session) -> dict[int, tuple[Portfolio, list[HoldingView]]]:
    """Every portfolio with its holdings, ready for the detectors."""
    rows = session.execute(
        select(Portfolio, Holding, Instrument)
        .join(Holding, Holding.portfolio_id == Portfolio.id)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .where(Holding.shares > 0)
    ).all()
    adv = avg_daily_volume(session, sorted({h.instrument_id for _, h, _ in rows}))
    out: dict[int, tuple[Portfolio, list[HoldingView]]] = {}
    for p, h, i in rows:
        out.setdefault(p.id, (p, []))[1].append(
            HoldingView(
                holding_id=h.id,
                portfolio_id=p.id,
                instrument_id=i.id,
                ins_code=str(i.ins_code),
                symbol=i.symbol_fa,
                shares=h.shares,
                avg_price=h.avg_price,
                stop_price=h.stop_price,
                avg_daily_volume=adv.get(i.id),
            )
        )
    return out


def alert_out(a: PortfolioAlert, symbols: dict[int, str]) -> dict[str, Any]:
    return {
        "id": a.id,
        "instrument_id": a.instrument_id,
        "symbol": symbols.get(a.instrument_id or -1),
        "kind": a.kind,
        "severity": a.severity,
        "title": a.title,
        "body": a.body,
        "data": a.data or {},
        "ask_exit": bool((a.data or {}).get("ask_exit")),
        "created_at": a.created_at,
        "delivered": a.delivered or [],
        "answer": a.answer,
        "answered_at": a.answered_at,
    }
