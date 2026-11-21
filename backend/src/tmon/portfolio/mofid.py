"""Link a portfolio to a Mofid (EasyTrader) account and copy its holdings and cash.

Mofid has no public API key: its site gets a bearer token after the owner logs in on
``login.emofid.com``. Tmon opens the owner's installed Chrome on a profile kept for that portfolio
(``<mofid_profile_dir>/<portfolio id>``), the owner logs in there themselves, and Tmon keeps the
token the site then sends to ``api-mts.orbis.easytrader.ir``. The profile keeps the login, so
later tokens come from a hidden Chrome without asking again until Mofid ends the session.

A sync reads ``assetmodule/api/performance`` (every position with its average price) and
``easy/api/money`` (buying power). Each Mofid position becomes one ``mofid`` ledger line at
Mofid's average price, dated at Mofid's period start or the last share-count change after it, so
a bonus Mofid already counted is not applied a second time. Lines of other sources for the same
symbols are replaced; symbols Mofid does not report are left alone. The cash becomes the buying
power.

An average that cannot have been paid (outside half the lowest low to twice the highest high
since the period began, when every unit was bought in it) is not used: the line is valued at that
day's close and marked estimated until the owner gives the real cost
(``settings['mofid_cost'][isin]``, total rial), which always wins.

Only a machine with Chrome and the saved login can renew a token (about 12 hours each). The PC
does it every morning and hands the token to the server (``python -m tmon.portfolio.mofid renew
--ssh ...``); a sync that fails marks the link broken, and the monitor tells the owner once.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import jdatetime
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.portfolio import ledger
from tmon.portfolio.watch import WARN, Finding
from tmon.storage.models import BrokerLink, Instrument, Portfolio, PortfolioTrade, PriceDaily

log = logging.getLogger(__name__)

API = "https://api-mts.orbis.easytrader.ir"
SITE = "https://d.easytrader.ir/"
HIDDEN_WAIT = 40  # seconds for a saved login to produce a token without a window
LOGIN_WAIT = 600  # seconds the owner has to log in
_running: set[int] = set()
_lock = threading.Lock()


class MofidError(RuntimeError):
    pass


FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
EXPIRED = "ورود به مفید تمام شده است؛ دوباره «اتصال به مفید» را بزن"


def profile_dir(portfolio_id: int) -> Path:
    root = get_settings().mofid_profile_dir
    base = Path(root) if root else Path(__file__).resolve().parents[4] / "data" / "mofid-profile"
    return base / str(portfolio_id)


def _expiry(token: str) -> dt.datetime | None:
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return dt.datetime.fromtimestamp(int(claims["exp"]), dt.UTC)
    except (IndexError, KeyError, ValueError):
        return None


def _valid(link: BrokerLink | None) -> bool:
    if link is None or not link.token:
        return False
    exp = link.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=dt.UTC)
    return exp is None or exp > utcnow() + dt.timedelta(minutes=2)


def capture_token(portfolio_id: int, *, visible: bool, wait: float) -> str | None:
    """Open Chrome on the portfolio's profile and return the first bearer token the site uses."""
    from playwright.sync_api import Request, sync_playwright

    profile = profile_dir(portfolio_id)
    profile.mkdir(parents=True, exist_ok=True)
    found: dict[str, str] = {}

    def on_request(req: Request) -> None:
        if not req.url.startswith(API):
            return
        auth = req.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and len(auth) > 40:
            found["token"] = auth[7:].strip()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=not visible,
            no_viewport=visible,
            # the site's service worker makes the API calls itself, out of sight of on_request
            service_workers="block",
            args=["--disable-blink-features=AutomationControlled"]
            + (["--start-maximized"] if visible else []),
            ignore_default_args=["--enable-automation"],
        )
        try:
            ctx.on("request", on_request)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(SITE)
            t0 = time.monotonic()
            while "token" not in found and time.monotonic() - t0 < wait:
                if visible and not ctx.pages:
                    break  # the owner closed the window
                time.sleep(1)
        finally:
            with contextlib.suppress(Exception):
                ctx.close()
    return found.get("token")


def _link(session: Session, portfolio_id: int) -> BrokerLink:
    link = session.get(BrokerLink, portfolio_id)
    if link is None:
        link = BrokerLink(portfolio_id=portfolio_id, broker="mofid", status="new")
        session.add(link)
        session.flush()
    return link


def _store(session: Session, portfolio_id: int, token: str) -> None:
    link = _link(session, portfolio_id)
    link.token = token
    link.expires_at = _expiry(token)
    link.status, link.message = "linked", None


