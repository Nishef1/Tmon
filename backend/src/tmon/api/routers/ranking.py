from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.queue_size import history_odds, odds_for, queue_readings
from tmon.api.returns import day_change
from tmon.api.routers.dashboard import _turning_doc, final_verdict
from tmon.api.schemas import OutsideRow, RankingOut
from tmon.api.trade_state import market_days, trade_state
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.storage.models import Instrument, PriceDaily
from tmon.storage.objectstore import get_object_store
from tmon.tools.v2_ranking import KEY

router = APIRouter(tags=["ranking"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/v2/ranking", response_model=RankingOut)
def ranking(session: SessionDep) -> RankingOut:
    """Latest ranking of the liquid basket written by ``python -m tmon.tools.v2_ranking``,
    with the evidence per horizon and the gate verdicts. Not a recommendation unless
    ``recommendation_allowed`` is true."""
    try:
        data = get_object_store().get(get_settings().minio_artifact_bucket, KEY)
    except (FileNotFoundError, KeyError, OSError):
        return RankingOut(available=False)
    doc = json.loads(data)
    out = RankingOut(available=True, **doc)
    out.outside = _outside(session, doc)
    turning = _turning_doc()
    for r in out.rows:
        v = final_verdict(doc, r.zone, {k: x for k, x in r.signals.items() if x is not None})
        r.verdict = v if v in ("buy", "hold", "sell") else None  # type: ignore[assignment]
    out.universe_size = len(doc.get("universe") or []) or None
    # link each row to its instrument page with the latest close and day change
    last = session.scalar(select(func.max(PriceDaily.date)))
    if last is not None and out.rows:
        symbols = {r.symbol for r in out.rows}
        found = session.execute(
            select(Instrument, PriceDaily)
            .join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
            .where(PriceDaily.date == last, Instrument.symbol_fa.in_(symbols))
            .order_by(PriceDaily.value.desc())
        ).all()
        by_symbol: dict[str, tuple[Instrument, PriceDaily]] = {}
        for ins, p in found:  # most traded listing wins when a symbol repeats
            by_symbol.setdefault(ins.symbol_fa, (ins, p))
        for r in out.rows:
            hit = by_symbol.get(r.symbol)
            if hit is None:
                continue
            ins, p = hit
            close = None if p.close is None else float(p.close)
            prev = None if p.prev_close is None else float(p.prev_close)
            r.instrument_id = ins.id
            r.close = close
            r.change_pct = day_change(close, prev)
            if r.verdict == "buy":  # a buy is lowered to a wait when the symbol's state objects
                again = final_verdict(
                    doc,
                    r.zone,
                    {k: x for k, x in r.signals.items() if x is not None},
                    turning,
                    ins.id,
                )
                r.verdict = again if again in ("buy", "hold", "sell") else None  # type: ignore[assignment]
        _mark_idle(session, out, by_symbol)
        readings = queue_readings(
            session, [r.instrument_id for r in out.rows if r.instrument_id], last
        )
        odds = history_odds(session) if readings else []
        for r in out.rows:
            got = readings.get(r.instrument_id or -1)
            if got is not None:
                r.queue_ratio, r.queue_level, r.queue_orders = got
                hit_odds = odds_for(got[0], odds)
                if hit_odds is not None:
                    r.queue_reach_pct, r.queue_reach_cases = hit_odds
    return out


def _mark_idle(
    session: Session, out: RankingOut, traded: dict[str, tuple[Instrument, PriceDaily]]
) -> None:
    """Rows that did not trade on the latest day: link them anyway and say for how long."""
    missing = {r.symbol for r in out.rows if r.symbol not in traded}
    if not missing:
        return
    days = market_days(session)
    listed: dict[str, Instrument] = {}
    for found in session.scalars(select(Instrument).where(Instrument.symbol_fa.in_(missing))):
        listed.setdefault(found.symbol_fa, found)
    for r in out.rows:
        stopped = listed.get(r.symbol) if r.symbol in missing else None
        if stopped is None:
            continue
        state, last_trade, idle = trade_state(session, stopped.id, days)
        r.instrument_id = stopped.id
        r.trade_state, r.idle_days, r.last_trade_date = state, idle, last_trade


OUTSIDE_LIMIT = 12


def _outside(session: Session, doc: dict) -> list[OutsideRow]:  # type: ignore[type-arg]
    """Best-scored stocks of the whole scored universe that are not in the liquid basket: the
    list shows only the basket (the model was tested on it, and orders there fill), so the rest
    are named here instead of silently missing."""
    basket = {r["symbol"] for r in doc.get("rows", [])}
    scored = sorted(
        (
            u
            for u in doc.get("universe", [])
            if u.get("score") is not None and u.get("queue_state") in (None, "none")
        ),
        key=lambda u: -u["score"],
    )
    ids = [u["id"] for u in scored[:80]]
    names = {i.id: i for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))}
    out: list[OutsideRow] = []
    for u in scored[:80]:
        ins = names.get(u["id"])
        if ins is None or ins.symbol_fa in basket or (ins.name_fa or "").startswith("صندوق"):
            continue
        out.append(
            OutsideRow(
                instrument_id=ins.id,
                symbol=ins.symbol_fa,
                name=ins.name_fa,
                score=u["score"],
                median_value=u.get("median_value"),
            )
        )
        if len(out) >= OUTSIDE_LIMIT:
            break
    return out
