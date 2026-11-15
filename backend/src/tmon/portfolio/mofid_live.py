"""Live order book, prices and individual/institutional flow from Mofid's push server.

EasyTrader's site gets its live data from a Lightstreamer server (``ls.easytrader.ir``, protocol
TLCP 2.1). A session needs only the customer number of a linked account (``customer_isin`` in
the token Tmon keeps, see :mod:`tmon.portfolio.mofid`); no password goes over it. One session
serves every symbol: a symbol is subscribed the first time its page asks and dropped once nobody
has asked for :data:`IDLE_DROP` seconds.

The server pushes a change the moment it happens and nothing while nothing changes, so a value is
current as long as the session is alive. :func:`snapshot` returns the values with the time the
server last spoke (``heard``); the caller calls the data stale when that is old, never by the age
of the value itself.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import json
import logging
import threading
import time
import urllib.parse
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.timeutil import TEHRAN, utcnow
from tmon.storage.models import BrokerLink

log = logging.getLogger(__name__)

BASE = "https://ls.easytrader.ir/lightstreamer"
CID = "pcYgxn8m8 feOojyA1U661o3g2.pz47Ag7s"  # the site's own Lightstreamer client id
HEADERS = {"Origin": "https://d.easytrader.ir", "Content-Type": "text/plain; charset=utf-8"}
IDLE_DROP = 120.0
ALIVE = 15.0  # the server sends a probe every few seconds; silence longer than this = cut off

LEVELS = 5
BOOK_FIELDS = ["timestamp"] + [
    f"{side}-{what}-{n}"
    for n in range(1, LEVELS + 1)
    for side, what in [
        ("buy", "volume"),
        ("sell", "volume"),
        ("buy", "order-count"),
        ("sell", "order-count"),
        ("buy", "price"),
        ("sell", "price"),
    ]
]
SYMBOL_FIELDS = [
    "last-trade-price",
    "closing-price",
    "prev-closing-price",
    "total-number-of-shares-traded",
    "total-trade-value",
    "total-number-of-trades",
    "max-daily-price",
    "min-daily-price",
    "max-daily-traded-price",
    "min-daily-traded-price",
    "state-code",
]
FLOW_FIELDS = [
    "timestamp",
    "buy-count-person",
    "buy-count-legal",
    "buy-volume-person",
    "buy-volume-legal",
    "sell-count-person",
    "sell-count-legal",
    "sell-volume-person",
    "sell-volume-legal",
]
FEEDS = {  # kind -> (group prefix, fields, data adapter)
    "book": ("bestlimit", BOOK_FIELDS, "BESTLIMIT_ADAPTER"),
    "symbol": ("symbol", SYMBOL_FIELDS, "RLC_ADAPTER"),
    "flow": ("tradevolume", FLOW_FIELDS, "SLE_ADAPTER"),
}


def customer_number(token: str | None) -> str | None:
    """The account number in a Mofid token (the push server's user name)."""
    if not token:
        return None
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    v = claims.get("customer_isin")
    return str(v) if v else None


def decode(values: str, previous: list[str | None]) -> list[str | None]:
    """One TLCP update line's values against the item's previous ones: empty = unchanged,
    ``#`` = null, ``$`` = empty string, ``^N`` = the next N unchanged, else percent-encoded."""
    out: list[str | None] = []
    for tok in values.split("|"):
        i = len(out)
        if tok == "":
            out.append(previous[i] if i < len(previous) else None)
        elif tok == "#":
            out.append(None)
        elif tok == "$":
            out.append("")
        elif tok.startswith("^") and tok[1:].isdigit():
            n = int(tok[1:])
            out.extend(previous[i + k] if i + k < len(previous) else None for k in range(n))
        else:
            out.append(urllib.parse.unquote(tok))
    return out


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _stamp(v: str | None) -> dt.datetime | None:
    """``20261115105524`` (Tehran) or epoch milliseconds -> aware UTC."""
    if not v or not v.isdigit():
        return None
    if len(v) == 13 and v[0] == "1":
        return dt.datetime.fromtimestamp(int(v) / 1000, dt.UTC)
    try:
        t = dt.datetime.strptime(v[:14], "%Y%m%d%H%M%S").replace(tzinfo=TEHRAN)
    except ValueError:
        return None
    return t.astimezone(dt.UTC)


def shape(kind: str, values: list[str | None]) -> dict[str, Any]:
    fields = FEEDS[kind][1]
    raw = dict(zip(fields, values, strict=False))
    if kind == "book":
        levels = []
        for n in range(1, LEVELS + 1):
            lv = {
                "row": n,
                "bid_price": _num(raw.get(f"buy-price-{n}")) or 0.0,
                "bid_volume": _num(raw.get(f"buy-volume-{n}")) or 0.0,
                "bid_count": int(_num(raw.get(f"buy-order-count-{n}")) or 0),
                "ask_price": _num(raw.get(f"sell-price-{n}")) or 0.0,
                "ask_volume": _num(raw.get(f"sell-volume-{n}")) or 0.0,
                "ask_count": int(_num(raw.get(f"sell-order-count-{n}")) or 0),
            }
            if lv["bid_volume"] or lv["ask_volume"]:
                levels.append(lv)
        return {"as_of": _stamp(raw.get("timestamp")), "levels": levels}
    if kind == "flow":
        return {"as_of": _stamp(raw.get("timestamp"))} | {
            k.replace("-", "_"): _num(raw.get(k)) for k in FLOW_FIELDS[1:]
        }
    return {k.replace("-", "_"): _num(raw.get(k)) for k in fields if k != "state-code"} | {
        "state_code": raw.get("state-code")
    }


class Stream:
    """One Lightstreamer session in a background thread, shared by every symbol page."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._session: str | None = None
        self._thread: threading.Thread | None = None
        self._req = 0
        self._next_sub = 0
        self._subs: dict[int, tuple[str, str]] = {}  # subId -> (isin, kind)
        self._by_key: dict[tuple[str, str], int] = {}
        self._raw: dict[tuple[str, str], list[str | None]] = {}
        self._got: dict[tuple[str, str], float] = {}
        self._asked: dict[str, float] = {}
        self._user: str | None = None
        self.heard = 0.0  # monotonic time the server last sent anything
        self.error: str | None = None

    # -- public ---------------------------------------------------------------------------
    def snapshot(self, isin: str, user: str, wait: float = 3.0) -> dict[str, Any] | None:
        """Ask for a symbol and return its current values (waiting up to ``wait`` seconds for
        the first push of a new symbol), or None when there is no live data for it."""
        with self._lock:
            self._asked[isin] = time.monotonic()
            self._user = user
        self._ensure_thread()
        self._subscribe(isin)
        end = time.monotonic() + wait
        while time.monotonic() < end and (isin, "book") not in self._raw:
            time.sleep(0.05)
        with self._lock:
            if (isin, "book") not in self._raw:
                return None
            out: dict[str, Any] = {
                kind: shape(kind, self._raw[(isin, kind)])
                for kind in FEEDS
                if (isin, kind) in self._raw
            }
            out["alive"] = self.alive()
            out["heard_at"] = utcnow() - dt.timedelta(seconds=time.monotonic() - self.heard)
            return out

    def alive(self) -> bool:
        return self._session is not None and time.monotonic() - self.heard < ALIVE

    # -- session --------------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="mofid-live", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        pause = 1.0
        while True:
            with self._lock:
                if not self._asked:
                    self._thread = None
                    return
            user = self._user
            if not user:
                return
            try:
                self._stream(user)
                pause = 1.0
            except (httpx.HTTPError, OSError, ValueError) as e:
                self.error = f"{type(e).__name__}"
                log.info("mofid live: %s", e)
            with self._lock:
                self._session = None
                self._subs.clear()
                self._by_key.clear()
            time.sleep(pause)
            pause = min(pause * 2, 30.0)

    def _stream(self, user: str) -> None:
        body = {"LS_polling": "false", "LS_cid": CID, "LS_adapter_set": "lsadapter-conf"}
        body["LS_user"] = user
        client = httpx.Client(timeout=httpx.Timeout(10, read=ALIVE * 2), headers=HEADERS)
        self._client = client
        try:
            with client.stream(
                "POST",
                f"{BASE}/create_session.txt?LS_protocol=TLCP-2.1.0",
                content=urllib.parse.urlencode(body, quote_via=urllib.parse.quote),
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    self.heard = time.monotonic()
                    if not self._line(line):
                        return
        finally:
            with contextlib.suppress(Exception):
                client.close()
            self._client = None

    def _line(self, line: str) -> bool:
        """Handle one line; False ends the session (the caller reconnects)."""
        head, _, rest = line.partition(",")
        if head == "CONOK":
            self._session = rest.split(",")[0]
            self.error = None
            threading.Thread(target=self._resubscribe, daemon=True).start()
        elif head == "U":
            sub, _item, values = rest.split(",", 2)
            key = self._subs.get(int(sub))
            if key:
                with self._lock:
                    self._raw[key] = decode(values, self._raw.get(key, []))
                    self._got[key] = time.monotonic()
        elif head in ("LOOP", "END", "CONERR", "ERROR"):
            return False
        self._drop_idle()
        return True

    def _control(self, params: dict[str, str]) -> str:
        client, session = self._client, self._session
        if client is None or session is None:
            return ""
        with self._lock:
            self._req += 1
            params = {"LS_reqId": str(self._req)} | params
        r = client.post(
            f"{BASE}/control.txt?LS_protocol=TLCP-2.1.0&LS_session={session}",
            content=urllib.parse.urlencode(params, quote_via=urllib.parse.quote),
        )
        return r.text

    def _subscribe(self, isin: str) -> None:
        if self._session is None:
            return  # done on CONOK
        for kind, (prefix, fields, adapter) in FEEDS.items():
            with self._lock:
                if (isin, kind) in self._by_key:
                    continue
                self._next_sub += 1
                sub = self._next_sub
                self._subs[sub] = (isin, kind)
                self._by_key[(isin, kind)] = sub
            try:
                self._control(
                    {
                        "LS_op": "add",
                        "LS_subId": str(sub),
                        "LS_mode": "MERGE",
                        "LS_group": f"{prefix}:{isin}",
                        "LS_schema": " ".join(fields),
                        "LS_data_adapter": adapter,
                        "LS_snapshot": "true",
                    }
                )
            except httpx.HTTPError:
                with self._lock:
                    self._subs.pop(sub, None)
                    self._by_key.pop((isin, kind), None)

    def _resubscribe(self) -> None:
        with self._lock:
            isins = list(self._asked)
        for isin in isins:
            self._subscribe(isin)

    def _drop_idle(self) -> None:
        now = time.monotonic()
        with self._lock:
            idle = [i for i, t in self._asked.items() if now - t > IDLE_DROP]
            for i in idle:
                del self._asked[i]
            gone = [(sub, key) for key, sub in self._by_key.items() if key[0] in idle]
            for sub, key in gone:
                self._by_key.pop(key, None)
                self._subs.pop(sub, None)
                self._raw.pop(key, None)
        for sub, _ in gone:
            threading.Thread(
                target=lambda s=sub: self._control({"LS_op": "delete", "LS_subId": str(s)}),
                daemon=True,
            ).start()


STREAM = Stream()


def linked_user(session: Session) -> str | None:
    """The customer number of any linked Mofid account (the push server's user name)."""
    for token in session.scalars(select(BrokerLink.token).where(BrokerLink.token.is_not(None))):
        if user := customer_number(token):
            return user
    return None


def snapshot(session: Session, isin: str | None, wait: float = 3.0) -> dict[str, Any] | None:
    """Live values of one symbol, or None when no Mofid account is linked or nothing came."""
    user = linked_user(session) if isin else None
    return STREAM.snapshot(isin, user, wait) if isin and user else None
