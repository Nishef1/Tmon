from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tmon.api.book import book_out
from tmon.api.routers.recommendations import instrument_out, signal_out
from tmon.api.schemas import (
    AgmDecisionOut,
    AgmInputOut,
    BookLevelOut,
    Candle,
    CodalLetterOut,
    CorporateEventOut,
    FeatureValue,
    InstrumentBookOut,
    InstrumentDetail,
    LiveFlowOut,
    LiveOut,
    ShareholderOut,
    SymbolNewsOut,
)
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import TEHRAN, tehran_today, utcnow
from tmon.domain.agm import AgmInputs, hold_or_sell, monthly_from_annual
from tmon.domain.rules import CostModel, MissingRuleError, RuleBook
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import get_feature_set
from tmon.ingest.tsetmc.risk_free import SERIES as RF_SERIES
from tmon.storage.models import (
    CodalLetter,
    CorporateEvent,
    FeatureRow,
    Instrument,
    IntradaySnapshot,
    MacroSeries,
    NewsRaw,
    OrderBookSnapshot,
    PriceDaily,
    Shareholder,
    Signal,
)

router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

# Features shown on the instrument page; each has a glossary entry in the frontend.
SHOWN_FEATURES = (
    "rsi_14", "macd_hist_pct", "adx_14", "atr_14_pct", "bb_pct_b", "vwap_gap",
    "ind_buy_power", "ind_net_flow_ratio", "rel_volume", "smart_money_flag",
    "mkt_ret_ew", "breadth",
)  # fmt: skip

LETTERS_SHOWN = 30  # latest Codal letters on the instrument page
EVENTS_SHOWN = 20  # latest Codal events on the instrument page
STALE_AFTER_SECONDS = 300  # a snapshot older than this is shown as stale

PRICE_FIELDS = ("open", "high", "low", "close", "last", "prev_close", "volume")


@router.get("/instruments/{instrument_id}", response_model=InstrumentDetail)
def instrument_detail(
    instrument_id: int,
    session: SessionDep,
    days: Annotated[int, Query(ge=20, le=1500)] = 250,
) -> InstrumentDetail:
    """Adjusted daily candles (never raw prices), the latest stored features and this symbol's
    published signals."""
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")

    rows = session.execute(
        select(PriceDaily)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.market_halt.is_(False))
        .order_by(PriceDaily.date.desc())
        .limit(days + 1)
    ).scalars()
    data: dict[str, list[object]] = {"instrument_id": [], "date": []}
    data.update({f: [] for f in PRICE_FIELDS})
    for r in reversed(list(rows)):  # I/O boundary: at most `days` rows of one symbol
        data["instrument_id"].append(r.instrument_id)
        data["date"].append(r.date)
        for f in PRICE_FIELDS:
            v = getattr(r, f)
            data[f].append(None if v is None else float(v))
    candles: list[Candle] = []
    if data["date"]:
        raw = pl.DataFrame(
            data,
            schema={
                "instrument_id": pl.Int64,
                "date": pl.Date,
                **dict.fromkeys(PRICE_FIELDS, pl.Float64),
            },
        )
        adj = apply_adjustments(raw).tail(days)
        candles = [
            Candle(date=d, open=o, high=h, low=lo, close=c, volume=v)
            for d, o, h, lo, c, v in adj.select(
                "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"
            ).iter_rows()
        ]

    fs = get_feature_set("D1")
    frow = session.scalars(
        select(FeatureRow)
        .where(FeatureRow.instrument_id == instrument_id, FeatureRow.feature_set_version == fs.key)
        .order_by(FeatureRow.date.desc())
        .limit(1)
    ).first()
    features = (
        [FeatureValue(feature=f, value=(frow.values or {}).get(f)) for f in SHOWN_FEATURES]
        if frow
        else []
    )
    sigs = session.scalars(
        select(Signal)
        .where(Signal.instrument_id == instrument_id)
        .order_by(Signal.date.desc(), Signal.rank)
        .limit(50)
    ).all()
    events = session.scalars(
        select(CorporateEvent)
        .where(CorporateEvent.instrument_id == instrument_id)
        .order_by(CorporateEvent.announced_at.desc(), CorporateEvent.id.desc())
        .limit(EVENTS_SHOWN)
    ).all()
    letters = session.scalars(
        select(CodalLetter)
        .where(CodalLetter.instrument_id == instrument_id)
        .order_by(CodalLetter.published_at.desc(), CodalLetter.tracing_no.desc())
        .limit(LETTERS_SHOWN)
    ).all()
    news = symbol_news(session, inst)
    holders = session.scalars(
        select(Shareholder)
        .where(Shareholder.instrument_id == instrument_id)
        .order_by(Shareholder.percent.desc().nulls_last(), Shareholder.holder_key)
    ).all()
    stamps = [h.fetched_at for h in holders if h.fetched_at]
    return InstrumentDetail(
        instrument=instrument_out(inst),
        adjusted=True,
        candles=candles,
        features_date=frow.date if frow else None,
        features=features,
        signals=[signal_out(s, inst) for s in sigs],
        shareholders=[
            ShareholderOut(
                name=h.name, shares=h.shares, percent=h.percent, change_amount=h.change_amount
            )
            for h in holders
        ],
        shareholders_at=max(stamps).date() if stamps else None,
        news=news,
        letters=[
            CodalLetterOut(
                title=x.title,
                letter_code=x.letter_code,
                published_at=x.published_at.date() if x.published_at else None,
                url=x.url,
                has_excel=x.has_excel,
                has_pdf=x.has_pdf,
            )
            for x in letters
        ],
        events=[
            CorporateEventOut(
                type=e.type,
                stage=e.stage,
                title=e.title,
                announced_at=e.announced_at,
                url=e.source_url,
            )
            for e in events
        ],
    )


