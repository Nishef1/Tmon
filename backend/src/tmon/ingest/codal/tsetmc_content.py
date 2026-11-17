"""Codal content through TSETMC's own API: every letter and the assembly decisions of a symbol.

TSETMC re-serves what Codal publishes and, unlike codal.ir, does not throttle or ask for a CAPTCHA
(checked 2026-11-17):

* ``Codal/GetPreparedDataByInsCode/{top}/{insCode}`` lists every letter of one issuer, back to its
  first one (tracing number, title, times, which files exist).
* ``Codal/GetStatementContentByInsCode/{reportType}/{subType}/{page}/{insCode}`` returns the
  content of the 15 newest letters of one kind as XML. ``14/0/-1`` is the assembly decisions
  (ن-۵۲), whose profit-appropriation table holds the earnings per share and the cash dividend per
  share, the same row Codal's letter page has.

Here the decisions of the ordinary assemblies are read into ``corporate_events.dps``, matched to the
letter by its publication day and title. Raw answers are kept in the object store.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.db import session_scope
from tmon.core.logging import configure_logging
from tmon.core.timeutil import utcnow
from tmon.ingest.codal.backfill import basket_symbols
from tmon.ingest.codal.dividends import DECISION_STAGE
from tmon.ingest.codal.parsers import ascii_digits
from tmon.ingest.codal.tsetmc_feed import parse_feed, store_new
from tmon.ingest.http import FetchError, PoliteClient
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.storage.models import CodalLetter, CorporateEvent, Instrument
from tmon.storage.objectstore import get_object_store, store_raw_payload

log = logging.getLogger(__name__)

BASE = "https://cdn.tsetmc.com/api/Codal/"
LIST_URL = BASE + "GetPreparedDataByInsCode/{top}/{ins}"
DECISIONS_URL = BASE + "GetStatementContentByInsCode/14/0/-1/{ins}"
SOURCE = "tsetmc-codal"
_DPS_LABEL = "سود نقدی هر سهم"
_EPS_LABEL = "سود (زیان) خالص هر سهم"
_CELLS = re.compile(r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", re.DOTALL)


def _number(text: str) -> float | None:
    t = ascii_digits(re.sub(r"<[^>]+>", "", text)).replace(",", "").replace("٬", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def parse_profit_table(content: str) -> dict[str, float | None]:
    """Cash dividend and earnings per share (rial) from the appropriation table of a decisions
    letter; a key is None when the row or its number is missing."""
    out: dict[str, float | None] = {"dps": None, "eps": None}
    for label, value in _CELLS.findall(content):
        name = normalize_fa(re.sub(r"<[^>]+>", "", label))
        if out["dps"] is None and name.startswith(_DPS_LABEL):
            out["dps"] = _number(value)
        elif out["eps"] is None and name.startswith(_EPS_LABEL):
            out["eps"] = _number(value)
    return out


def decisions_of(payload: bytes | str) -> list[dict[str, Any]]:
    """Ordinary-assembly decisions in a ``14/0/-1`` answer: day, title, dps, eps."""
    data = json.loads(payload)
    out: list[dict[str, Any]] = []
    for row in data.get("statemetnContent") or []:
        title = normalize_fa(row.get("title") or "")
        if "عادی" not in title:
            continue
        out.append(
            {
                "day": row.get("publishDateTime_DEven"),
                "title": title,
                **parse_profit_table(row.get("content") or ""),
            }
        )
    return out


def _day(d: int) -> date:
    s = str(d)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def apply_decisions(session: Session, rows: list[dict[str, Any]], instrument_id: int) -> int:
    """Set ``dps`` on the decisions event of each letter the rows match (same day and title);
    creates the event when the letter is stored but its event is not. Returns how many got a dps."""
    n = 0
    for r in rows:
        if r["dps"] is None or not r["day"]:
            continue
        day = _day(int(r["day"]))
        letters = session.scalars(
            select(CodalLetter).where(CodalLetter.instrument_id == instrument_id)
        ).all()
        hit = next(
            (
                x
                for x in letters
                if x.published_at is not None
                and abs((x.published_at.date() - day).days) <= 1
                and normalize_fa(x.title or "") == r["title"]
            ),
            None,
        )
        if hit is None:
            continue
        ev = session.scalars(
            select(CorporateEvent).where(CorporateEvent.tracing_no == hit.tracing_no)
        ).first()
        if ev is None:
            ev = CorporateEvent(
                instrument_id=instrument_id,
                type="agm_dividend",
                announced_at=day,
                tracing_no=hit.tracing_no,
                stage=DECISION_STAGE,
                title=hit.title,
                source=SOURCE,
                published_at=hit.published_at,
            )
            session.add(ev)
        ev.dps = r["dps"]
        n += 1
    return n


def _ins_codes(session: Session, symbols: list[str]) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for sym in symbols:
        row = session.execute(
            select(Instrument.id, Instrument.ins_code)
            .where(Instrument.symbol_fa == sym, Instrument.ins_code.is_not(None))
            .order_by(Instrument.id.desc())
        ).first()
        if row:
            out[sym] = (row[0], str(row[1]))
    return out


async def run(basket: Path, state_path: Path, top: int = 3000) -> dict[str, int]:
    state: dict[str, Any] = (
        json.loads(state_path.read_text("utf-8")) if state_path.exists() else {"done": []}
    )
    done = set(state["done"])
    stats = {"symbols": 0, "letters": 0, "dps": 0, "failed": 0}
    store = get_object_store()
    client = PoliteClient()
    try:
        with session_scope() as s:
            codes = _ins_codes(s, basket_symbols(basket))
        for sym, (iid, ins) in codes.items():
            if sym in done:
                continue
            fetched_at: datetime = utcnow()
            try:
                lst = await client.get(LIST_URL.format(top=top, ins=ins))
                dec = await client.get(DECISIONS_URL.format(ins=ins))
                letters = parse_feed(lst.content)
                rows = decisions_of(dec.content)
            except (FetchError, ValueError) as exc:
                log.warning("tsetmc codal %s: %s", sym, exc)
                stats["failed"] += 1
                continue
            with session_scope() as s:
                for url, resp in (
                    (LIST_URL.format(top=top, ins=ins), lst),
                    (DECISIONS_URL.format(ins=ins), dec),
                ):
                    store_raw_payload(
                        s,
                        store,
                        source=SOURCE,
                        source_url=url,
                        payload=resp.content,
                        fetched_at=fetched_at,
                        ext="json",
                        content_type="application/json",
                    )
                stats["letters"] += store_new(
                    s, letters, LIST_URL.format(top=top, ins=ins), fetched_at
                )
                s.flush()
                stats["dps"] += apply_decisions(s, rows, iid)
            done.add(sym)
            stats["symbols"] += 1
            state["done"] = sorted(done)
            state_path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
            log.info("tsetmc codal %s ok %s", sym, stats)
    finally:
        await client.aclose()
    return stats


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-tsetmc-codal")
    ap.add_argument("--basket", default="data/liquid-basket.json")
    ap.add_argument("--state", default="data/tsetmc-codal.json")
    ap.add_argument("--top", type=int, default=3000)
    a = ap.parse_args()
    print(asyncio.run(run(Path(a.basket), Path(a.state), a.top)))


if __name__ == "__main__":
    main()