def connect(portfolio_id: int) -> None:
    """Get a token: from the saved login first, else a Chrome window for the owner to log in.
    Then sync. Runs in its own thread; progress is in the link's status."""
    with _lock:
        if portfolio_id in _running:
            return
        _running.add(portfolio_id)
    try:
        token = capture_token(portfolio_id, visible=False, wait=HIDDEN_WAIT)
        if token is None:
            with session_scope() as s:
                link = _link(s, portfolio_id)
                link.status, link.message = "login", "در پنجرهٔ کروم وارد حساب مفید شو"
            token = capture_token(portfolio_id, visible=True, wait=LOGIN_WAIT)
        with session_scope() as s:
            if token is None:
                link = _link(s, portfolio_id)
                link.status, link.message = "error", "در زمان داده‌شده ورودی انجام نشد"
                return
            _store(s, portfolio_id, token)
        with session_scope() as s:
            p = s.get(Portfolio, portfolio_id)
            if p is not None:
                sync(s, p, refresh=False)
    except Exception as e:
        log.exception("mofid connect failed")
        with session_scope() as s:
            link = _link(s, portfolio_id)
            link.status, link.message = "error", str(e)[:300]
    finally:
        with _lock:
            _running.discard(portfolio_id)


def start_connect(portfolio_id: int) -> bool:
    if portfolio_id in _running:
        return False
    threading.Thread(target=connect, args=(portfolio_id,), daemon=True).start()
    return True


def busy(portfolio_id: int) -> bool:
    return portfolio_id in _running


def _get(token: str, path: str) -> Any:
    r = httpx.get(
        API + path,
        headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-store"},
        timeout=30,
    )
    if r.status_code == 401:
        raise PermissionError("token rejected")
    r.raise_for_status()
    return r.json()


