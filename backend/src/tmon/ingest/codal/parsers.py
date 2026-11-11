"""Parse the Codal search API response (``search.codal.ir/api/search/v2/q``).

Field names and formats are taken from captured responses in ``tests/fixtures/codal/``.
Dates are Jalali with Persian digits, in Tehran local time: ``۱۴۰۵/۰۸/۱۷ ۱۸:۲۰:۲۰``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import jdatetime

from tmon.core.timeutil import TEHRAN
from tmon.ingest.codal.endpoints import report_url
from tmon.ingest.tsetmc.parsers import ParseError, normalize_fa

_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def ascii_digits(text: str) -> str:
    return text.translate(_TO_ASCII)


def parse_codal_datetime(text: str | None) -> datetime | None:
    """``۱۴۰۵/۰۸/۱۷ ۱۸:۲۰:۲۰`` (Tehran) -> aware UTC datetime; None for empty input."""
    if not text or not text.strip():
        return None
    raw = ascii_digits(text).strip()
    try:
        day, _, clock = raw.partition(" ")
        y, m, d = (int(p) for p in day.split("/"))
        hh, mm, ss = (int(p) for p in (clock or "00:00:00").split(":"))
        greg = jdatetime.date(y, m, d).togregorian()
    except (ValueError, TypeError) as exc:
        raise ParseError(f"bad Codal datetime {text!r}") from exc
    local = datetime(greg.year, greg.month, greg.day, hh, mm, ss, tzinfo=TEHRAN)
    return local.astimezone(UTC)


@dataclass(frozen=True)
class Letter:
    tracing_no: int
    symbol: str
    company_name: str
    title: str
    letter_code: str  # as published, Persian digits ("ن-۵۲"); "" when the letter has none
    sent_at: datetime | None
    published_at: datetime | None
    url: str
    has_html: bool
    has_excel: bool
    has_pdf: bool
    under_supervision: bool


@dataclass(frozen=True)
class SearchPage:
    total: int  # 0 when LetterCode is set, whatever the real count (see endpoints.py)
    pages: int
    letters: list[Letter]


def parse_search(payload: bytes | str) -> SearchPage:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        head = payload[:80] if isinstance(payload, str) else payload[:80].decode(errors="replace")
        raise ParseError(f"Codal search: not JSON: {head!r}") from exc
    if not isinstance(data, dict) or "Letters" not in data:
        raise ParseError("Codal search: no 'Letters' key")
    letters = []
    for row in data["Letters"] or []:
        try:
            sup = row.get("SuperVision") or {}
            letters.append(
                Letter(
                    tracing_no=int(row["TracingNo"]),
                    symbol=normalize_fa(row.get("Symbol") or ""),
                    company_name=normalize_fa(row.get("CompanyName") or ""),
                    title=normalize_fa(row.get("Title") or ""),
                    letter_code=(row.get("LetterCode") or "").strip(),
                    sent_at=parse_codal_datetime(row.get("SentDateTime")),
                    published_at=parse_codal_datetime(row.get("PublishDateTime")),
                    url=report_url(row.get("Url") or ""),
                    has_html=bool(row.get("HasHtml")),
                    has_excel=bool(row.get("HasExcel")),
                    has_pdf=bool(row.get("HasPdf")),
                    under_supervision=bool(sup.get("UnderSupervision")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ParseError(f"Codal search: bad letter row: {exc}") from exc
    return SearchPage(
        total=int(data.get("Total") or 0), pages=int(data.get("Page") or 0), letters=letters
    )
