"""The portfolio monitor: one process that keeps watch for every portfolio.

    python -m tmon.portfolio.monitor            # follow the market day after day
    python -m tmon.portfolio.monitor --force    # also outside trading hours (testing)

While the exchange is open (``market_rules.trading_hours``), every ``monitor_interval_seconds``:

1. one ``GetMarketWatch`` request (every instrument, 5-level books). It is stored in the intraday
   tables exactly as ``tmon.ingest.tsetmc.intraday`` does, so this process replaces that follower;
2. the detectors of ``tmon.portfolio.watch`` run on each holding of each portfolio;
3. every few polls: individuals' flows (``GetClientTypeAll``), the state log (halts), supervisor
   messages and the main index;
4. new findings become alerts and go out at once to the portfolio's channels.

Around it: the newest Codal letters every ``codal_watch_minutes`` and the news feeds every
``news_watch_minutes`` (alerts for held symbols), a pre-open briefing ``preopen_lead_minutes``
before the open and an hourly briefing during the session (``tmon.portfolio.briefing``). Messenger
button presses (exit / reduce / hold) are collected every loop, also when the market is closed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from iran_bourse_mcp.api import TseApi
from iran_bourse_mcp.client import Http
from sqlalchemy import func, select

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.domain.rules import MissingRuleError, RuleBook
from tmon.ingest.news import text as news_text
from tmon.ingest.news.rss import FOREIGN
from tmon.ingest.tsetmc.intraday import IntradayState, in_trading_hours, store_quotes
from tmon.portfolio import alerts as alert_store
from tmon.portfolio.notify import BOT_HOSTS, poll_answers
from tmon.portfolio.watch import (
    INFO,
    MAIN_INDEX_CODE,
    URGENT,
    WARN,
    Finding,
    HoldingView,
    Quote,
    WatchState,
    detect_holding,
    detect_index,
    detect_message,
    detect_real_flow,
    detect_state,
    parse_quote,
    settings_for,
)
from tmon.storage.models import CodalLetter, NewsEvent, NewsRaw, Portfolio
from tmon.storage.objectstore import get_object_store
from tmon.tasks.schedule import is_schedule_day

log = logging.getLogger(__name__)

SLOW_EVERY = 3  # flows, states, messages and index every 3rd poll (~1 minute)
IDLE_SECONDS = 15  # loop pace outside the session: messenger answers and the schedule

CODAL_BAD = ("زیان", "توقف", "تعدیل", "کاهش", "تعلیق", "عدم", "با اهمیت", "اصلاحیه")


def _hours(rules: RuleBook, now: datetime) -> tuple[datetime, datetime] | None:
    local = now.astimezone(TEHRAN)
    try:
        h = rules.value("trading_hours", local.date())
    except MissingRuleError:
        return None
    o, c = (
        datetime.combine(local.date(), datetime.strptime(h[k], "%H:%M").time(), TEHRAN)
        for k in ("open", "close")
    )
    return o, c


def codal_finding(p_id: int, letter: CodalLetter, symbol: str) -> Finding:
    bad = any(w in letter.title for w in CODAL_BAD)
    return Finding(
        "codal",
        WARN if bad else INFO,
        letter.instrument_id,
        f"اطلاعیهٔ کدال: {symbol}",
        letter.title + (f"\n{letter.url}" if letter.url else ""),
        f"{p_id}:codal:{letter.tracing_no}",
        {"tracing_no": letter.tracing_no, "url": letter.url},
        ask_exit=bad,
    )


# Heavy market-wide news without the LLM step: foreign items about Iran with a shock word, and
# domestic items with a war / sanctions / crash word. Market-wide warnings, never per holding.
_IRAN = r"\b(?:iran\w*|tehran|hormuz)\b"
_SHOCK = (
    r"\b(?:war|strikes?|attack\w*|missiles?|mines?|blockade|sanction\w*|snapback|seiz\w*|"
    r"fighting|escalat\w*)\b"
)
FOREIGN_SHOCK = re.compile(f"{_IRAN}.*{_SHOCK}|{_SHOCK}.*{_IRAN}", re.IGNORECASE)
DOMESTIC_SHOCK = (
    "جنگ",
    "حمله",
    "تحریم",
    "اسنپ‌بک",
    "اسنپ بک",
    "مکانیسم ماشه",
    "سقوط بورس",
    "ریزش شاخص",
    "بستن تنگه",
)


def shock(item: NewsRaw) -> bool:
    if item.source in FOREIGN:
        return bool(FOREIGN_SHOCK.search(f"{item.title} {item.summary or ''}"))
    return any(w in item.title for w in DOMESTIC_SHOCK)


def news_finding(
    p_id: int, item: NewsRaw, ev: NewsEvent | None, h: HoldingView | None
) -> Finding | None:
    """A news item about a held symbol (or a heavy market-wide one). Severity follows the
    structured event when the LLM step produced one; a bare title match is information."""
    sev = INFO
    if ev is not None:
        if ev.direction < 0 and ev.magnitude >= 4 and ev.confidence >= 0.7:
            sev = URGENT
        elif ev.direction < 0 and ev.magnitude >= 3:
            sev = WARN
        elif h is None:
            return None  # market-wide items only when they are heavy and negative
    elif h is None:
        if not shock(item):
            return None
        sev = WARN
    who = h.symbol if h else ("کل بازار (خبر خارجی)" if item.source in FOREIGN else "کل بازار")
    body = (ev.summary_fa if ev and ev.summary_fa else item.title) + f"\n{item.url}"
    return Finding(
        "news",
        sev,
        h.instrument_id if h else None,
        f"خبر: {who}",
        body,
        f"{p_id}:news:{item.cluster_id or item.id}",
        {"news_id": item.id, "source": item.source},
        ask_exit=sev >= WARN and h is not None,
    )


@dataclass
class Monitor:
    force: bool = False
    state: WatchState = field(default_factory=WatchState)
    intraday: IntradayState = field(default_factory=IntradayState)
    polls: int = 0
    offsets: dict[str, int] = field(default_factory=dict)
    codal_mark: int | None = None
    news_mark: int | None = None
    last_codal: datetime | None = None
    last_news: datetime | None = None
    briefed: set[str] = field(default_factory=set)

    # -- the session -------------------------------------------------------------------------
    async def market_tick(
        self,
        api: TseApi,
        views: dict[int, tuple[Portfolio, list[HoldingView]]],
        now: datetime,
        session_minutes: float,
    ) -> int:
        raw = await api.market_watch_all()
        with session_scope() as s:
            store_quotes(
                s,
                get_object_store(),
                raw,
                self.intraday,
                book_top_n=get_settings().book_top_n,
                fetched_at=now,
            )
        held = {h.ins_code for _, hs in views.values() for h in hs}
        quotes: dict[str, Quote] = {}
        for r in raw:
            if str(r.get("insCode")) in held:
                q = parse_quote(r)
                quotes[q.ins_code] = q
                self.state.push(q, now)

        slow = self.polls % SLOW_EVERY == 0
        self.polls += 1
        flows: dict[str, dict[str, Any]] = {}
        states: dict[str, str] = {}
        messages: list[dict[str, Any]] = []
        index_row: dict[str, Any] | None = None
        if slow and held:
            flows, states, messages, index_row = await self._slow(api)

        n = 0
        for pid, (p, hs) in views.items():
            cfg = settings_for(p.settings)
            found: list[Finding] = []
            for h in hs:
                hq = quotes.get(h.ins_code)
                if hq is not None:
                    found += detect_holding(h, hq, self.state, cfg, now, session_minutes)
                if h.ins_code in flows:
                    f = detect_real_flow(h, flows[h.ins_code], q, cfg, now)
                    if f:
                        found.append(f)
                if h.ins_code in states:
                    f = detect_state(h, states[h.ins_code], self.state, now)
                    if f:
                        found.append(f)
                for m in messages:
                    f = detect_message(h, m, self.state, now)
                    if f:
                        found.append(f)
            if index_row is not None:
                f = detect_index(pid, index_row, self.state, cfg, now)
                if f:
                    found.append(f)
            n += await self._emit(pid, found, now)
        return n

    async def _slow(
        self, api: TseApi
    ) -> tuple[
        dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]], dict[str, Any] | None
    ]:
        async def safe(coro: Any) -> Any:
            try:
                return await coro
            except Exception as exc:
                log.warning("monitor: %s", exc)
                return []

        flows_raw, log_raw, m1, m2, idx = await asyncio.gather(
            safe(api.client_type_all()),
            safe(api.state_log(200)),
            safe(api.messages_flow(1, 20)),
            safe(api.messages_flow(2, 20)),
            safe(api.indices(1)),
        )
        flows = {str(f.get("insCode")): f for f in flows_raw or []}
        latest: dict[str, tuple[int, int, str]] = {}
        for r in log_raw or []:
            code = str(r.get("insCode"))
            stamp = (int(r.get("dEven") or 0), int(r.get("hEven") or 0))
            if code not in latest or stamp > latest[code][:2]:
                latest[code] = (*stamp, str(r.get("cEtaval") or ""))
        states = {c: v[2] for c, v in latest.items()}
        index_row = next((r for r in idx or [] if str(r.get("insCode")) == MAIN_INDEX_CODE), None)
        return flows, states, [*(m1 or []), *(m2 or [])], index_row

    async def _emit(self, portfolio_id: int, found: list[Finding], now: datetime) -> int:
        if not found:
            return 0
        with session_scope() as s:
            p = s.get(Portfolio, portfolio_id)
            if p is None:
                return 0
            new = alert_store.record(s, portfolio_id, found, now)
            await alert_store.dispatch(s, p, new, get_settings().public_web_url)
            for a in new:
                log.info("alert portfolio=%s sev=%s %s", portfolio_id, a.severity, a.title)
            return len(new)

    # -- Codal and news ----------------------------------------------------------------------
    async def codal_tick(
        self, views: dict[int, tuple[Portfolio, list[HoldingView]]], now: datetime
    ) -> int:
        from tmon.ingest.codal.pipeline import run_letters

        if self.codal_mark is None:
            with session_scope() as s:
                self.codal_mark = s.scalar(select(func.max(CodalLetter.tracing_no))) or 0
        try:
            await asyncio.to_thread(run_letters, max_pages=3)
        except Exception as exc:
            log.warning("monitor codal: %s", exc)
        self.last_codal = now
        by_inst: dict[int, list[tuple[int, HoldingView]]] = {}
        for pid, (_, hs) in views.items():
            for h in hs:
                by_inst.setdefault(h.instrument_id, []).append((pid, h))
        n = 0
        with session_scope() as s:
            letters = list(
                s.scalars(
                    select(CodalLetter)
                    .where(CodalLetter.tracing_no > self.codal_mark)
                    .order_by(CodalLetter.tracing_no)
                )
            )
        if letters:
            self.codal_mark = max(x.tracing_no for x in letters)
        per: dict[int, list[Finding]] = {}
        for x in letters:
            for pid, h in by_inst.get(x.instrument_id or -1, []):
                per.setdefault(pid, []).append(codal_finding(pid, x, h.symbol))
        for pid, found in per.items():
            n += await self._emit(pid, found, now)
        return n

    async def news_tick(
        self, views: dict[int, tuple[Portfolio, list[HoldingView]]], now: datetime
    ) -> int:
        from tmon.ingest.news.pipeline import run_news

        if self.news_mark is None:
            with session_scope() as s:
                self.news_mark = s.scalar(select(func.max(NewsRaw.id))) or 0
        try:
            await asyncio.to_thread(run_news)
        except Exception as exc:
            log.warning("monitor news: %s", exc)
        self.last_news = now
        with session_scope() as s:
            items = list(s.scalars(select(NewsRaw).where(NewsRaw.id > self.news_mark)))
            events = (
                {
                    e.news_id: e
                    for e in s.scalars(
                        select(NewsEvent).where(
                            NewsEvent.news_id.in_([i.cluster_id or i.id for i in items])
                        )
                    )
                }
                if items
                else {}
            )
            for e in events.values():
                s.expunge(e)
            for i in items:
                s.expunge(i)
        if items:
            self.news_mark = max(i.id for i in items)
        n = 0
        for pid, (_, hs) in views.items():
            found: list[Finding] = []
            for it in items:
                if it.cluster_id not in (None, it.id):
                    continue  # one alert per duplicate cluster
                ev = events.get(it.id)
                syms = {news_text.normalize(x) for x in (ev.symbols if ev else [])}
                hit = next(
                    (
                        h
                        for h in hs
                        if news_text.normalize(h.symbol) in syms
                        or (len(h.symbol) >= 3 and h.symbol in it.title_norm.split())
                    ),
                    None,
                )
                f = news_finding(pid, it, ev, hit)
                if f:
                    found.append(f)
            n += await self._emit(pid, found, now)
        return n

    # -- briefings ---------------------------------------------------------------------------
    async def briefing_tick(self, rules: RuleBook, now: datetime) -> None:
        from tmon.portfolio.briefing import run_all

        s = get_settings()
        hours = _hours(rules, now)
        if hours is None or not is_schedule_day(now, s.schedule_days):
            return
        open_, close = hours
        local = now.astimezone(TEHRAN)
        due: str | None = None
        pre = open_ - timedelta(minutes=s.preopen_lead_minutes)
        key = local.strftime("%Y%m%d")
        if pre <= local < open_ and f"{key}:pre" not in self.briefed:
            due, mark = "preopen", f"{key}:pre"
        elif (
            open_ < local <= close
            and local.minute < 5
            and f"{key}:{local.hour}" not in self.briefed
        ):
            due, mark = "hourly", f"{key}:{local.hour}"
        if due is None:
            return
        self.briefed.add(mark)
        try:  # dollar, coin, gold, oil, copper move between sessions: fresh before every review
            from tmon.ingest.macro.pipeline import run_macro

            await asyncio.to_thread(run_macro)
        except Exception as exc:
            log.warning("briefing macro refresh: %s", exc)
        if due == "preopen":  # fresh inputs first
            await self.news_tick({}, now)
            try:
                from tmon.ingest.codal.pipeline import run_letters

                await asyncio.to_thread(run_letters, max_pages=5)
            except Exception as exc:
                log.warning("preopen codal: %s", exc)
        try:
            results = await asyncio.to_thread(run_all, due)
        except Exception:
            log.exception("briefing %s failed", due)
            return
        for pid, found in results.items():
            await self._emit(pid, found, now)

    # -- messenger answers -------------------------------------------------------------------
    async def answers_tick(self, client: httpx.AsyncClient) -> int:
        with session_scope() as s:
            bots = [
                c
                for (chs,) in s.execute(select(Portfolio.channels))
                for c in chs or []
                if c.get("type") in BOT_HOSTS and c.get("token")
            ]
        if not bots:
            return 0

        def on_answer(alert_id: int, value: str, chat: str) -> bool:
            with session_scope() as s:
                return alert_store.answer(s, alert_id, value, chat_id=chat) is not None

        return await poll_answers(client, bots, self.offsets, on_answer)

    # -- the loop ----------------------------------------------------------------------------
    async def run(self, *, once: bool = False) -> None:
        s = get_settings()
        http = Http()
        api = TseApi(http)
        client = httpx.AsyncClient(timeout=15)
        try:
            while True:
                now = utcnow()
                with session_scope() as db:
                    rules = RuleBook.from_session(db)
                    views = alert_store.holding_views(db)
                    for p, _ in views.values():
                        db.expunge(p)
                hours = _hours(rules, now)
                open_now = self.force or in_trading_hours(rules, now)
                minutes = (hours[1] - hours[0]).total_seconds() / 60 if hours else 210.0
                try:
                    await self.answers_tick(client)
                    await self.briefing_tick(rules, now)
                    if open_now and views:
                        await self.market_tick(api, views, now, minutes)
                    codal_gap = s.codal_watch_minutes if open_now else 30
                    news_gap = s.news_watch_minutes if open_now else 60
                    if views and (
                        self.last_codal is None
                        or now - self.last_codal >= timedelta(minutes=codal_gap)
                    ):
                        await self.codal_tick(views, now)
                    if views and (
                        self.last_news is None
                        or now - self.last_news >= timedelta(minutes=news_gap)
                    ):
                        await self.news_tick(views, now)
                except Exception:
                    log.exception("monitor tick failed")
                if not open_now:
                    self.intraday = IntradayState()
                    self.state = WatchState(seen_messages=self.state.seen_messages)
                if once:
                    break
                await asyncio.sleep(s.monitor_interval_seconds if open_now else IDLE_SECONDS)
        finally:
            await client.aclose()
            await http.aclose()


def main() -> None:
    from tmon.core.logging import configure_logging

    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-monitor")
    ap.add_argument("--force", action="store_true", help="watch also outside trading hours")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    asyncio.run(Monitor(force=a.force).run(once=a.once))


if __name__ == "__main__":
    main()
