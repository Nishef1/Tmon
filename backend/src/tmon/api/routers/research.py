from __future__ import annotations

from fastapi import APIRouter

from tmon.api.book import KEY as BOOK_KEY
from tmon.api.book import research_out as book_research_out
from tmon.api.entry import entry_doc, entry_odds_out
from tmon.api.schemas import EntryOddsOut, OrderbookResearchOut, TaSignalsOut
from tmon.api.technical import load_doc, signals_out, ta_doc

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


@router.get("/research/orderbook-queue", response_model=OrderbookResearchOut)
def orderbook_queue() -> OrderbookResearchOut:
    """What the order book and the buy/sell queues add to the score and what a realistic portfolio
    (queue waits, 10% of the day's value, costs) earned in the tested history
    (``python -m tmon.tools.orderbook_research``). The past, not advice."""
    return book_research_out(load_doc(BOOK_KEY))
