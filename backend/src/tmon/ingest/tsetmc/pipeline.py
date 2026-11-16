"""TSETMC ingestion orchestration (M1).

Order for every payload: fetch -> store raw in object storage -> parse -> upsert with
``source_url`` and ``fetched_at``. Parsers never touch the network.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import polars as pl
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import tehran_today, utcnow
from tmon.domain.calendar import build_calendar, halt_windows
from tmon.domain.enums import InstrumentType
from tmon.domain.rules import RuleBook
from tmon.features.adjustment import detect_adjustments
from tmon.ingest.http import FetchError, PoliteClient
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.classify import Classifier, get_classifier
from tmon.storage.models import (
    ClientTypeDaily,
    Holding,
    Instrument,
    PriceAdjustment,
    PriceDaily,
    RawPayload,
    TradingCalendar,
)
from tmon.storage.objectstore import ObjectStore, get_object_store, store_raw_payload
from tmon.storage.repositories import upsert
from tmon.storage.seed import seed_market_rules

log = logging.getLogger(__name__)

SOURCE = "tsetmc"
REFETCH_OVERLAP_DAYS = 7  # re-read the tail so late corrections overwrite stored rows


@dataclass
class Ctx:
    session: Session
    client: PoliteClient
    store: ObjectStore
    classifier: Classifier
    # ins_code -> traded value in the latest market-watch snapshot (filled by sync_instruments);
    # used to pick the most liquid instruments for a limited backfill.
    liquidity: dict[str, float] = field(default_factory=dict)

    async def fetch_text(
        self, url: str, *, ext: str = "txt", keep_raw: bool = True
    ) -> tuple[str, datetime]:
        fetched_at = utcnow()
        resp = await self.client.get(url)
        payload = resp.content
        if keep_raw:  # intraday polling keeps only a sample of raw payloads (see intraday.py)
            store_raw_payload(
                self.session,
                self.store,
                source=SOURCE,
                source_url=url,
                payload=payload,
                fetched_at=fetched_at,
                ext=ext,
            )
        return payload.decode("utf-8", errors="replace"), fetched_at


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #


async def sync_instruments(ctx: Ctx) -> int:
    url = endpoints.MARKET_WATCH_INIT
    text, fetched_at = await ctx.fetch_text(url)
    watch = parsers.parse_market_watch_init(text)
    try:
        ctx.liquidity = {q.ins_code: q.value for q in parsers.parse_market_watch_quotes(text)}
    except parsers.ParseError:  # quotes are only used to rank; the instrument list still stands
        ctx.liquidity = {}

    existing = dict(
        ctx.session.execute(select(Instrument.ins_code, Instrument.instrument_type)).all()
    )
    rows = []
    for w in watch:
        itype, matched = ctx.classifier.classify(group_title=None, name_fa=w.name_fa)
        row: dict[str, object] = {
            "ins_code": w.ins_code,
            "symbol_fa": w.symbol_fa,
            "name_fa": w.name_fa,
            "isin": w.isin or None,
            "market": "IR",
            "source_url": url,
            "fetched_at": fetched_at,
        }
        if w.ins_code not in existing:  # never overwrite a type refined by enrichment
            row["instrument_type"] = itype.value
            row["tags"] = {} if matched else {"unclassified": True}
        rows.append(row)
    # two passes keep new-row defaults without clobbering enriched columns
    new_rows = [r for r in rows if "instrument_type" in r]
    old_rows = [r for r in rows if "instrument_type" not in r]
    n = upsert(ctx.session, Instrument, new_rows, conflict_columns=["ins_code"])
    n += upsert(ctx.session, Instrument, old_rows, conflict_columns=["ins_code"])
    log.info("instrument list: %d rows (%d new)", n, len(new_rows))
    return n


async def enrich_instrument(ctx: Ctx, instrument: Instrument) -> None:
    url = endpoints.instrument_info_url(instrument.ins_code)
    text, fetched_at = await ctx.fetch_text(url, ext="json")
    info = parsers.parse_instrument_info(text)
    itype, matched = ctx.classifier.classify(
        group_title=info.group_title,
        name_fa=info.name_fa or instrument.name_fa,
        board=info.flow_title,
        type_code=info.type_code,
        fund_desc=info.fund_desc,
    )
    instrument.sector_code = info.sector_code
    instrument.board = info.flow_title
    instrument.isin = info.isin or instrument.isin
    instrument.instrument_type = itype.value
    tags = dict(instrument.tags or {})
    tags.update(
        {
            "group_code": info.group_code,
            "group_title": info.group_title,
            "sector_title": info.sector_title,
            "base_volume": info.base_volume,
            "shares": info.shares,
            "type_code": info.type_code,
            "fund_desc": info.fund_desc,
            "eps": info.eps,
            "sector_pe": info.sector_pe,
            "week_min": info.week_min,
            "week_max": info.week_max,
            "year_min": info.year_min,
            "year_max": info.year_max,
        }
    )
    if matched:
        tags.pop("unclassified", None)
    else:
        tags["unclassified"] = True
    instrument.tags = tags
    instrument.source_url = url
    instrument.fetched_at = fetched_at


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #


def _bar_rows(
    instrument_id: int,
    bars: list[parsers.DailyBar],
    url: str,
    fetched_at: datetime,
    since: date | None,
) -> list[dict[str, object]]:
    return [
        {
            "instrument_id": instrument_id,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "last": b.last,
            "prev_close": b.prev_close,
            "volume": b.volume,
            "value": b.value,
            "trades": b.trades,
            "source_url": url,
            "fetched_at": fetched_at,
        }
        for b in bars
        if since is None or b.date >= since
    ]


def _client_rows(
    instrument_id: int,
    rows: list[parsers.ClientTypeRow],
    url: str,
    fetched_at: datetime,
    since: date | None,
) -> list[dict[str, object]]:
    return [
        {
            "instrument_id": instrument_id,
            "date": r.date,
            "buy_count_i": r.buy_count_i,
            "buy_count_n": r.buy_count_n,
            "sell_count_i": r.sell_count_i,
            "sell_count_n": r.sell_count_n,
            "buy_volume_i": r.buy_volume_i,
            "buy_volume_n": r.buy_volume_n,
            "sell_volume_i": r.sell_volume_i,
            "sell_volume_n": r.sell_volume_n,
            "buy_value_i": r.buy_value_i,
            "buy_value_n": r.buy_value_n,
            "sell_value_i": r.sell_value_i,
            "sell_value_n": r.sell_value_n,
            "source_url": url,
            "fetched_at": fetched_at,
        }
        for r in rows
        if since is None or r.date >= since
    ]


def rebuild_adjustments(session: Session, instrument_id: int) -> int:
    """Re-derive adjustment events for one instrument from its stored raw bars."""
    rows = session.execute(
        select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close, PriceDaily.prev_close)
        .where(PriceDaily.instrument_id == instrument_id)
        .order_by(PriceDaily.date)
    ).all()
    if not rows:
        return 0
    df = pl.DataFrame(
        {
            "instrument_id": [r[0] for r in rows],
            "date": [r[1] for r in rows],
            "close": [float(r[2]) if r[2] is not None else None for r in rows],
            "prev_close": [float(r[3]) if r[3] is not None else None for r in rows],
        }
    )
    events = detect_adjustments(df)
    session.query(PriceAdjustment).filter(PriceAdjustment.instrument_id == instrument_id).delete()
    return upsert(
        session,
        PriceAdjustment,
        [
            {
                "instrument_id": e["instrument_id"],
                "date": e["date"],
                "close_before": e["close_before"],
                "price_after": e["price_after"],
                "adj_factor": e["adj_factor"],
                "derived_from": "prev_close_gap",
            }
            for e in events.iter_rows(named=True)
        ],
    )


async def ingest_history(
    ctx: Ctx, instrument: Instrument, *, since: date | None = None, with_client_types: bool = True
) -> dict[str, int]:
    """Fetch and store daily bars (+ client types) for one instrument."""
    stats = {"bars": 0, "client_rows": 0}
    url = endpoints.daily_history_url(instrument.ins_code)
    text, fetched_at = await ctx.fetch_text(url, ext="csv")
    bars = parsers.parse_daily_history(text)
    stats["bars"] = upsert(
        ctx.session, PriceDaily, _bar_rows(instrument.id, bars, url, fetched_at, since)
    )

    if with_client_types:
        c_url = endpoints.client_types_url(instrument.ins_code)
        try:
            c_text, c_fetched = await ctx.fetch_text(c_url)
            c_rows = parsers.parse_client_types(c_text)
            stats["client_rows"] = upsert(
                ctx.session,
                ClientTypeDaily,
                _client_rows(instrument.id, c_rows, c_url, c_fetched, since),
            )
        except (FetchError, parsers.ParseError) as exc:
            log.warning("client types failed for %s: %s", instrument.symbol_fa, exc)

    ctx.session.flush()
    rebuild_adjustments(ctx.session, instrument.id)
    return stats


async def fill_today_client_types(ctx: Ctx, today: date | None = None) -> int:
    """Today's real/legal split for every instrument that traded today but whose history does
    not carry today yet. Individual buying power is the strongest signal of the ranking, so
    without this the evening ranking scored most symbols on an older day's flow. Only today:
    the market-wide endpoint always describes the current session. The next run's history
    fetch overwrites these rows with TSETMC's published ones (values included)."""
    day = today or tehran_today()
    traded = dict(
        ctx.session.execute(
            select(Instrument.ins_code, Instrument.id)
            .join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
            .where(PriceDaily.date == day, PriceDaily.volume > 0)
        ).all()
    )
    if not traded:
        return 0
    have = set(
        ctx.session.scalars(
            select(ClientTypeDaily.instrument_id).where(ClientTypeDaily.date == day)
        )
    )
    missing = {code: iid for code, iid in traded.items() if iid not in have}
    if not missing:
        return 0
    url = endpoints.CLIENT_TYPES_ALL
    text, fetched_at = await ctx.fetch_text(url, ext="json")
    rows = parsers.parse_client_types_all(text, day)
    out: list[dict[str, object]] = []
    for code, iid in missing.items():
        r = rows.get(code)
        if r is not None and r.buy_volume_i + r.buy_volume_n > 0:
            out.extend(_client_rows(iid, [r], url, fetched_at, None))
    n = upsert(ctx.session, ClientTypeDaily, out) if out else 0
    ctx.session.flush()
    log.info("today's client types: %d of %d missing filled", n, len(missing))
    return n