def fetch(
    session: Session, p: Portfolio, *, refresh: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Mofid's positions and money, renewing the token from the saved login when needed."""
    link = session.get(BrokerLink, p.id)
    if not _valid(link) and refresh:
        try:
            token = capture_token(p.id, visible=False, wait=HIDDEN_WAIT)
        except Exception as e:  # no Chrome here (the server): only the PC can renew
            log.info("mofid renew on this machine failed: %s", e)
            token = None
        if token is None:
            raise MofidError(EXPIRED)
        _store(session, p.id, token)
        session.flush()
        link = session.get(BrokerLink, p.id)
    if link is None or not link.token:
        raise MofidError("حساب مفید وصل نیست")
    try:
        perf = _get(link.token, "/assetmodule/api/performance")
        money = _get(link.token, "/easy/api/money")
    except PermissionError:
        if not refresh:
            raise MofidError(EXPIRED) from None
        link.token = None
        return fetch(session, p, refresh=True)
    return list(perf.get("items") or []), dict(money or {})


def _paid_range(session: Session, iid: int, x: dict[str, Any]) -> tuple[float, float] | None:
    """Lowest low and highest high since Mofid's period began, when every unit held was bought
    in that period (otherwise the average carries older buys and cannot be bounded)."""
    try:
        start = dt.date.fromisoformat(str(x.get("date"))[:10])
    except ValueError:
        return None
    bought = float(x.get("periodicBoughtVolume") or 0)
    if bought < float(x.get("asset") or 0):
        return None
    if float(x.get("totalBoughtVolume") or 0) > bought:
        return None  # older buys: Mofid restarts the period at a bonus and counts it as bought
    lo, hi = session.execute(
        select(func.min(PriceDaily.low), func.max(PriceDaily.high)).where(
            PriceDaily.instrument_id == iid, PriceDaily.date >= start, PriceDaily.low > 0
        )
    ).one()
    return (float(lo), float(hi)) if lo and hi else None


def _held_since(session: Session, iid: int, x: dict[str, Any], day: dt.date) -> dt.date:
    """Mofid's period start, moved past any later share-count change: the shares Mofid gives
    are today's count, so the ledger must not multiply them by a bonus or rights issue again."""
    try:
        start = min(dt.date.fromisoformat(str(x.get("date"))[:10]), day)
    except ValueError:
        return day
    moves = [
        a.date
        for a in ledger.corporate_actions(session, iid, start - dt.timedelta(days=1))
        if a.ratio != 1 and a.date <= day
    ]
    return max([start, *moves])


def costs(p: Portfolio) -> dict[str, float]:
    """The real buy cost the owner gave per ISIN (total rial)."""
    return {k: float(v) for k, v in ((p.settings or {}).get("mofid_cost") or {}).items()}


def set_cost(session: Session, p: Portfolio, isin: str, amount: float | None) -> None:
    c = costs(p)
    if amount and amount > 0:
        c[isin] = float(amount)
    else:
        c.pop(isin, None)
    p.settings = {**(p.settings or {}), "mofid_cost": c}
    link = session.get(BrokerLink, p.id)
    items = (link.last_result or {}).get("items") if link else None
    if link is not None and items is not None:  # re-apply the last sync with the new cost
        link.last_result = {**apply(session, p, items, {}), "items": items}
    session.commit()


def apply(
    session: Session, p: Portfolio, items: list[dict[str, Any]], money: dict[str, Any]
) -> dict[str, Any]:
    """Write Mofid's positions as ledger lines and its buying power as the cash."""
    day = ledger.market_date(session) or utcnow().date()
    ledger.migrate_legacy(session, p)
    by_isin = {
        i.isin: i
        for i in session.scalars(
            select(Instrument).where(Instrument.isin.in_([x.get("symbolIsin") for x in items]))
        )
    }
    session.execute(
        delete(PortfolioTrade).where(
            PortfolioTrade.portfolio_id == p.id, PortfolioTrade.source == "mofid"
        )
    )
    held, unknown = [], []
    realized = dividends = 0.0
    for x in items:
        realized += float(x.get("totalRealizedProfitAndLoss") or 0)
        dividends += float(x.get("totalDPSAmount") or 0)
        shares = float(x.get("asset") or 0)
        if shares <= 0:
            continue
        inst = by_isin.get(x.get("symbolIsin"))
        if inst is None:
            unknown.append(x.get("symbolName") or x.get("symbolIsin"))
            continue
        session.execute(
            delete(PortfolioTrade).where(
                PortfolioTrade.portfolio_id == p.id, PortfolioTrade.instrument_id == inst.id
            )
        )
        isin = str(x.get("symbolIsin"))
        avg = float(x.get("periodicBuyAveragePrice") or x.get("totalBuyAveragePrice") or 0)
        mofid_avg, source = avg, "mofid"
        given = costs(p).get(isin)
        if given:
            avg, source = given / shares, "owner"
        elif avg:
            rng = _paid_range(session, inst.id, x)
            if rng and not (rng[0] * 0.5 <= avg <= rng[1] * 2):
                avg, source = 0.0, "doubtful"
        session.add(
            PortfolioTrade(
                portfolio_id=p.id,
                instrument_id=inst.id,
                side="buy",
                date=_held_since(session, inst.id, x, day),
                shares=shares,
                price=avg or None,
                fee=0.0 if source == "owner" else None,  # the owner gives what they paid
                cash_delta=0.0,
                source="mofid",
                external_id=f"mofid:{x.get('symbolIsin')}",
                note="Mofid",
                created_at=utcnow(),
            )
        )
        held.append(
            {
                "symbol": inst.symbol_fa,
                "isin": isin,
                "shares": shares,
                "avg_price": avg or None,
                "mofid_avg_price": mofid_avg,
                "cost_source": source,
                "owner_cost": given,
            }
        )
    if money.get("buyPowerT0") is not None:
        p.cash = max(0.0, float(money["buyPowerT0"]))
    session.flush()
    ledger.rebuild(session, p)
    return {
        "positions": held,
        "unknown": unknown,
        "cash": p.cash,
        "mofid_realized": realized,
        "mofid_dividends": dividends,
    }


def sync(session: Session, p: Portfolio, *, refresh: bool = True) -> dict[str, Any]:
    link = _link(session, p.id)
    try:
        items, money = fetch(session, p, refresh=refresh)
    except Exception as e:
        link.status = "error"
        link.message = str(e) if isinstance(e, MofidError) else "مفید پاسخ نداد؛ بعداً دوباره"
        session.commit()
        raise
    result = apply(session, p, items, money)
    link.status, link.message = "linked", None
    link.last_sync_at = utcnow()
    link.last_result = {**result, "items": items}
    session.commit()
    return result


def status(session: Session, portfolio_id: int) -> dict[str, Any]:
    link = session.get(BrokerLink, portfolio_id)
    if link is None:
        return {"linked": False, "status": "none", "busy": busy(portfolio_id)}
    linked = link.status == "linked" or bool(link.last_sync_at)
    return {
        "linked": linked,
        # holdings are only as fresh as the last sync: say so when no sync can run now
        "stale": linked and not busy(portfolio_id) and (link.status == "error" or not _valid(link)),
        "status": link.status,
        "message": link.message,
        "busy": busy(portfolio_id),
        "token_valid": _valid(link),
        "expires_at": link.expires_at,
        "last_sync_at": link.last_sync_at,
        "last_result": {k: v for k, v in (link.last_result or {}).items() if k != "items"},
    }


def unlink(session: Session, portfolio_id: int) -> None:
    """Forget the token and the saved login; the ledger lines stay as the last sync left them."""
    link = session.get(BrokerLink, portfolio_id)
    if link is not None:
        session.delete(link)
    import shutil

    shutil.rmtree(profile_dir(portfolio_id), ignore_errors=True)


def broken_finding(link: BrokerLink) -> Finding:
    """The alert for a link that stopped working; one per last good sync."""
    since = link.last_sync_at
    when = since.replace(tzinfo=dt.UTC).astimezone(TEHRAN) if since else None
    body = (link.message or EXPIRED) + "."
    if when is not None:
        day = jdatetime.date.fromgregorian(date=when.date()).strftime("%Y/%m/%d")
        stamp = f"{day} ساعت {when:%H:%M}".translate(FA_DIGITS)
        body += f" دارایی‌ها و نقد صفحه همان آخرین دریافت در {stamp} است و خرید و فروش بعد از آن"
        body += " را نشان نمی‌دهد."
    return Finding(
        kind="mofid_link",
        severity=WARN,
        instrument_id=None,
        title="اتصال به مفید قطع شد",
        body=body,
        key=f"mofid_link:{since.isoformat() if since else 'never'}",
    )


def sync_all() -> dict[int, Finding]:
    """Refresh every linked portfolio (from the monitor); a failure is kept on the link. Returns
    an alert for each link that worked before this round and failed in it."""
    with session_scope() as s:
        ids = s.scalars(select(BrokerLink.portfolio_id).where(BrokerLink.broker == "mofid")).all()
    broke: dict[int, Finding] = {}
    for pid in ids:
        if busy(pid):
            continue
        try:
            with session_scope() as s:
                p = s.get(Portfolio, pid)
                if p is not None:
                    sync(s, p)
        except Exception as e:
            log.warning("mofid sync %s: %s", pid, e)
            with session_scope() as s:
                link = s.get(BrokerLink, pid)
                if link is not None and link.last_sync_at is not None:
                    broke[pid] = broken_finding(link)
    return broke


def accept(portfolio_id: int, token: str) -> dict[str, Any]:
    """Take a token renewed elsewhere (the PC) and sync with it at once."""
    with session_scope() as s:
        if s.get(Portfolio, portfolio_id) is None:
            raise MofidError(f"portfolio {portfolio_id} not found")
        _store(s, portfolio_id, token)
    with session_scope() as s:
        p = s.get(Portfolio, portfolio_id)
        assert p is not None
        return sync(s, p, refresh=False)


def renew(ssh: list[str] | None = None, remote: str = "") -> int:
    """Renew every link from its saved login, sync here, and hand the token to the server over
    ``ssh`` (stdin, never the command line). Prints one line per portfolio, never the token.
    Returns how many links need the owner to log in again."""
    import subprocess

    with session_scope() as s:
        ids = s.scalars(select(BrokerLink.portfolio_id).where(BrokerLink.broker == "mofid")).all()
    need_login = 0
    for pid in ids:
        token = capture_token(pid, visible=False, wait=HIDDEN_WAIT)
        if token is None:
            need_login += 1
            with session_scope() as s:
                link = _link(s, pid)
                link.status, link.message = "error", EXPIRED
            print(f"portfolio {pid}: saved login ended, the owner must connect again")
            continue
        try:
            result = accept(pid, token)
            print(f"portfolio {pid}: renewed here, {len(result['positions'])} positions")
        except Exception as e:
            print(f"portfolio {pid}: renewed, local sync failed: {e}")
        if ssh:
            r = subprocess.run(
                [*ssh, f"{remote} accept {pid}"],
                check=False,
                input=token,
                text=True,
                capture_output=True,
                timeout=180,
            )
            out = (r.stdout or r.stderr).strip().splitlines()
            print(f"portfolio {pid}: server: {out[-1] if out else r.returncode}")
    return need_login


def main(argv: list[str] | None = None) -> int:
    import argparse
    import shlex
    import sys

    ap = argparse.ArgumentParser(prog="python -m tmon.portfolio.mofid")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("renew", help="renew every link from its saved login (the PC)")
    rn.add_argument("--ssh", default="", help='e.g. "ssh -p 1415 -i KEY root@HOST"')
    rn.add_argument(
        "--remote",
        # the services' own environment file, read by systemd (a shell would mangle its JSON)
        default="systemd-run --quiet --wait --pipe -p EnvironmentFile=/etc/tmon.env "
        "-p WorkingDirectory=/opt/tmon/backend /opt/tmon/backend/.venv/bin/python "
        "-m tmon.portfolio.mofid",
        help="the command on the server that runs this module",
    )
    ac = sub.add_parser("accept", help="read a token from stdin and sync (the server)")
    ac.add_argument("portfolio_id", type=int)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if a.cmd == "renew":
        return 1 if renew(shlex.split(a.ssh) if a.ssh else None, a.remote) else 0
    token = sys.stdin.read().strip()
    if not token:
        print("no token on stdin")
        return 2
    result = accept(a.portfolio_id, token)
    print(f"synced {len(result['positions'])} positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
