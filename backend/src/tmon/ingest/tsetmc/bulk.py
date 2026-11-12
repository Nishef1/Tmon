"""R0 data completion: the complete instrument list, share-count events and the full daily
history of every instrument in a few dozen requests.

Endpoint shapes come from the open-source ``tse-client`` (MIT, github.com/m-ahmadi/tse-client)
and were re-checked against live replies; they are recorded in ``endpoints.py``.

* ``t=Instrument`` lists every instrument ever listed, delisted ones included. Its ``DEven``
  column is NOT the last trade date (it is a listing-record date), so an instrument's exit is
  dated from its last price bar.
* ``t=ClosingPrices`` returns the history from 2001-03-21, 50 instruments per request. It also
  returns rows for days without trades (volume 0); the rest of the project stores traded days
  only (the per-instrument export drops the others), so those rows are counted and skipped.
  On every traded day the two sources agree to the last digit (checked on 4 instruments and
  4 296 overlapping bars).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.ingest.http import FetchError
from tmon.ingest.tsetmc import endpoints
from tmon.ingest.tsetmc.parsers import DailyBar, ParseError, normalize_fa, parse_client_types
from tmon.ingest.tsetmc.pipeline import (
    Ctx,
    _bar_rows,
    _client_rows,
    enrich_instrument,
    rebuild_adjustments,
)
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily, ShareChange
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

CHUNK = 50  # the service's own client caps a request at 59 instruments
EXIT_GAP_DAYS = 10  # last bar this much older than the newest bar in the DB = left the market


@dataclass(frozen=True)
class ListedInstrument:
    ins_code: str
    instrument_id: str  # IRO... style code
    latin_symbol: str
    latin_name: str
    company_code: str
    symbol: str
    name: str
    isin: str
    list_deven: str
    flow: str
    type_code: str  # YVal
    symbol_type: str  # CGdSVal A/I/O
    group_code: str  # CGrValCot
    market_code: str  # YMarNSC
    board_code: str  # CComVal
    sector_code: str  # CSecVal
    subsector_code: str  # CSoSecVal
    symbol_original: str | None


def _clean(text: str) -> str:
    return normalize_fa(text)


def parse_instrument_list(text: str) -> list[ListedInstrument]:
    out: list[ListedInstrument] = []
    for raw in text.split(";"):
        if not raw.strip():
            continue
        f = raw.split(",")
        if len(f) not in (18, 19):
            raise ParseError(f"instrument row has {len(f)} fields, expected 18 or 19")
        out.append(
            ListedInstrument(
                ins_code=f[0],
                instrument_id=f[1],
                latin_symbol=f[2],
                latin_name=f[3],
                company_code=f[4],
                symbol=_clean(f[5]),
                name=_clean(f[6]),
                isin=f[7],
                list_deven=f[8],
                flow=f[9],
                symbol_type=f[11],
                group_code=f[12],
                market_code=f[13],
                board_code=f[14],
                sector_code=f[15].strip(),
                subsector_code=f[16].strip(),
                type_code=f[17].strip(),
                symbol_original=_clean(f[18]) if len(f) > 18 and f[18].strip() else None,
            )
        )
    if not out:
        raise ParseError("empty instrument list")
    return out


@dataclass(frozen=True)
class ShareRow:
    idn: int
    ins_code: str
    date: date
    shares_new: int
    shares_old: int


def parse_share_changes(text: str) -> list[ShareRow]:
    parts = text.split("@")
    if len(parts) < 2:
        raise ParseError("InstrumentAndShare reply has no share section")
    out: list[ShareRow] = []
    for raw in parts[1].split(";"):
        if not raw.strip():
            continue
        f = raw.split(",")
        if len(f) != 5:
            raise ParseError(f"share row has {len(f)} fields, expected 5")
        out.append(
            ShareRow(
                int(f[0]),
                f[1],
                datetime.strptime(f[2], "%Y%m%d").date(),
                int(float(f[3])),
                int(float(f[4])),
            )
        )
    return out


def parse_closing_prices(text: str, n_items: int) -> tuple[list[list[DailyBar]], list[int]]:
    """One block per requested item. Returns ``(bars per item, zero-trade rows skipped per
    item)``. A reply with another block count is rejected rather than mis-assigned."""
    blocks = text.split("@")
    if len(blocks) != n_items:
        raise ParseError(f"expected {n_items} blocks, got {len(blocks)}")
    bars_out: list[list[DailyBar]] = []
    skipped: list[int] = []
    for block in blocks:
        bars: list[DailyBar] = []
        skip = 0
        for raw in block.split(";"):
            if not raw.strip():
                continue
            f = raw.split(",")
            if len(f) != 11:
                raise ParseError(f"closing-price row has {len(f)} fields, expected 11")
            trades, volume = int(float(f[4])), float(f[5])
            if trades == 0 and volume == 0:
                skip += 1
                continue
            bars.append(
                DailyBar(
                    date=datetime.strptime(f[1], "%Y%m%d").date(),
                    close=float(f[2]),
                    last=float(f[3]),
                    trades=trades,
                    volume=volume,
                    value=float(f[6]),
                    low=float(f[7]),
                    high=float(f[8]),
                    prev_close=float(f[9]),
                    open=float(f[10]),
                )
            )
        bars_out.append(bars)
        skipped.append(skip)
    return bars_out, skipped


async def sync_full_instrument_list(ctx: Ctx) -> dict[str, int]:
    """Register every listed-ever instrument; keep types already refined by enrichment."""
    url = endpoints.instrument_list_url()
    text, fetched_at = await ctx.fetch_text(url)
    listed = parse_instrument_list(text)
    existing = {i.ins_code: i for i in ctx.session.scalars(select(Instrument))}
    new_rows: list[dict[str, object]] = []
    touched = 0
    for li in listed:
        extra = {
            "company_code": li.company_code,
            "latin_symbol": li.latin_symbol,
            "latin_name": li.latin_name,
            "instrument_code": li.instrument_id,
            "list_deven": li.list_deven,
            "flow": li.flow,
            "list_type_code": li.type_code,
            "symbol_type": li.symbol_type,
            "group_code": li.group_code,
            "market_code": li.market_code,
            "board_code": li.board_code,
            "subsector_code": li.subsector_code,
            "symbol_original": li.symbol_original,
            "in_full_list": True,
        }
        ins = existing.get(li.ins_code)
        if ins is None:
            itype, matched = ctx.classifier.classify(
                group_title=None, name_fa=li.name, type_code=li.type_code
            )
            new_rows.append(
                {
                    "ins_code": li.ins_code,
                    "symbol_fa": li.symbol,
                    "name_fa": li.name,
                    "isin": li.isin or None,
                    "market": "IR",
                    "instrument_type": itype.value,
                    "sector_code": li.sector_code or None,
                    "tags": extra | ({} if matched else {"unclassified": True}),
                    "source_url": url,
                    "fetched_at": fetched_at,
                }
            )
        else:
            tags = dict(ins.tags or {})
            tags.update(extra)
            ins.tags = tags
            if not ins.sector_code and li.sector_code:
                ins.sector_code = li.sector_code
            if not ins.isin and li.isin:
                ins.isin = li.isin
            touched += 1
    n_new = upsert(ctx.session, Instrument, new_rows, conflict_columns=["ins_code"])
    ctx.session.flush()
    return {"listed": len(listed), "new": n_new, "updated": touched}


async def sync_share_changes(ctx: Ctx) -> int:
    url = endpoints.instrument_and_share_url()
    text, fetched_at = await ctx.fetch_text(url)
    rows = parse_share_changes(text)
    ids = dict(ctx.session.execute(select(Instrument.ins_code, Instrument.id)).all())
    n = upsert(
        ctx.session,
        ShareChange,
        [
            {
                "idn": r.idn,
                "ins_code": r.ins_code,
                "instrument_id": ids.get(r.ins_code),
                "date": r.date,
                "shares_new": r.shares_new,
                "shares_old": r.shares_old,
                "source_url": url,
                "fetched_at": fetched_at,
            }
            for r in rows
        ],
    )
    ctx.session.flush()
    return n


async def load_full_history(
    ctx: Ctx,
    instruments: list[Instrument],
    *,
    start_deven: int = endpoints.FIRST_POSSIBLE_DEVEN,
) -> dict[str, int]:
    """Daily bars from ``start_deven`` for the given instruments, 50 per request."""
    out = {"requests": 0, "instruments": 0, "bars": 0, "zero_trade_skipped": 0, "failed": 0}
    for i in range(0, len(instruments), CHUNK):
        chunk = instruments[i : i + CHUNK]
        items = [
            (ins.ins_code, start_deven, (ins.tags or {}).get("market_code", "NO") != "NO")
            for ins in chunk
        ]
        url = endpoints.closing_prices_url(items)
        try:
            text, fetched_at = await ctx.fetch_text(url, ext="txt")
            bars, skipped = parse_closing_prices(text, len(chunk))
        except (FetchError, ParseError) as exc:
            ctx.session.rollback()
            out["failed"] += len(chunk)
            log.error("closing-prices chunk %d failed: %s", i // CHUNK, exc)
            continue
        out["requests"] += 1
        for ins, b, sk in zip(chunk, bars, skipped, strict=True):
            if b:
                out["bars"] += upsert(
                    ctx.session, PriceDaily, _bar_rows(ins.id, b, url, fetched_at, None)
                )
            out["instruments"] += 1
            out["zero_trade_skipped"] += sk
        ctx.session.flush()
        for ins, b in zip(chunk, bars, strict=True):
            if b:
                rebuild_adjustments(ctx.session, ins.id)
        ctx.session.commit()
        log.info("history chunk %d/%d %s", i // CHUNK + 1, -(-len(instruments) // CHUNK), out)
    return out


DETAIL_TYPES = (
    "stock",
    "other",
    "commodity_certificate",
    "etf_equity",
    "etf_fixed_income",
    "etf_mixed",
    "etf_commodity",
    "etf_leveraged",
)


async def fill_details(ctx: Ctx, *, limit: int | None = None) -> dict[str, int]:
    """For instruments that have bars but were never enriched (group, sector, type) or have no
    real/legal (حقیقی/حقوقی) history, fetch what is missing. An instrument is marked
    ``ct_checked`` once its client-type request was answered, so an empty answer is not
    retried on every run."""
    have_bars = set(ctx.session.scalars(select(PriceDaily.instrument_id).distinct()))
    have_ct = set(ctx.session.scalars(select(ClientTypeDaily.instrument_id).distinct()))
    todo = [
        i
        for i in ctx.session.scalars(select(Instrument).order_by(Instrument.id))
        if i.id in have_bars
        and i.instrument_type in DETAIL_TYPES
        and (
            "group_title" not in (i.tags or {})
            or (i.id not in have_ct and not (i.tags or {}).get("ct_checked"))
        )
    ]
    if limit:
        todo = todo[:limit]
    out = {"todo": len(todo), "enriched": 0, "client_rows": 0, "no_client_types": 0, "failed": 0}
    for n, ins in enumerate(todo, 1):
        try:
            if "group_title" not in (ins.tags or {}):
                await enrich_instrument(ctx, ins)
                out["enriched"] += 1
            if ins.id not in have_ct:
                c_url = endpoints.client_types_url(ins.ins_code)
                c_text, c_at = await ctx.fetch_text(c_url)
                rows = parse_client_types(c_text)
                k = upsert(
                    ctx.session, ClientTypeDaily, _client_rows(ins.id, rows, c_url, c_at, None)
                )
                out["client_rows"] += k
                out["no_client_types"] += 0 if k else 1
                ins.tags = {**(ins.tags or {}), "ct_checked": True}
            ctx.session.commit()
        except (FetchError, ParseError) as exc:
            ctx.session.rollback()
            out["failed"] += 1
            log.warning("details for %s failed: %s", ins.symbol_fa, exc)
        if n % 25 == 0:
            log.info("details %d/%d %s", n, len(todo), out)
    return out


def flag_nav_lines(session: Session) -> int:
    """Fund pseudo-instruments such as ``سرو2``: a second line of a fund (same name as the real
    unit ``سرو``, symbol + "2") whose last bar is a placeholder price (close <= 10) against a
    reference price of the real NAV scale (prev_close >= 100). It is not a tradable unit, so it is
    tagged ``nav_line`` and typed ``other`` (kept, never ranked). Pattern found in the data audit,
    verified on all 83 matches; the ``4`` lines (آوند4, ...) carry real prices: left alone."""
    by_key = {(i.symbol_fa, i.name_fa): i for i in session.scalars(select(Instrument))}
    changed = 0
    for ins in list(by_key.values()):
        if not ins.symbol_fa.endswith("2") or not ins.instrument_type.startswith("etf"):
            continue
        if (ins.symbol_fa[:-1], ins.name_fa) not in by_key:
            continue
        row = session.execute(
            select(PriceDaily.close, PriceDaily.prev_close)
            .where(PriceDaily.instrument_id == ins.id)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        ).first()
        if row is None or row[0] is None or not (row[0] <= 10 and (row[1] or 0) >= 100):
            continue
        ins.tags = {**(ins.tags or {}), "nav_line": True}
        ins.instrument_type = "other"
        changed += 1
    session.flush()
    return changed


def flag_alt_lines(session: Session) -> int:
    """Alternate trading lines of a share (``شکربن3`` next to ``شکربن``): same company name, the
    plain symbol plus a digit, absent from the official instrument list, placeholder group "-'".
    They are the same company, not another stock, so counting them would duplicate it in every
    universe and ranking. Tagged ``alt_line`` and typed ``other``. All 463 stock-typed rows with
    this shape matched a plain-symbol sibling by name when audited."""
    by_key = {(i.symbol_fa, i.name_fa): i for i in session.scalars(select(Instrument))}
    changed = 0
    for ins in list(by_key.values()):
        tags = ins.tags or {}
        if ins.instrument_type != "stock" or tags.get("in_full_list"):
            continue
        if tags.get("discovered_by") == "search" or not ins.symbol_fa[-1:].isdigit():
            continue
        if (ins.symbol_fa.rstrip("0123456789"), ins.name_fa) not in by_key:
            continue
        ins.tags = {**tags, "alt_line": True}
        ins.instrument_type = "other"
        changed += 1
    session.flush()
    return changed


def date_exits(session: Session) -> int:
    """Set ``delisted_at`` from the last bar for instruments that stopped trading; clear it
    for any that traded again."""
    latest = session.scalar(select(func.max(PriceDaily.date)))
    if latest is None:
        return 0
    last = dict(
        session.execute(
            select(PriceDaily.instrument_id, func.max(PriceDaily.date)).group_by(
                PriceDaily.instrument_id
            )
        ).all()
    )
    changed = 0
    for ins in session.scalars(select(Instrument)):
        d = last.get(ins.id)
        if d is None:
            continue
        gone = (latest - d).days > EXIT_GAP_DAYS
        new = d if gone else None
        if ins.delisted_at != new:
            ins.delisted_at = new
            changed += 1
    session.flush()
    return changed


def main() -> None:
    import argparse
    import asyncio

    from tmon.core.db import session_scope
    from tmon.core.logging import configure_logging
    from tmon.ingest.http import PoliteClient
    from tmon.ingest.tsetmc.classify import get_classifier
    from tmon.ingest.tsetmc.pipeline import flag_market_halts, refresh_trading_calendar
    from tmon.storage.objectstore import get_object_store

    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-bulk")
    ap.add_argument("--limit", type=int, default=None, help="only the first N instruments")
    ap.add_argument("--skip-list", action="store_true")
    ap.add_argument("--details", action="store_true", help="only enrich + client types")
    a = ap.parse_args()

    async def run() -> None:
        client = PoliteClient()
        try:
            with session_scope() as s:
                ctx = Ctx(s, client, get_object_store(), get_classifier())
                if a.details:
                    print("details", await fill_details(ctx, limit=a.limit))
                    return
                if not a.skip_list:
                    print("list", await sync_full_instrument_list(ctx))
                    print("shares", await sync_share_changes(ctx))
                    s.commit()
                todo = list(s.scalars(select(Instrument).order_by(Instrument.id)))
                if a.limit:
                    todo = todo[: a.limit]
                print("history", await load_full_history(ctx, todo))
                print("exits dated", date_exits(s))
                print("nav lines", flag_nav_lines(s), "alt lines", flag_alt_lines(s))
                flag_market_halts(s)
                refresh_trading_calendar(s)
                s.commit()
        finally:
            await client.aclose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
