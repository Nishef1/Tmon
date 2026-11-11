"""Codal endpoints, as verified against live responses on 2026-11-11.

``search.codal.ir/api/search/v2/q`` returns 20 letters per page, newest first. Parameters seen to
filter the result: ``Symbol``, ``LetterCode`` (e.g. ``ن-۵۲``), ``FromDate``/``ToDate`` (Jalali,
``1405/05/01``), ``Childs=false&Mains=true`` (drops letters published for subsidiaries).
``PageNumber`` starts at 1.

Quirk: with ``LetterCode`` set, ``Total`` and ``Page`` come back as 0 even when letters are
returned, so callers page until a short page instead of trusting those fields.

The server rate-limits (HTTP 429 with no ``Retry-After``) after a few dozen requests at about one
per second, so Codal gets its own slower per-host interval (``codal_min_interval_seconds``).
"""

from __future__ import annotations

from urllib.parse import urlencode

SEARCH_HOST = "search.codal.ir"
SEARCH_URL = f"https://{SEARCH_HOST}/api/search/v2/q"
REPORT_BASE = "https://www.codal.ir"
PAGE_SIZE = 20


def search_url(
    *,
    page: int = 1,
    symbol: str | None = None,
    letter_code: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    mains_only: bool = False,
) -> str:
    params: dict[str, str | int] = {"PageNumber": page}
    if symbol:
        params["Symbol"] = symbol
    if letter_code:
        params["LetterCode"] = letter_code
    if from_date:
        params["FromDate"] = from_date
    if to_date:
        params["ToDate"] = to_date
    if mains_only:
        params["Childs"] = "false"
        params["Mains"] = "true"
    params["search"] = "true"
    return f"{SEARCH_URL}?{urlencode(params)}"


def report_url(path: str) -> str:
    """Absolute URL of a letter's report page (``Url`` in the index is site-relative)."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return REPORT_BASE + (path if path.startswith("/") else "/" + path)
