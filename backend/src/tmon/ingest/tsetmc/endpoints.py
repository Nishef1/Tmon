"""TSETMC endpoints.

Shapes are taken from the open-source reference client ``pytse-client`` (allowed by
docs/02). They are NOT verified against the live site from the build machine; see
``tests/network`` and docs/OPEN_QUESTIONS.md.
"""

from __future__ import annotations

from tmon.core.config import get_settings

OLD = get_settings().tsetmc_old_url.rstrip("/")
CDN = get_settings().tsetmc_cdn_url.rstrip("/")

MARKET_WATCH_INIT = f"{OLD}/tsev2/data/MarketWatchInit.aspx?h=0&r=0"
DAILY_HISTORY = f"{OLD}/tsev2/data/Export-txt.aspx?t=i&a=1&b=0&i={{ins_code}}"
CLIENT_TYPES = f"{OLD}/tsev2/data/clienttype.aspx?i={{ins_code}}"
INSTRUMENT_INFO = f"{CDN}/api/Instrument/GetInstrumentInfo/{{ins_code}}"
SHAREHOLDERS = f"{CDN}/api/Shareholder/GetInstrumentShareHolderLast/{{ins_code}}"
BEST_LIMITS = f"{CDN}/api/BestLimits/{{ins_code}}/{{date}}"
BEST_LIMITS_LIVE = f"{CDN}/api/BestLimits/{{ins_code}}"  # current order book (reference client)
# TSETMC's own adjusted series (a=1; a=0 is the raw one). Integer-rounded prices.
ADJUSTED_HISTORY = f"{OLD}/tsev2/chart/data/Financial.aspx?i={{ins_code}}&t=ph&a=1&b=0"
INDEX_HISTORY = f"{CDN}/api/Index/GetIndexB2History/{{code}}"
INSTRUMENT_SEARCH = f"{CDN}/api/Instrument/GetInstrumentSearch/{{text}}"
LAST_TRADE_DAY = "https://service.tsetmc.com/tsev2/data/TseClient2.aspx?t=LastPossibleDeven"


SERVICE = "https://service.tsetmc.com/tsev2/data/TseClient2.aspx"
FIRST_POSSIBLE_DEVEN = 20010321  # earliest date the service serves (open-source tse-client, MIT)


def instrument_list_url() -> str:
    """Every instrument ever listed (4k+ rows, one request); ``a=0`` asks for the full list."""
    return f"{SERVICE}?t=Instrument&a=0"


def instrument_and_share_url() -> str:
    """``instrument rows @ share-change rows`` (capital increases etc.)."""
    return f"{SERVICE}?t=InstrumentAndShare&a=0&a2=0"


def closing_prices_url(items: list[tuple[str, int, bool]]) -> str:
    """Batched daily history, up to 50 instruments per request: ``code,from_deven,not_normal``
    items joined by ``;``; the reply holds one ``;``-separated block per item, joined by ``@``."""
    a = ";".join(f"{c},{d},{int(n)}" for c, d, n in items)
    return f"{SERVICE}?t=ClosingPrices&a={a}"


def daily_history_url(ins_code: str) -> str:
    return DAILY_HISTORY.format(ins_code=ins_code)


def client_types_url(ins_code: str) -> str:
    return CLIENT_TYPES.format(ins_code=ins_code)


def instrument_info_url(ins_code: str) -> str:
    return INSTRUMENT_INFO.format(ins_code=ins_code)


def shareholders_url(ins_code: str) -> str:
    return SHAREHOLDERS.format(ins_code=ins_code)


def best_limits_live_url(ins_code: str) -> str:
    return BEST_LIMITS_LIVE.format(ins_code=ins_code)


def best_limits_url(ins_code: str, date_yyyymmdd: int | str = 0) -> str:
    return BEST_LIMITS.format(ins_code=ins_code, date=date_yyyymmdd)


def index_history_url(code: str) -> str:
    return INDEX_HISTORY.format(code=code)


def adjusted_history_url(ins_code: str) -> str:
    return ADJUSTED_HISTORY.format(ins_code=ins_code)


def instrument_search_url(text: str) -> str:
    from urllib.parse import quote

    return INSTRUMENT_SEARCH.format(text=quote(text))