@router.get("/instruments/{instrument_id}/agm", response_model=AgmDecisionOut)
def agm_decision(
    instrument_id: int,
    session: SessionDep,
    dps: Annotated[float, Query(ge=0, description="dividend per share, rial")],
    months_to_payment: Annotated[float, Query(ge=0, le=60, description="k")],
    expected_drop_after: Annotated[float, Query(description="E[ΔP_after], rial")] = 0.0,
    dividend_tax: Annotated[float, Query(ge=0, description="rial per share")] = 0.0,
    months_alt: Annotated[float | None, Query(ge=0, le=60, description="k'; default k")] = None,
    monthly_discount: Annotated[float | None, Query(gt=-1, description="r_m")] = None,
    alt_monthly_return: Annotated[float | None, Query(gt=-1, description="r_alt")] = None,
) -> AgmDecisionOut:
    """Hold for the AGM or sell before it (docs/05). DPS and timing come from the caller; the
    price, the risk-free rate (default for r_m and r_alt) and the costs come from the database,
    and every input says where it came from."""
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    bar = session.scalars(
        select(PriceDaily)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    if bar is None or not bar.close or float(bar.close) <= 0:
        raise HTTPException(status_code=422, detail="قیمتی برای این نماد ثبت نشده است")
    price = float(bar.close)
    inputs: list[AgmInputOut] = [
        AgmInputOut(name="dps", value=dps, source="user"),
        AgmInputOut(name="price_now", value=price, source=f"prices_daily.close {bar.date}"),
        AgmInputOut(name="months_to_payment", value=months_to_payment, source="user"),
    ]

    rf = None
    if monthly_discount is None or alt_monthly_return is None:
        rf = session.scalars(
            select(MacroSeries)
            .where(MacroSeries.series == RF_SERIES)
            .order_by(MacroSeries.ref_period.desc())
            .limit(1)
        ).first()
        if rf is None:
            raise HTTPException(
                status_code=422,
                detail="نرخ بدون ریسک ثبت نشده است؛ r_m و r_alt را وارد کنید",
            )
    rf_src = f"macro_series.{RF_SERIES} {rf.ref_period}, monthly" if rf else ""
    r_m = monthly_discount if monthly_discount is not None else monthly_from_annual(rf.value)  # type: ignore[union-attr]
    r_alt = (
        alt_monthly_return if alt_monthly_return is not None else monthly_from_annual(rf.value)  # type: ignore[union-attr]
    )
    inputs.append(
        AgmInputOut(
            name="monthly_discount",
            value=r_m,
            source="user" if monthly_discount is not None else rf_src,
        )
    )
    inputs.append(
        AgmInputOut(
            name="alt_monthly_return",
            value=r_alt,
            source="user" if alt_monthly_return is not None else rf_src,
        )
    )
    k_alt = months_alt if months_alt is not None else months_to_payment
    inputs.append(
        AgmInputOut(
            name="months_alt",
            value=k_alt,
            source="user" if months_alt is not None else "= months_to_payment",
        )
    )

    try:
        costs = CostModel.from_rules(
            RuleBook.from_session(session),
            tehran_today(),
            get_engine_config().costs.slippage_fraction,
        )
    except MissingRuleError as exc:
        raise HTTPException(status_code=422, detail=f"قاعدهٔ هزینه ثبت نشده است: {exc}") from exc
    rt = price * costs.round_trip
    inputs.append(
        AgmInputOut(
            name="round_trip_costs",
            value=rt,
            source=f"market_rules + slippage, {costs.round_trip:.4%} of price",
        )
    )
    inputs.append(
        AgmInputOut(
            name="expected_drop_after",
            value=expected_drop_after,
            source="user" if expected_drop_after else "default 0 (not estimated yet)",
        )
    )
    inputs.append(
        AgmInputOut(
            name="dividend_tax",
            value=dividend_tax,
            source="user" if dividend_tax else "default 0 (not verified)",
        )
    )
    try:
        out = hold_or_sell(
            AgmInputs(
                dps=dps,
                price_now=price,
                months_to_payment=months_to_payment,
                monthly_discount=r_m,
                expected_drop_after=expected_drop_after,
                dividend_tax=dividend_tax,
                alt_monthly_return=r_alt,
                months_alt=k_alt,
                round_trip_costs=rt,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgmDecisionOut(
        instrument_id=instrument_id,
        decision=out.decision,
        pv_dividend=out.pv_dividend,
        net_hold=out.net_hold,
        net_sell=out.net_sell,
        inputs=inputs,
    )


def _utc(ts: dt.datetime) -> dt.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)


@router.get("/instruments/{instrument_id}/book", response_model=InstrumentBookOut)
def instrument_book(instrument_id: int, session: SessionDep) -> InstrumentBookOut:
    """Recent days of the reduced order book and where the symbol stood among the stocks with a
    stored book on the latest day. ``available=false`` for symbols outside the 100 most traded."""
    if session.get(Instrument, instrument_id) is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    return book_out(session, instrument_id)


@router.get("/instruments/{instrument_id}/live", response_model=LiveOut)
def instrument_live(instrument_id: int, session: SessionDep) -> LiveOut:
    """The latest stored intraday snapshot and 5-level order book. ``available=false`` is a normal
    state (market closed, or the live poller is not running)."""
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    if (live := _mofid_live(session, inst)) is not None:
        return live
    tsetmc_book = _tsetmc_book(inst)
    snap = session.scalars(
        select(IntradaySnapshot)
        .where(IntradaySnapshot.instrument_id == instrument_id)
        .order_by(IntradaySnapshot.ts.desc())
        .limit(1)
    ).first()
    if snap is None and tsetmc_book:
        return LiveOut(
            instrument_id=instrument_id,
            available=True,
            source="tsetmc",
            as_of=utcnow(),
            age_seconds=0,
            stale=False,
            reference_price=_prev_close(session, instrument_id),
            book_as_of=utcnow(),
            book=tsetmc_book,
        )
    if snap is None:
        return LiveOut(
            instrument_id=instrument_id,
            available=False,
            message="داده لحظه‌ای ذخیره نشده است؛ بازار بسته است یا دریافت زنده فعال نیست.",
        )
    ts = _utc(snap.ts)
    day = ts.astimezone(TEHRAN).date()
    prev = session.scalars(
        select(PriceDaily.close)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.date < day)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    last = None if snap.last_price is None else float(snap.last_price)
    ref = None if prev is None else float(prev)
    book_row = session.scalars(
        select(OrderBookSnapshot)
        .where(OrderBookSnapshot.instrument_id == instrument_id)
        .order_by(OrderBookSnapshot.ts.desc())
        .limit(1)
    ).first()
    age = max(0, int((utcnow() - ts).total_seconds()))
    return LiveOut(
        instrument_id=instrument_id,
        available=True,
        as_of=ts,
        age_seconds=age,
        stale=age > STALE_AFTER_SECONDS,
        last_price=last,
        cum_volume=None if snap.cum_volume is None else float(snap.cum_volume),
        reference_price=ref,
        change_pct=(last / ref - 1.0) if last and ref else None,
        book_as_of=utcnow() if tsetmc_book else _utc(book_row.ts) if book_row else None,
        book=tsetmc_book or ([BookLevelOut(**lv) for lv in book_row.levels] if book_row else []),
        source="tsetmc" if tsetmc_book else "stored",
    )


@router.get("/instruments/{instrument_id}/entry")
def instrument_entry(
    instrument_id: int, session: SessionDep, paid: float | None = None
) -> dict[str, Any]:
    """Is now a sensible moment and price to buy this symbol, and where and when to sell it?
    Today's range comes from the exchange for this request (nothing kept); the answer weighs the
    gap, the place in the day's range, the model's tested edge after cost, the history of days
    that opened like today and the order book. It also carries the exit ladder (where to leave a
    sell limit) and the best quarter-hours of the session to buy and to sell. With ``paid`` it
    also grades a purchase made at that price today."""
    from tmon.portfolio import entry as ent
    from tmon.portfolio import liveprice, timing
    from tmon.portfolio.advice import ranking_doc

    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    bar = liveprice.fetch(inst.ins_code)
    live = bar is not None
    if bar is None:
        row = session.scalars(
            select(PriceDaily)
            .where(PriceDaily.instrument_id == instrument_id)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        ).first()
        bar = ent.bar_from_row(row) if row else None
    if bar is None:
        return {"available": False, "message": "قیمت امروز در دسترس نیست."}
    doc = ranking_doc()
    edge, cost = ent.edge_and_cost(doc)
    verdict = None
    for u in (doc or {}).get("universe") or []:
        if int(u["id"]) == instrument_id:
            from tmon.api.routers.dashboard import _turning_doc
            from tmon.engine.verdict import final_verdict

            v = final_verdict(doc or {}, u, _turning_doc(), instrument_id)
            verdict = v.key if v else None
            break
    fade = ent.bucket_for(ent.fade_table(session), bar.gap)
    drift = ent.drift_from_model(
        ent.fit_open_model(session), ent.open_features(session, instrument_id, bar)
    )
    now = utcnow().astimezone(TEHRAN)
    minutes = None
    if live and bar.day == now.date() and 8 * 60 + 30 <= now.hour * 60 + now.minute <= 12 * 60 + 30:
        minutes = now.hour * 60 + now.minute - 9 * 60
    book = _tsetmc_book(inst) if live else []
    imbalance = None
    queue = None
    if book:
        bid = sum(lv.bid_volume or 0 for lv in book)
        ask = sum(lv.ask_volume or 0 for lv in book)
        imbalance = (bid - ask) / (bid + ask) if bid + ask else None
        top = book[0]
        if bar.limit_up and top.bid_price and top.bid_price >= bar.limit_up and not top.ask_volume:
            queue = "buy_queue"
        elif (
            bar.limit_down
            and top.ask_price
            and top.ask_price <= bar.limit_down
            and not top.bid_volume
        ):
            queue = "sell_queue"
    g = ent.guard(
        bar,
        edge=edge if verdict == "buy" else None,
        cost=cost,
        fade=fade,
        drift=drift,
        queue=queue,
        book_imbalance=imbalance,
        now_minutes=minutes,
        verdict=verdict,
    )
    return {
        "available": True,
        "live": live,
        "day": bar.day.isoformat() if bar.day else None,
        "verdict": verdict,
        "bar": {
            "first": bar.first,
            "high": bar.high,
            "low": bar.low,
            "last": bar.last,
            "close": bar.close,
            "yesterday": bar.yesterday,
            "limit_up": bar.limit_up,
            "limit_down": bar.limit_down,
        },
        "guard": g,
        "plan": ent.entry_plan(
            session,
            instrument_id,
            bar,
            edge=edge,
            cost=cost,
            in_session=minutes is not None and minutes >= 0 and bar.first is not None,
            now_minutes=minutes,
            verdict=verdict,
        ),
        "exit_plan": ent.exit_plan(
            session,
            instrument_id,
            bar,
            in_session=minutes is not None and minutes >= 0 and bar.first is not None,
            now_minutes=minutes,
            verdict=verdict,
        ),
        "timing": timing.time_of_day(session, instrument_id),
        "review": ent.review_entry(paid, bar, edge=edge, cost=cost, fade=fade, queue=queue)
        if paid
        else None,
    }


def _prev_close(session: Session, instrument_id: int) -> float | None:
    day = tehran_today()
    v = session.scalars(
        select(PriceDaily.close)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.date < day)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    return None if v is None else float(v)


def _mofid_live(session: Session, inst: Instrument) -> LiveOut | None:
    """Pushed live by Mofid's server when an account is linked; None otherwise."""
    from tmon.portfolio import mofid_live

    snap = mofid_live.snapshot(session, inst.isin)
    if not snap:
        return None
    sym, book, flow = snap.get("symbol") or {}, snap["book"], snap.get("flow")
    last = sym.get("last_trade_price")
    ref = sym.get("prev_closing_price") or _prev_close(session, inst.id)
    heard = snap["heard_at"]
    age = max(0, int((utcnow() - heard).total_seconds()))
    return LiveOut(
        instrument_id=inst.id,
        available=True,
        source="mofid",
        as_of=heard,
        age_seconds=age,
        stale=not snap["alive"],
        last_price=last,
        cum_volume=sym.get("total_number_of_shares_traded"),
        reference_price=ref,
        change_pct=(last / ref - 1.0) if last and ref else None,
        high_allowed=sym.get("max_daily_price"),
        low_allowed=sym.get("min_daily_price"),
        day_high=sym.get("max_daily_traded_price"),
        day_low=sym.get("min_daily_traded_price"),
        trade_value=sym.get("total_trade_value"),
        trades=sym.get("total_number_of_trades"),
        book_as_of=book.get("as_of") or heard,
        book=[BookLevelOut(**lv) for lv in book["levels"]],
        flow=LiveFlowOut(**{k: v for k, v in flow.items() if k in LiveFlowOut.model_fields})
        if flow
        else None,
    )


def _tsetmc_book(inst: Instrument) -> list[BookLevelOut]:
    """The current book straight from TSETMC (fetched now, nothing kept); [] when it fails."""
    import httpx

    from tmon.ingest.tsetmc.endpoints import BEST_LIMITS_LIVE
    from tmon.ingest.tsetmc.parsers import ParseError, parse_best_limits

    try:
        r = httpx.get(
            BEST_LIMITS_LIVE.format(ins_code=inst.ins_code),
            headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-store"},
            timeout=4,
        )
        r.raise_for_status()
        levels = parse_best_limits(r.text)
    except (httpx.HTTPError, ParseError, ValueError):
        return []
    return [BookLevelOut(**lv.as_dict()) for lv in levels if lv.bid_volume or lv.ask_volume]


NEWS_DAYS = 45
NEWS_SHOWN = 12


def symbol_news(session: Session, inst: Instrument) -> list[SymbolNewsOut]:
    """Recent headlines that name the symbol or the company. Symbols are short Persian words, so
    the symbol must stand alone (spaces, punctuation or the title's ends around it)."""
    since = utcnow() - dt.timedelta(days=NEWS_DAYS)
    names = [n for n in {inst.symbol_fa, (inst.name_fa or "").strip()} if n and len(n) >= 3]
    if not names:
        return []
    rows = session.scalars(
        select(NewsRaw)
        .where(NewsRaw.published_at >= since, or_(*[NewsRaw.title.contains(n) for n in names]))
        .order_by(NewsRaw.published_at.desc())
        .limit(80)
    ).all()
    word = re.compile("|".join(rf"(?<![\w‌]){re.escape(n)}(?![\w‌])" for n in names))
    out: list[SymbolNewsOut] = []
    seen: set[str] = set()
    for n in rows:
        key = n.title_norm or n.title
        if key in seen or not word.search(n.title):
            continue
        seen.add(key)
        out.append(
            SymbolNewsOut(title=n.title, source=n.source, url=n.url, published_at=n.published_at)
        )
    return out[:NEWS_SHOWN]
