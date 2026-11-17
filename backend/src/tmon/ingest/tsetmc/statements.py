"""Financial statements (balance sheet and income statement) from TSETMC's Codal feed.

``GetStatementContentByInsCode`` returns only the newest 15 filings listed under a symbol, and
holding companies' pages also list their subsidiaries' filings (title ends in ``(شرکت ...)``), which
are skipped. Page 0 is the balance sheet, page 1 the income statement; the two share a publish
time and title, so they are merged into one row.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select

from tmon.core.timeutil import TEHRAN, from_jalali
from tmon.ingest.http import FetchError
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import FinancialStatement, Instrument
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LABEL_FIX = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " ", "\u200f": " "})
_TR = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TD = re.compile(r"<td\b[^>]*?(?:/>|>(.*?)</td>)", re.DOTALL)
_TAG = re.compile(r"<(YearEndToDate|Period|IsAudited|PeriodEndToDate)>([^<]*)")
_SUBSIDIARY = re.compile(r"\(شرکت [^)]*\)\s*$")


def normalize_label(text: str) -> str:
    """Row labels differ in letters and half-spaces between filings; compare them normalised."""
    return " ".join(html.unescape(text).translate(_LABEL_FIX).split())


def parse_number(text: str) -> float | None:
    s = html.unescape(text).translate(_PERSIAN_DIGITS).strip().replace(",", "").replace("٬", "")
    if not s or s in {"-", "—"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_jalali(text: str) -> date | None:
    m = re.match(r"\s*(\d{4})/(\d{1,2})/(\d{1,2})", text.translate(_PERSIAN_DIGITS))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    for day in (d, d - 1):  # the 30th of Esfand does not exist in a non-leap year
        try:
            return from_jalali(y, mo, day)
        except ValueError:
            continue
    return None


@dataclass
class Statement:
    published_at: datetime
    kind: str
    title: str
    period_end: date | None = None
    fiscal_year_end: date | None = None
    period_months: int | None = None
    audited: bool | None = None
    balance: list[list[object]] = field(default_factory=list)
    income: list[list[object]] = field(default_factory=list)


def parse_table(content: str) -> list[list[object]]:
    """``[label, v0, v1, ...]`` per row. The percent column (last) and header columns without a
    title are dropped; value columns are those the header names. Unlabelled rows only repeat a
    subtotal and are skipped."""
    rows = [[html.unescape(c or "") for c in _TD.findall(r)] for r in _TR.findall(content)]
    if len(rows) < 2:
        return []
    # The header does not line up with the rows: annual income pages have an empty column after the
    # label in both, interim income pages only in the rows, and balance rows end with an extra zero
    # column. So the values are the row's cells between label and percent, minus the leading empty
    # cells, cut to as many columns as the header names.
    n_values = sum(1 for h in rows[0][1:-1] if h.strip())
    out: list[list[object]] = []
    for r in rows[1:]:
        if len(r) < 3 or not normalize_label(r[0]):
            continue
        cells = r[1:-1]
        while cells and not cells[0].strip():
            cells = cells[1:]
        out.append([normalize_label(r[0]), *(parse_number(x) for x in cells[:n_values])])
    return out


def parse_statements(payload: str, page: int) -> dict[tuple[datetime, str], Statement]:
    """One payload (page 0 or 1) -> statements keyed by (publish time, kind)."""
    data = json.loads(payload)
    if not isinstance(data, dict) or "statemetnContent" not in data:
        raise parsers.ParseError("statement payload has no 'statemetnContent' key")
    out: dict[tuple[datetime, str], Statement] = {}
    for item in data["statemetnContent"] or []:
        title = normalize_label(str(item.get("title") or ""))
        if _SUBSIDIARY.search(title):
            continue
        raw = item.get("publishDateTime_Gregorian")
        content = item.get("content")
        if not raw or not content:
            continue
        published = datetime.fromisoformat(str(raw)).replace(tzinfo=TEHRAN)
        kind = "consolidated" if "تلفیقی" in title else "separate"
        st = out.setdefault((published, kind), Statement(published, kind, title))
        meta = dict(_TAG.findall(content))
        st.period_end = parse_jalali(meta.get("PeriodEndToDate", ""))
        st.fiscal_year_end = parse_jalali(meta.get("YearEndToDate", ""))
        months = meta.get("Period", "").translate(_PERSIAN_DIGITS).strip()
        st.period_months = int(months) if months.isdigit() else None
        audited = normalize_label(meta.get("IsAudited", ""))
        st.audited = None if not audited else "نشده" not in audited
        if page == 0:
            st.balance = parse_table(content)
        else:
            st.income = parse_table(content)
    return out


async def ingest_statements(
    ctx: Ctx, *, symbols: list[str] | None = None, limit: int | None = None
) -> dict[str, int]:
    """Fetch pages 0 and 1 for each symbol and store the statements. A failed fetch keeps what is
    stored; the endpoint only returns the latest 15 filings, so run it again each month or so."""
    q = select(Instrument).where(Instrument.instrument_type == "stock").order_by(Instrument.id)
    if symbols:
        q = q.where(Instrument.symbol_fa.in_(symbols))
    todo: list[Instrument] = []
    seen: set[str] = set()
    for ins in ctx.session.scalars(q):
        if ins.symbol_fa not in seen:
            seen.add(ins.symbol_fa)
            todo.append(ins)
    if limit:
        todo = todo[:limit]
    out = {"todo": len(todo), "symbols_with_rows": 0, "rows": 0, "failed": 0}
    for n, ins in enumerate(todo, 1):
        merged: dict[tuple[datetime, str], Statement] = {}
        fetched_at = None
        try:
            for page in (0, 1):
                text, fetched_at = await ctx.fetch_text(
                    endpoints.statements_url(ins.ins_code, page), ext="json"
                )
                for key, st in parse_statements(text, page).items():
                    cur = merged.setdefault(key, st)
                    if cur is not st:
                        cur.balance = cur.balance or st.balance
                        cur.income = cur.income or st.income
        except (FetchError, parsers.ParseError, ValueError) as exc:
            ctx.session.rollback()
            out["failed"] += 1
            log.warning("statements of %s failed: %s", ins.symbol_fa, exc)
            continue
        url = endpoints.statements_url(ins.ins_code, 0)
        rows = [
            {
                "instrument_id": ins.id,
                "published_at": s.published_at,
                "kind": s.kind,
                "title": s.title,
                "period_end": s.period_end,
                "fiscal_year_end": s.fiscal_year_end,
                "period_months": s.period_months,
                "audited": s.audited,
                "balance": s.balance,
                "income": s.income,
                "source_url": url,
                "fetched_at": fetched_at,
            }
            for s in merged.values()
        ]
        upsert(ctx.session, FinancialStatement, rows)
        ctx.session.commit()
        out["rows"] += len(rows)
        out["symbols_with_rows"] += bool(rows)
        if n % 25 == 0:
            log.info("statements %d/%d %s", n, len(todo), out)
    return out
