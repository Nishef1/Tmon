"""Readiness probe for the live TSETMC integration.

Run it from the network that will do the ingestion. It checks reachability, fetches one payload of
every kind, parses it with the production parsers and cross-checks the market-watch columns
against the daily history. It prints what is verified and what is not; nothing is assumed.

    python -m tmon.ingest.tsetmc.cli probe
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from tmon.core.config import get_settings
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.ingest.http import FetchError, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc import endpoints, parsers

NETWORK_HINT = (
    "TSETMC hosts are not reachable from this network (timeouts or TLS resets are typical when "
    "a connection comes from outside Iran). Run the probe from a network that can open "
    "tsetmc.com, or set TMON_HTTP_PROXY to a route you are entitled to use."
)


@dataclass
class Check:
    name: str
    ok: bool | None  # None = not run / not comparable
    detail: str


async def _step(name: str, fn: Callable[[], Awaitable[str]]) -> Check:
    try:
        return Check(name, True, await fn())
    except (FetchError, parsers.ParseError, httpx.HTTPError, ValueError, KeyError) as exc:
        return Check(name, False, f"{type(exc).__name__}: {exc}")


async def run_probe(client: PoliteClient | None = None) -> list[Check]:
    s = get_settings()
    own = client is None
    http = client or PoliteClient(
        retry=RetryPolicy(max_retries=1, base_delay=0.5),
        client=httpx.AsyncClient(
            timeout=10, headers={"User-Agent": s.http_user_agent}, proxy=s.http_proxy
        ),
    )
    checks: list[Check] = []
    shared: dict[str, object] = {}

    async def get(url: str) -> str:
        return (await http.get(url)).content.decode("utf-8", errors="replace")

    async def watch() -> str:
        text = await get(endpoints.MARKET_WATCH_INIT)
        shared["watch_text"] = text
        items = parsers.parse_market_watch_init(text)
        shared["watch"] = items
        return f"{len(items)} instruments"

    async def quotes() -> str:
        qs = parsers.parse_market_watch_quotes(str(shared["watch_text"]))
        shared["quotes"] = qs
        traded = [q for q in qs if q.volume > 0]
        if not traded:
            return f"{len(qs)} quotes, none traded yet (market closed or pre-open)"
        sane = sum(1 for q in traded if q.low <= q.final <= q.high and q.low <= q.first <= q.high)
        frac = sane / len(traded)
        if frac < 0.9:
            raise ValueError(f"only {frac:.0%} of traded quotes have low<=first,final<=high")
        top = max(traded, key=lambda q: q.value)
        shared["probe_code"] = top.ins_code
        return f"{len(qs)} quotes, {len(traded)} traded, price columns consistent ({frac:.0%})"

    try:
        checks.append(await _step("market watch (instrument list)", watch))
        if not checks[-1].ok:
            checks[-1].detail += f" — {NETWORK_HINT}"
            return checks
        checks.append(await _step("market watch (live quotes)", quotes))
        code = str(shared.get("probe_code") or shared["watch"][0].ins_code)  # type: ignore[index]

        async def history() -> str:
            bars = parsers.parse_daily_history(await get(endpoints.daily_history_url(code)))
            shared["bars"] = bars
            if not bars:
                raise ValueError("no bars")
            return f"{len(bars)} bars, {bars[0].date} → {bars[-1].date}"

        async def clients() -> str:
            rows = parsers.parse_client_types(await get(endpoints.client_types_url(code)))
            return f"{len(rows)} rows"

        async def info() -> str:
            i = parsers.parse_instrument_info(await get(endpoints.instrument_info_url(code)))
            return f"{i.symbol_fa} sector={i.sector_code} group={i.group_title}"

        async def book() -> str:
            lv = parsers.parse_best_limits(await get(endpoints.best_limits_live_url(code)))
            return f"{len(lv)} order-book levels"

        checks.append(await _step(f"daily history ({code})", history))
        checks.append(await _step(f"client types ({code})", clients))
        checks.append(await _step(f"instrument info ({code})", info))
        checks.append(await _step(f"live order book ({code})", book))
        checks.append(_cross_check(shared, code))
    finally:
        if own:
            await http.aclose()
    return checks


def _cross_check(shared: dict[str, object], code: str) -> Check:
    name = "cross-check: market-watch columns vs daily history"
    qs = [q for q in shared.get("quotes", []) if q.ins_code == code]  # type: ignore[attr-defined]
    bars = shared.get("bars") or []
    if not qs or not bars:
        return Check(name, None, "not comparable (a payload is missing)")
    q, bar = qs[0], bars[-1]  # type: ignore[index]
    today = utcnow().astimezone(TEHRAN).date()
    if bar.date != today:
        return Check(name, None, f"not comparable (latest daily bar is {bar.date}, today {today})")
    findings = []
    findings.append(f"yesterday==prev_close:{q.yesterday == bar.prev_close}")
    findings.append(f"final==last:{q.final == bar.last} final==close:{q.final == bar.close}")
    findings.append(f"close==close:{q.close == bar.close} close==last:{q.close == bar.last}")
    findings.append(f"volume:{q.volume == bar.volume}")
    ok = q.yesterday == bar.prev_close and q.volume == bar.volume
    return Check(name, ok, "; ".join(findings))


def format_report(checks: list[Check]) -> str:
    mark = {True: "OK  ", False: "FAIL", None: "SKIP"}
    lines = [f"{mark[c.ok]} {c.name}: {c.detail}" for c in checks]
    verified = sum(1 for c in checks if c.ok)
    lines.append(f"\n{verified}/{len(checks)} checks passed.")
    return "\n".join(lines)


def probe_cli() -> int:
    checks = asyncio.run(run_probe())
    print(format_report(checks))
    return 0 if all(c.ok is not False for c in checks) and any(c.ok for c in checks) else 1