# --------------------------------------------------------------------------- #
# Halts and calendar
# --------------------------------------------------------------------------- #


def flag_market_halts(session: Session) -> int:
    rules = RuleBook.from_session(session)
    flagged = 0
    for w in halt_windows(rules):
        res = session.execute(
            update(PriceDaily)
            .where(PriceDaily.date.between(w.start, w.end))
            .values(market_halt=True)
        )
        flagged += getattr(res, "rowcount", 0) or 0
    return flagged


def refresh_trading_calendar(session: Session) -> int:
    rows = session.execute(
        select(PriceDaily.date, func.count()).where(PriceDaily.volume > 0).group_by(PriceDaily.date)
    ).all()
    counts = pl.DataFrame(
        {"date": [r[0] for r in rows], "n_traded": [int(r[1]) for r in rows]},
        schema={"date": pl.Date, "n_traded": pl.Int64},
    )
    cal = build_calendar(counts, halt_windows(RuleBook.from_session(session)))
    return upsert(session, TradingCalendar, list(cal.iter_rows(named=True)))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def refresh_info(ctx: Ctx) -> dict[str, int]:
    """Re-read GetInstrumentInfo for every stock that traded in the last 30 days, so EPS and the
    group P/E follow new financial statements. Instruments that fail are skipped, not fatal."""
    last = ctx.session.scalar(select(func.max(PriceDaily.date)))
    if last is None:
        return {"refreshed": 0, "failed": 0}
    ids = set(
        ctx.session.scalars(
            select(PriceDaily.instrument_id)
            .where(PriceDaily.date >= last - timedelta(days=30))
            .distinct()
        )
    )
    stocks = [
        i
        for i in ctx.session.scalars(select(Instrument).where(Instrument.delisted_at.is_(None)))
        if i.id in ids and i.instrument_type == "stock"
    ]
    done = failed = 0
    for ins in stocks:
        try:
            await enrich_instrument(ctx, ins)
            done += 1
            if done % 25 == 0:
                ctx.session.commit()
        except (FetchError, parsers.ParseError, OperationalError) as exc:
            ctx.session.rollback()
            failed += 1
            log.error("info refresh failed for %s: %s", ins.symbol_fa, exc)
    ctx.session.commit()
    return {"refreshed": done, "failed": failed}


