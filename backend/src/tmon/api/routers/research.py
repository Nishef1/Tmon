from __future__ import annotations

from fastapi import APIRouter

from tmon.api.schemas import TaSignalsOut
from tmon.api.technical import signals_out, ta_doc

router = APIRouter(tags=["research"])


@router.get("/research/ta-signals", response_model=TaSignalsOut)
def ta_signals() -> TaSignalsOut:
    """Every classic reading of the glossary's chart terms, tested on the whole TSETMC history
    (``python -m tmon.tools.ta_signals``). A description of the past, not advice."""
    return signals_out(ta_doc())
