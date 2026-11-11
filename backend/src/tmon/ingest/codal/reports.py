"""Parse Codal report bodies from the Excel export (``excel.codal.ir``).

The export is not a spreadsheet: it is the report's HTML (``.xls`` with an HTML body) holding one
``<table class="rayanDynamicStatement">`` per section, each with a ``<thead>`` of one or more header
rows (explicit ``rowspan``/``colspan``) and a ``<tbody>``. A section title, when there is one,
is the text between the previous table and this one. Numbers use Persian digits, thousands
separators and parentheses for negatives: ``(۳,۰۱۴)``.

Structure seen in captured samples (``tests/fixtures/codal/``):

* ن-۳۰ monthly activity (production company): 5 tables, with no titles between them:
  production and sales by product, raw-material purchases, energy use, foreign-currency sources,
  and free-text notes.
* ن-۱۰ interim statements (consolidated, production company): 62 tables under titles such as
  «صورت سود و زیان», «صورت وضعیت مالی», «صورت جریان های نقدی» and the pages of
  «خلاصه اطلاعات گزارش تفسیری».

The parser keeps every non-empty cell with its section title, row label and column header path,
so nothing is lost when a template differs; field-level extraction is done downstream against
the stored cells.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from tmon.ingest.codal.parsers import ascii_digits
from tmon.ingest.tsetmc.parsers import ParseError, normalize_fa

# The page Codal serves instead of a report once a viewer has opened "many reports".
CAPTCHA_MARKER = "ReportsCaptcha.aspx"
_NUMBER = re.compile(r"^(\()?\s*(-)?\s*([\d,]*\.?\d+)\s*(\))?\s*(%)?$")
_SUBSIDIARY = re.compile(r"\((شرکت [^()]+)\)\s*(?:\(اصلاحیه\))?\s*$")
_PERIOD_END = re.compile(r"منتهی به\s*(\d{4}/\d{2}/\d{2})")


@dataclass(frozen=True)
class ReportTable:
    index: int
    title: str | None
    columns: list[str]  # header path per column, " / "-joined; "" when the table has no header
    rows: list[list[str]]  # body rows, one string per column ("" for empty or spanned cells)


@dataclass
class _Cell:
    text: str
    rowspan: int
    colspan: int


@dataclass
class _Table:
    head: list[list[_Cell]] = field(default_factory=list)
    body: list[list[_Cell]] = field(default_factory=list)
    title: str | None = None


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._between: list[str] = []
        self._skip = 0  # inside <style>/<script>
        self._table: _Table | None = None
        self._depth = 0  # nested table depth; inner tables are flattened into the outer cell
        self._in_head = False
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "table":
            self._depth += 1
            if self._depth == 1:
                title = _title(self._between)
                self._table = _Table(title=title or None)
                self._between = []
        elif self._depth == 1 and tag == "thead":
            self._in_head = True
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th"):
            a = dict(attrs)
            self._cell = _Cell("", _span(a.get("rowspan")), _span(a.get("colspan")))
            self._buf = []
        elif tag == "br" and self._cell is not None:
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag == "table":
            if self._depth == 1 and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag == "thead":
            self._in_head = False
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            self._cell.text = _clean("".join(self._buf))
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None and self._table:
            (self._table.head if self._in_head else self._table.body).append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._buf.append(data)
        elif self._depth == 0:
            self._between.append(data)


def _span(v: str | None) -> int:
    try:
        return max(1, int(v or 1))
    except ValueError:
        return 1


def _title(chunks: list[str]) -> str:
    """Join the text between two tables, dropping a chunk that repeats the one before it (the
    export writes each section title twice)."""
    parts: list[str] = []
    for ch in chunks:
        t = _clean(ch)
        if t and (not parts or parts[-1] != t):
            parts.append(t)
    return " ".join(parts)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_fa(text)).strip()


def _grid(rows: list[list[_Cell]], *, fill_spans: bool) -> list[list[str]]:
    """Expand rowspan/colspan into a rectangular grid. Header cells repeat across their span so
    every column gets its full header path; body cells sit in their first column only, so a
    spanned number is never counted twice."""
    out: dict[tuple[int, int], str] = {}
    width = 0
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in out:
                c += 1
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    first = dr == 0 and dc == 0
                    out[(r + dr, c + dc)] = cell.text if (first or fill_spans) else ""
            c += cell.colspan
            width = max(width, c)
    return [[out.get((r, c), "") for c in range(width)] for r in range(len(rows))]


def _column_paths(head: list[list[str]], width: int) -> list[str]:
    paths = []
    for c in range(width):
        parts: list[str] = []
        for row in head:
            t = row[c] if c < len(row) else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        paths.append(" / ".join(parts))
    return paths


def parse_report(payload: bytes) -> list[ReportTable]:
    """Every top-level table of a Codal Excel export. Raises ``ParseError`` for the CAPTCHA page
    or a body without report tables."""
    text = payload.decode("utf-8", errors="replace")
    if CAPTCHA_MARKER in text:
        raise ParseError("Codal served its CAPTCHA page instead of the report")
    ex = _Extractor()
    ex.feed(text)
    ex.close()
    if not ex.tables:
        raise ParseError(f"Codal report: no tables in {text[:120]!r}")
    out = []
    for i, t in enumerate(ex.tables):
        head = _grid(t.head, fill_spans=True)
        body = _grid(t.body, fill_spans=False)
        width = max([len(r) for r in head + body] or [0])
        body = [r + [""] * (width - len(r)) for r in body]
        out.append(ReportTable(i, t.title, _column_paths(head, width), body))
    return out


def parse_number(text: str) -> float | None:
    """``۳۹,۳۹۱,۴۰۱`` -> 39391401; ``(۳,۰۱۴)`` -> -3014; ``۱۲.۵%`` -> 12.5; text -> None."""
    s = ascii_digits(text).replace("٬", ",").replace("٫", ".").replace(" ", "")
    m = _NUMBER.match(s)
    if not m or not m.group(3).strip(","):
        return None
    try:
        v = float(m.group(3).replace(",", ""))
    except ValueError:
        return None
    negative = bool(m.group(2)) or (bool(m.group(1)) and bool(m.group(4)))
    return -v if negative else v


def row_label(row: list[str]) -> str | None:
    """First non-numeric text of a body row (the line item or product name)."""
    for t in row:
        if t and parse_number(t) is None:
            return t
    return None


def format_signature(tables: list[ReportTable]) -> str:
    """Short hash of the template: section titles and column headers with digits removed, so the
    same template for another period or company hashes the same. A new value means a format
    variant worth recording."""
    parts = []
    for t in tables:
        cols = "|".join(re.sub(r"[\d/]+", "#", ascii_digits(c)) for c in t.columns)
        parts.append(f"{re.sub(r'[0-9]+', '#', ascii_digits(t.title or ''))}::{cols}")
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]


def period_end(title: str) -> str | None:
    """Jalali period end from a letter title («... منتهی به ۱۴۰۵/۰۷/۳۰»), ASCII digits."""
    m = _PERIOD_END.search(normalize_fa(ascii_digits(title)))
    return m.group(1) if m else None


def subsidiary_of(title: str) -> str | None:
    """Codal files a subsidiary's reports under the parent's symbol and names the subsidiary in a
    trailing parenthesis: «... (حسابرسی شده) (شرکت نیروگاهی سیکل ترکیبی کرمانیان)»."""
    m = _SUBSIDIARY.search(normalize_fa(title))
    return m.group(1) if m else None


def is_correction(title: str) -> bool:
    return "اصلاحیه" in normalize_fa(title)
