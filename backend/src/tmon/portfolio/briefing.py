"""The pre-open (and hourly) review of every portfolio: news, Codal, model, one verdict per holding.

Inputs, all from the database the collectors keep fresh (the monitor pulls news and Codal right
before the pre-open run):

* news of the last day that name the holding (LLM-extracted ``news_events`` symbols, or the symbol
  in the title), plus heavy market-wide events (magnitude >= 4, no symbol: war, FX, rates, oil...);
* Codal letters of the holding since the last day;
* the advice of :mod:`tmon.portfolio.advice` (model score, zone, queue, stop, P&L).

With ``TMON_LLM_API_KEY`` set the evidence is judged by Claude (structured output, one verdict per
holding with confidence and reasons, in Persian). Without it a transparent rule does the same:
exit on a hit stop / sell queue / strongly negative news or letter, reduce on a weak score with
negative news, add on a strong score with positive news, hold otherwise. Either way an exit or
reduce verdict becomes an alert that asks the owner.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.portfolio.advice import advise
from tmon.portfolio.watch import INFO, URGENT, WARN, Finding
from tmon.storage.models import (
    CodalLetter,
    Holding,
    NewsEvent,
    NewsRaw,
    Portfolio,
    PortfolioBriefing,
)

log = logging.getLogger(__name__)

LOOKBACK = dt.timedelta(hours=24)
BAD_WORDS = ("زیان", "توقف", "تعلیق", "تعدیل منفی", "کاهش", "ممنوع", "عرضه", "اصلاحیه")
Action = Literal["exit", "reduce", "hold", "add"]
ACTION_FA = {"exit": "خروج", "reduce": "کاهش نصف", "hold": "نگه‌داری", "add": "افزایش"}


class HoldingCall(BaseModel):
    symbol: str
    action: Action
    confidence: float = Field(ge=0, le=1)
    reasons_fa: list[str] = Field(default_factory=list)


class BriefingCall(BaseModel):
    market_fa: str = Field(description="یک تا سه جمله دربارهٔ وضعیت کلی بازار امروز")
    holdings: list[HoldingCall]


SYSTEM = (
    "You are a cautious risk officer for a Tehran Stock Exchange portfolio. For each holding you "
    "get the quant model's view and the last day's news and Codal disclosures. Decide exit, "
    "reduce, hold or add for today's session. Prefer protecting capital: material negative news "
    "(losses, halts, negative EPS revisions, large supply, sanctions on the sector) means exit "
    "or reduce. Do not invent facts; when evidence is thin, say hold with low confidence. Write "
    "reasons in Persian, short and concrete, citing the evidence."
)


def _news(session: Session, since: dt.datetime) -> list[tuple[NewsRaw, NewsEvent | None]]:
    rows = session.execute(
        select(NewsRaw, NewsEvent)
        .outerjoin(NewsEvent, NewsEvent.news_id == NewsRaw.id)
        .where(NewsRaw.published_at >= since)
        .order_by(NewsRaw.published_at.desc())
        .limit(400)
    ).all()
    return [(n, e) for n, e in rows]


def _evidence(
    session: Session, holdings: list[dict[str, Any]], since: dt.datetime
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    news = _news(session, since)
    market = [
        {"title": n.title, "direction": e.direction, "magnitude": e.magnitude, "type": e.event_type}
        for n, e in news
        if e is not None and not e.symbols and e.magnitude >= 4
    ][:8]
    per: dict[int, dict[str, Any]] = {}
    for h in holdings:
        sym = str(h["symbol"])
        items = []
        for n, e in news:
            if (e is not None and sym in (e.symbols or [])) or f" {sym} " in f" {n.title} ":
                items.append(
                    {
                        "title": n.title,
                        "direction": e.direction if e else None,
                        "magnitude": e.magnitude if e else None,
                        "summary": (n.summary or "")[:300],
                    }
                )
        letters = [
            {"title": c.title, "url": c.url, "bad": any(w in c.title for w in BAD_WORDS)}
            for c in session.scalars(
                select(CodalLetter)
                .where(
                    CodalLetter.instrument_id == h["instrument_id"],
                    CodalLetter.published_at >= since,
                )
                .order_by(CodalLetter.published_at.desc())
                .limit(10)
            )
        ]
        per[int(h["instrument_id"])] = {"news": items[:8], "codal": letters}
    return per, market


def rule_call(h: dict[str, Any], ev: dict[str, Any]) -> HoldingCall:
    """The verdict without an LLM, from the same evidence."""
    neg = [n for n in ev["news"] if (n["direction"] or 0) < 0]
    pos = [n for n in ev["news"] if (n["direction"] or 0) > 0]
    strong_neg = [n for n in neg if (n["magnitude"] or 0) >= 3]
    bad_letters = [c for c in ev["codal"] if c["bad"]]
    reasons = list(h.get("reasons") or [])
    reasons += [f"خبر منفی: {n['title']}" for n in neg[:3]]
    reasons += [f"اطلاعیهٔ کدال: {c['title']}" for c in bad_letters[:3]]
    v = h["verdict"]
    if v == "sell" or strong_neg or (bad_letters and v == "weak"):
        return HoldingCall(symbol=h["symbol"], action="exit", confidence=0.7, reasons_fa=reasons)
    if v == "weak" and (neg or bad_letters):
        return HoldingCall(symbol=h["symbol"], action="reduce", confidence=0.6, reasons_fa=reasons)
    if bad_letters or neg:
        return HoldingCall(symbol=h["symbol"], action="hold", confidence=0.4, reasons_fa=reasons)
    if v == "strong" and pos:
        reasons += [f"خبر مثبت: {n['title']}" for n in pos[:2]]
        return HoldingCall(symbol=h["symbol"], action="add", confidence=0.5, reasons_fa=reasons)
    return HoldingCall(symbol=h["symbol"], action="hold", confidence=0.5, reasons_fa=reasons)


def _llm(payload: dict[str, Any]) -> BriefingCall | None:
    s = get_settings()
    if not s.llm_api_key:
        return None
    import json

    import anthropic

    client = anthropic.Anthropic(api_key=s.llm_api_key)
    r = client.messages.parse(
        model=s.llm_model,
        max_tokens=4000,
        system=SYSTEM,
        messages=[
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        output_format=BriefingCall,
    )
    if r.stop_reason != "end_turn":
        return None
    return r.parsed_output


def brief(
    session: Session, p: Portfolio, kind: str, now: dt.datetime
) -> tuple[dict[str, Any], list[Finding]]:
    adv = advise(session, p)
    since = now - LOOKBACK
    per, market = _evidence(session, adv["holdings"], since)
    calls: dict[str, HoldingCall] = {}
    method = "rules"
    market_fa = ""
    if adv["holdings"]:
        try:
            got = _llm(
                {
                    "kind": kind,
                    "market_news": market,
                    "holdings": [
                        {
                            k: h[k]
                            for k in (
                                "symbol",
                                "verdict",
                                "score",
                                "zone",
                                "pnl_pct",
                                "queue_state",
                                "reasons",
                            )
                        }
                        | per[int(h["instrument_id"])]
                        for h in adv["holdings"]
                    ],
                }
            )
        except Exception:
            log.warning("briefing LLM failed; rules used", exc_info=True)
            got = None
        if got is not None:
            method = "llm"
            market_fa = got.market_fa
            calls = {c.symbol: c for c in got.holdings}
    items = []
    for h in adv["holdings"]:
        ev = per[int(h["instrument_id"])]
        c = calls.get(str(h["symbol"])) or rule_call(h, ev)
        items.append(
            {
                **h,
                "action": c.action,
                "action_fa": ACTION_FA[c.action],
                "confidence": c.confidence,
                "why": c.reasons_fa,
                "news": ev["news"],
                "codal": ev["codal"],
            }
        )
    if not market_fa:
        neg = sum(1 for m in market if m["direction"] < 0)
        market_fa = (
            f"{len(market)} خبر مهم کلان در ۲۴ ساعت گذشته ({neg} منفی)."
            if market
            else "خبر کلان مهمی ثبت نشده است."
        )
    doc = {
        "kind": kind,
        "at": now.isoformat(),
        "method": method,
        "market_fa": market_fa,
        "market_news": market,
        "validated": adv["validated"],
        "note": adv["note"],
        "holdings": items,
        "switches": adv["switches"],
        "buys": adv["buys"],
    }
    findings: list[Finding] = []
    day = now.astimezone(TEHRAN).strftime("%Y%m%d")
    when = "پیش از بازار" if kind == "preopen" else "ساعتی"
    for it in items:
        if it["action"] not in ("exit", "reduce"):
            continue
        sev = URGENT if it["action"] == "exit" and it["confidence"] >= 0.7 else WARN
        findings.append(
            Finding(
                "briefing",
                sev,
                int(it["instrument_id"]),
                f"بازبینی {when}: {it['action_fa']} {it['symbol']}؟",
                "\n".join(it["why"][:5]) or "شواهد منفی برای این نماد ثبت شد.",
                f"{p.id}:{it['instrument_id']}:briefing:{day}",
                {"action": it["action"], "confidence": it["confidence"]},
                ask_exit=True,
            )
        )
    if kind == "preopen" and items:
        summary = "، ".join(f"{i['symbol']}: {i['action_fa']}" for i in items)
        findings.append(
            Finding(
                "briefing",
                INFO,
                None,
                "بازبینی پیش از بازار",
                f"{market_fa}\n{summary}",
                f"{p.id}:-:briefing_summary:{day}",
            )
        )
    return doc, findings


def run_one(session: Session, p: Portfolio, kind: str) -> tuple[PortfolioBriefing, list[Finding]]:
    now = utcnow()
    doc, findings = brief(session, p, kind, now)
    b = PortfolioBriefing(
        portfolio_id=p.id, kind=kind, created_at=now, method=doc["method"], doc=doc
    )
    session.add(b)
    session.flush()
    return b, findings


def run_all(kind: str) -> dict[int, list[Finding]]:
    """Brief every portfolio that holds something; called by the monitor."""
    out: dict[int, list[Finding]] = {}
    with session_scope() as s:
        ids = sorted(set(s.scalars(select(Holding.portfolio_id).where(Holding.shares > 0))))
        for pid in ids:
            p = s.get(Portfolio, pid)
            if p is None:
                continue
            try:
                _, out[pid] = run_one(s, p, kind)
            except Exception:
                log.exception("briefing for portfolio %s failed", pid)
    return out