def _tradable_instruments(session: Session, classifier: Classifier) -> list[Instrument]:
    rows = session.scalars(select(Instrument).where(Instrument.delisted_at.is_(None))).all()
    return [i for i in rows if classifier.is_tradable(i.instrument_type)]


def _held_extra(session: Session, classifier: Classifier) -> list[Instrument]:
    """Instruments someone holds in a portfolio that the market-wide run skips (rights, bonds,
    options): their prices are still needed to value the portfolio."""
    rows = session.scalars(
        select(Instrument).where(Instrument.id.in_(select(Holding.instrument_id).distinct()))
    ).all()
    return [i for i in rows if not classifier.is_tradable(i.instrument_type)]


async def backfill(
    ctx: Ctx,
    *,
    since: date | None = None,
    limit: int | None = None,
    enrich: bool = True,
    missing_only: bool = False,
) -> dict[str, int]:
    seed_market_rules(ctx.session)
    await sync_instruments(ctx)
    ctx.session.commit()
    instruments = _tradable_instruments(ctx.session, ctx.classifier)
    if limit:  # the most liquid first, so a short run covers instruments that actually trade
        instruments.sort(key=lambda i: ctx.liquidity.get(i.ins_code, 0.0), reverse=True)
        instruments = instruments[:limit]
    if missing_only:  # resume: skip instruments that already have price history
        have = set(ctx.session.scalars(select(PriceDaily.instrument_id).distinct()))
        instruments = [i for i in instruments if i.id not in have]
    totals = {"instruments": 0, "bars": 0, "client_rows": 0, "failed": 0}
    for ins in instruments:
        try:
            if enrich:
                await enrich_instrument(ctx, ins)
            s = await ingest_history(ctx, ins, since=since)
            totals["bars"] += s["bars"]
            totals["client_rows"] += s["client_rows"]
            totals["instruments"] += 1
            ctx.session.commit()  # a crash hours in must not lose the instruments already done
        except (FetchError, parsers.ParseError, OperationalError) as exc:
            ctx.session.rollback()
            totals["failed"] += 1
            log.error("ingest failed for %s (%s): %s", ins.symbol_fa, ins.ins_code, exc)
    flag_market_halts(ctx.session)
    refresh_trading_calendar(ctx.session)
    return totals


