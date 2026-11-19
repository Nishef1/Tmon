"""Readable page addresses: ``/instruments/<industry>/<symbol>`` instead of the numeric id.

A slug is the Persian name with Arabic letter forms turned into Persian ones, digits turned into
ASCII, and every run of spaces, half-spaces and punctuation turned into one hyphen.
"""

from __future__ import annotations

import re
import unicodedata

NO_SECTOR = "سایر"  # instruments without an industry group (funds, coins, rights of others)

_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ى": "ی"})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_GAPS = re.compile(r"[^\w]+")
# Arabic diacritics (U+064B..U+065F), tatweel, and the left/right marks
_MARKS = re.compile(f"[{chr(0x64B)}-{chr(0x65F)}{chr(0x640)}{chr(0x200E)}{chr(0x200F)}]")


def slugify(text: str | None) -> str:
    """The address form of a name; empty when nothing readable is left."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _MARKS.sub("", t).translate(_LETTERS).translate(_DIGITS).casefold()
    return _GAPS.sub("-", t.replace("_", "-")).strip("-")


def sector_slug(name: str | None) -> str:
    return slugify(name) or NO_SECTOR
