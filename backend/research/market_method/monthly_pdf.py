"""Read the revenue total of a monthly-activity PDF (ن-۳۰, production template) from TSETMC.

The PDF's text order is scrambled for RTL digits (words come out in pieces), but every glyph keeps its
x position, and digits run left to right on the page. So the numbers are rebuilt from glyph positions:
glyphs of one row are sorted by x and read with the regex d{1,3}(,d{3})*.

The table «تولید و فروش» ends with a row labelled exactly «جمع» with the amount columns, left to right:
  [same period last year (cumulative), this year to date, the month, corrected YTD to last month,
   corrections, YTD to last month]
so the month is the 3rd value from the left, and the cumulative is the 2nd. Rows with other counts are
skipped (None). Validated against the 641 reports read from Codal's page JSON (monthly_sales.py).

Needs pymupdf (not in the backend venv): run with a Python that has it, e.g. a --target install.
parse_pdf(path) -> dict | None.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUM = re.compile(r"\d{1,3}(?:,\d{3})*")
_TOTAL = "ﺟﻤﻊ"  # «جمع» in presentation forms, as the PDF stores it
_PURCHASE = "ﺧﺮﯾﺪ"  # «خرید»: the next section (purchases) starts on a later page


def _rows(page: pymupdf.Page) -> list[tuple[float, list[tuple[float, str]]]]:
    raw = page.get_text("rawdict")
    glyphs = []
    for b in raw["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                for c in s["chars"]:
                    x0, y0, x1, y1 = c["bbox"]
                    glyphs.append((c["c"], (x0 + x1) / 2, (y0 + y1) / 2))
    glyphs.sort(key=lambda g: g[2])
    rows: list[tuple[float, list[tuple[float, str]]]] = []
    last_y = None
    for ch, x, y in glyphs:
        if last_y is None or y - last_y > 3.0:
            rows.append((y, []))
        rows[-1][1].append((x, ch))
        last_y = y
    return [(y, sorted(v)) for y, v in rows]


def _numbers(row: list[tuple[float, str]]) -> list[float]:
    """Numbers of a row, left to right; a gap wider than a digit pitch starts a new cell."""
    out: list[float] = []
    cell = ""
    prev = None
    for x, ch in row:
        c = ch.translate(_DIGITS)
        if c not in "0123456789,":
            continue
        if prev is not None and x - prev > 4.6 and cell:
            out.append(cell)
            cell = ""
        cell += c
        prev = x
    if cell:
        out.append(cell)
    nums: list[float] = []
    for t in out:
        t = t.strip(",")
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", t):
            nums.append(float(t.replace(",", "")))
    return nums


def _label(row: list[tuple[float, str]]) -> str:
    return "".join(ch for _x, ch in row if ch.translate(_DIGITS) not in "0123456789,").strip()


def parse_pdf(path: str | Path) -> dict | None:
    doc = pymupdf.open(str(path))
    best = None
    for page in doc:
        text = page.get_text()
        if _PURCHASE + " دوره" in text and best is not None:
            break
        for _y, row in _rows(page):
            lab = re.sub(r"[\s().]", "", _label(row))
            if lab not in (_TOTAL, _TOTAL[::-1]):
                continue
            vals = _numbers(row)
            if len(vals) == 6 and (best is None or vals[1] + vals[2] >= best[1] + best[2]):
                best = vals
    if best is None:
        return None
    return {"last_year_ytd": best[0], "ytd": best[1], "month": best[2]}