def reclassify_instruments(session: Session, classifier: Classifier) -> dict[str, int]:
    """Re-run the classifier over stored instruments (no network): uses the group title and board
    that enrichment saved. Needed whenever ``config/instrument_types.yaml`` changes."""
    changed = 0
    for ins in session.scalars(select(Instrument)):
        t = ins.tags or {}
        itype, matched = classifier.classify(
            group_title=t.get("group_title"),
            name_fa=ins.name_fa,
            board=ins.board,
            type_code=t.get("type_code") or t.get("list_type_code"),
            fund_desc=t.get("fund_desc"),
        )
        tags = dict(ins.tags or {})
        if tags.get("nav_line") or tags.get("alt_line"):  # pseudo / alternate lines (bulk.flag_*)
            itype, matched = InstrumentType.OTHER, True
        if matched:
            tags.pop("unclassified", None)
        else:
            tags["unclassified"] = True
        if itype.value != ins.instrument_type or tags != (ins.tags or {}):
            changed += int(itype.value != ins.instrument_type)
            ins.instrument_type = itype.value
            ins.tags = tags
    session.flush()
    counts = dict(
        session.execute(
            select(Instrument.instrument_type, func.count()).group_by(Instrument.instrument_type)
        ).all()
    )
    return {"changed": changed, **{str(k): int(v) for k, v in counts.items()}}


