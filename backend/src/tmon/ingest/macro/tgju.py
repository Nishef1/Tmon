"""tgju.org daily history (free-market USD, gold, coin).

``api.tgju.org/v1/market/indicator/summary-table-data/{key}`` returns a DataTables payload,
``{"draw", "recordsTotal", "recordsFiltered", "data": [[...], ...]}``, newest first. Each row,
checked against the column headers of ``tgju.org/profile/{key}/history`` on 2026-11-12:
open, low, high, close (thousands-separated rial), change and change % (HTML ``<span>`` whose
class ``high``/``low`` gives the sign), Gregorian date ``YYYY/MM/DD``, Jalali date. Sample:
``tests/fixtures/macro/tgju_price_dollar_rl.json`` (first 40 rows of a real response).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from tmon.ingest.tsetmc.parsers import ParseError

API = "https://api.tgju.org/v1/market/indicator/summary-table-data/{key}"

# our series name -> tgju key; names checked against each profile page title on 2026-11-12
SERIES: dict[str, str] = {
    "usd_free": "price_dollar_rl",  # «دلار» بازار آزاد، ریال
    "gold_18k": "geram18",  # «قیمت طلای 18 عیار / 750»، ریال هر گرم
    "coin_emami": "sekee",  # «قیمت سکه امامی»، ریال
}
SOURCE = "tgju"


@dataclass(frozen=True)
class TgjuBar:
    date: date
    open: float
    low: float
    high: float
    close: float
    jalali: str


def url(key: str) -> str:
    return API.format(key=key)


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def parse_history(payload: bytes) -> list[TgjuBar]:
    try:
        doc = json.loads(payload)
        rows = doc["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError(f"tgju: not a history payload: {payload[:120]!r}") from exc
    out = []
    for r in rows:
        try:
            y, m, d = (int(x) for x in r[6].split("/"))
            out.append(TgjuBar(date(y, m, d), _num(r[0]), _num(r[1]), _num(r[2]), _num(r[3]), r[7]))
        except (IndexError, ValueError, AttributeError) as exc:
            raise ParseError(f"tgju: unexpected row {r!r}") from exc
    return out
