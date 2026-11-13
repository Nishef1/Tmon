from __future__ import annotations

from fastapi import APIRouter

from tmon.api.entry import entry_doc, entry_odds_out
from tmon.api.schemas import EntryOddsOut, TaSignalsOut
from tmon.api.technical import signals_out, ta_doc

router = APIRouter(tags=["research"])


@router.get("/research/ta-signals", response_model=TaSignalsOut)
def ta_signals() -> TaSignalsOut:
    """Every classic reading of the glossary's chart terms, tested on the whole TSETMC history
    (``python -m tmon.tools.ta_signals``). A description of the past, not advice."""
    return signals_out(ta_doc())


@router.get("/research/entry-odds", response_model=EntryOddsOut)
def entry_odds() -> EntryOddsOut:
    """After a given candle, how often the next 1 to 20 candles were up, against every symbol
    one could buy on the same days (``python -m tmon.tools.entry_odds``). The past, not advice."""
    return entry_odds_out(entry_doc())