async def end_of_day(ctx: Ctx, *, full: bool = False) -> dict[str, int]:
    """Daily update. Default (fast): prices of the last ``REFETCH_OVERLAP_DAYS`` for all
    instruments in batches of 50 (service.tsetmc.com), today's real/legal flows from the one
    market-wide call, and a per-instrument flow fetch only for days that still miss flows.
    ``full=True`` re-reads every instrument's whole history and flows one by one (about an hour);
    run it weekly so TSETMC's published flows replace the same-day market-wide ones."""
    since = utcnow().date() - timedelta(days=REFETCH_OVERLAP_DAYS)
    await sync_instruments(ctx)
    ctx.session.flush()
    held = _held_extra(ctx.session, ctx.classifier)
    if full:
        totals = await _end_of_day_full(ctx, since, held)
    else:
        totals = await _end_of_day_fast(ctx, since, held)
    # the bulk feed can publish today hours late; the per-symbol closing endpoint has it already
    from tmon.ingest.tsetmc.today_cdn import fill_today

    try:
        totals["bars_from_closing_info"] = fill_today(ctx.session)["stored"]
    except Exception:  # a failing fallback must not stop the rest of the cycle
        log.exception("filling today from the closing endpoint failed")
    try:
        totals["client_rows_today"] = await fill_today_client_types(ctx)
    except (FetchError, parsers.ParseError) as exc:
        log.error("today's client types failed: %s", exc)
    flag_market_halts(ctx.session)
    refresh_trading_calendar(ctx.session)
    return totals


async def _end_of_day_full(ctx: Ctx, since: date, held: list[Instrument]) -> dict[str, int]:
    totals = {"instruments": 0, "bars": 0, "client_rows": 0, "failed": 0}
    for ins in [*_tradable_instruments(ctx.session, ctx.classifier), *held]:
        try:
            first = (
                ins in held
                and ctx.session.scalar(
                    select(PriceDaily.date).where(PriceDaily.instrument_id == ins.id).limit(1)
                )
                is None
            )
            s = await ingest_history(ctx, ins, since=None if first else since)
            totals["bars"] += s["bars"]
            totals["client_rows"] += s["client_rows"]
            totals["instruments"] += 1
        except (FetchError, parsers.ParseError) as exc:
            totals["failed"] += 1
            log.error("EOD failed for %s: %s", ins.symbol_fa, exc)
    return totals


async def _end_of_day_fast(ctx: Ctx, since: date, held: list[Instrument]) -> dict[str, int]:
    from tmon.ingest.tsetmc.bulk import load_full_history  # bulk imports this module

    totals = {"instruments": 0, "bars": 0, "client_rows": 0, "failed": 0}
    everyone = [*_tradable_instruments(ctx.session, ctx.classifier), *held]
    has_bars = set(ctx.session.scalars(select(PriceDaily.instrument_id).distinct()))
    new = [i for i in held if i.id not in has_bars]  # never fetched: whole history, not a week
    recent = [i for i in everyone if i not in new]
    start = int(since.strftime("%Y%m%d"))
    for group, begin in ((recent, start), (new, endpoints.FIRST_POSSIBLE_DEVEN)):
        if not group:
            continue
        s = await load_full_history(ctx, group, start_deven=begin)
        totals["bars"] += s["bars"]
        totals["instruments"] += s["instruments"]
        totals["failed"] += s["failed"]
    ctx.session.commit()
    for ins in _missing_flows(ctx.session, everyone, since):
        try:
            c_url = endpoints.client_types_url(ins.ins_code)
            c_text, c_fetched = await ctx.fetch_text(c_url)
            c_rows = parsers.parse_client_types(c_text)
            totals["client_rows"] += upsert(
                ctx.session, ClientTypeDaily, _client_rows(ins.id, c_rows, c_url, c_fetched, since)
            )
        except (FetchError, parsers.ParseError) as exc:
            log.warning("client types failed for %s: %s", ins.symbol_fa, exc)
    ctx.session.flush()
    return totals


def _missing_flows(
    session: Session, instruments: list[Instrument], since: date
) -> list[Instrument]:
    """Instruments that traded on a day since ``since`` (before today, which the market-wide call
    covers) but have no real/legal row for that day."""
    today = tehran_today()
    traded = {
        (iid, d)
        for iid, d in session.execute(
            select(PriceDaily.instrument_id, PriceDaily.date).where(
                PriceDaily.date >= since, PriceDaily.date < today, PriceDaily.volume > 0
            )
        )
    }
    have = {
        (iid, d)
        for iid, d in session.execute(
            select(ClientTypeDaily.instrument_id, ClientTypeDaily.date).where(
                ClientTypeDaily.date >= since
            )
        )
    }
    ids = {iid for iid, _ in traded - have}
    return [i for i in instruments if i.id in ids]


