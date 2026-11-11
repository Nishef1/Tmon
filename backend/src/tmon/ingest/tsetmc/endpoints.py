"""TSETMC endpoints.

Shapes are taken from the open-source reference client ``pytse-client`` (allowed by
docs/02). They are NOT verified against the live site from the build machine; see
``tests/network`` and docs/OPEN_QUESTIONS.md.
"""

from __future__ import annotations

OLD = "http://old.tsetmc.com"
CDN = "http://cdn.tsetmc.com"

MARKET_WATCH_INIT = f"{OLD}/tsev2/data/MarketWatchInit.aspx?h=0&r=0"
DAILY_HISTORY = f"{OLD}/tsev2/data/Export-txt.aspx?t=i&a=1&b=0&i={{ins_code}}"
CLIENT_TYPES = f"{OLD}/tsev2/data/clienttype.aspx?i={{ins_code}}"
INSTRUMENT_INFO = f"{CDN}/api/Instrument/GetInstrumentInfo/{{ins_code}}"
BEST_LIMITS = f"{CDN}/api/BestLimits/{{ins_code}}/{{date}}"
BEST_LIMITS_LIVE = f"{CDN}/api/BestLimits/{{ins_code}}"  # current order book (reference client)
LAST_TRADE_DAY = "http://service.tsetmc.com/tsev2/data/TseClient2.aspx?t=LastPossibleDeven"


def daily_history_url(ins_code: str) -> str:
    return DAILY_HISTORY.format(ins_code=ins_code)


def client_types_url(ins_code: str) -> str:
    return CLIENT_TYPES.format(ins_code=ins_code)


def instrument_info_url(ins_code: str) -> str:
    return INSTRUMENT_INFO.format(ins_code=ins_code)


def best_limits_live_url(ins_code: str) -> str:
    return BEST_LIMITS_LIVE.format(ins_code=ins_code)


def best_limits_url(ins_code: str, date_yyyymmdd: int | str = 0) -> str:
    return BEST_LIMITS.format(ins_code=ins_code, date=date_yyyymmdd)
