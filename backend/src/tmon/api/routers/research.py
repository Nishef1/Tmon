from __future__ import annotations

from fastapi import APIRouter

from tmon.api.adapt import KEY as ADAPT_KEY
from tmon.api.adapt import adapt_out
from tmon.api.autopilot import KEY as AUTOPILOT_KEY
from tmon.api.autopilot import autopilot_out
from tmon.api.book import KEY as BOOK_KEY
from tmon.api.book import research_out as book_research_out
from tmon.api.entry import entry_doc, entry_odds_out
from tmon.api.regime_paper import KEY as REGIME_KEY
from tmon.api.regime_paper import regime_paper_out
from tmon.api.schemas import (
    AdaptOut,
    AutopilotOut,
    EntryOddsOut,
    OrderbookResearchOut,
    RegimePaperOut,
    TaSignalsOut,
)
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


@router.get("/research/adapt", response_model=AdaptOut)
def adapt() -> AdaptOut:
    """The living ranking: which method is champion per horizon after the gate, its weights against
    equal weights, the weight drift, the cycle history and the replay on the past
    (``python -m tmon.tools.adapt_cycle``). The past, not advice."""
    return adapt_out(load_doc(ADAPT_KEY))


@router.get("/research/autopilot", response_model=AutopilotOut)
def autopilot() -> AutopilotOut:
    """What the system saw when it last checked itself: the regime reading of the official index
    and the events since (a champion changed, the regime flipped). Read fresh from the stored
    document (``python -m tmon.tools.autopilot``). The past, not advice."""
    return autopilot_out(load_doc(AUTOPILOT_KEY))


@router.get("/research/regime-paper", response_model=RegimePaperOut)
def regime_paper() -> RegimePaperOut:
    """The market-state plan run forward on paper: today's state from breadth, the action it
    calls for, the decision log and the paper account against the basket and cash
    (``python -m tmon.tools.regime_paper``). A test, not advice; no order is placed."""
    return regime_paper_out(load_doc(REGIME_KEY))