# --------------------------------------------------------------------------- #
# Sync entry points (daily cycle / CLI)
# --------------------------------------------------------------------------- #


async def _run(fn_name: str, **kwargs: object) -> dict[str, int]:
    client = PoliteClient()
    try:
        with session_scope() as session:
            ctx = Ctx(session, client, get_object_store(), get_classifier())
            if fn_name == "backfill":
                return await backfill(ctx, **kwargs)  # type: ignore[arg-type]
            if fn_name == "info":
                return await refresh_info(ctx)
            if fn_name == "eod":
                return await end_of_day(ctx, full=bool(kwargs.get("full")))
            if fn_name == "risk_free":
                from tmon.ingest.tsetmc.risk_free import compute_risk_free, ingest_treasury_bills

                out = await ingest_treasury_bills(ctx)
                out["rf_rows"] = compute_risk_free(ctx.session)
                ctx.session.commit()
                return out
            if fn_name == "adjustment_check":
                from tmon.ingest.tsetmc.adjcheck import run_check

                return await run_check(ctx, str(kwargs["out"]))
            if fn_name == "shareholders":
                from tmon.ingest.tsetmc.shareholders import ingest_shareholders

                return await ingest_shareholders(ctx, **kwargs)  # type: ignore[arg-type]
            if fn_name == "indices":
                from tmon.ingest.tsetmc.indices import ingest_indices

                return await ingest_indices(ctx)
            n = await sync_instruments(ctx)
            return {"instruments": n}
    finally:
        await client.aclose()


def ingest_end_of_day(full: bool = False) -> dict[str, int]:
    return asyncio.run(_run("eod", full=full))


def run_info_refresh() -> dict[str, int]:
    return asyncio.run(_run("info"))


def run_adjustment_check(out: str) -> dict[str, int]:
    return asyncio.run(_run("adjustment_check", out=out))


def run_risk_free() -> dict[str, int]:
    return asyncio.run(_run("risk_free"))


def run_shareholders(limit: int | None = None) -> dict[str, int]:
    return asyncio.run(_run("shareholders", limit=limit))


def run_indices() -> dict[str, int]:
    return asyncio.run(_run("indices"))


def backfill_info_tags(session: Session, store: ObjectStore) -> int:
    """Copy the type code and fund description into ``tags`` from the latest stored
    GetInstrumentInfo payload of each instrument (no network). Needed once for instruments
    enriched before these fields were kept."""
    latest: dict[str, str] = {}
    rows = session.execute(
        select(RawPayload.source_url, RawPayload.object_key)
        .where(RawPayload.source_url.like("%GetInstrumentInfo/%"))
        .order_by(RawPayload.fetched_at)
    )
    for url, key in rows:
        latest[url.rstrip("/").rsplit("/", 1)[-1]] = key
    bucket = get_settings().minio_raw_bucket
    n = 0
    for ins in session.scalars(select(Instrument).where(Instrument.ins_code.in_(list(latest)))):
        try:
            info = parsers.parse_instrument_info(store.get(bucket, latest[ins.ins_code]).decode())
        except (OSError, parsers.ParseError, ValueError) as exc:
            log.warning("info payload unreadable for %s: %s", ins.ins_code, exc)
            continue
        tags = dict(ins.tags or {})
        new = {
            "type_code": info.type_code,
            "fund_desc": info.fund_desc,
            "eps": info.eps,
            "sector_pe": info.sector_pe,
            "base_volume": info.base_volume,
            "shares": info.shares,
            "week_min": info.week_min,
            "week_max": info.week_max,
            "year_min": info.year_min,
            "year_max": info.year_max,
        }
        if any(tags.get(k) != v for k, v in new.items()):
            tags.update(new)
            ins.tags = tags
            n += 1
    session.flush()
    return n


def run_reclassify() -> dict[str, int]:
    with session_scope() as session:
        tagged = backfill_info_tags(session, get_object_store())
        return {"info_tags_backfilled": tagged, **reclassify_instruments(session, get_classifier())}


def run_backfill(
    *, since: date | None = None, limit: int | None = None, missing_only: bool = False
) -> dict[str, int]:
    return asyncio.run(_run("backfill", since=since, limit=limit, missing_only=missing_only))
