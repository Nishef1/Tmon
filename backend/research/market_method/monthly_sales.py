"""Monthly revenue of each company from its Codal monthly-activity report (ن-۳۰), read from the pages
the browser pane stored (raw_payloads, source codal, url with let=58).

The page carries the whole report as JSON (`var datasource = {...}`): sheets, tables, cells with row
and column sequence. The revenue table is found by its alias (production, services, construction,
leasing, insurance); its last row labelled «جمع» is the total, and the column whose header says
«دوره یک ماهه» is the month. Amounts are million rial. Banks and holdings have no revenue total in
this form and are left out (template = None).

parse_page(html) -> dict or None. build() -> DataFrame, one row per (symbol, period end), the latest
published version winning (a correction replaces the original).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

import polars as pl

DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
STORE = Path(os.environ.get("TMON_OBJECT_STORE_DIR", "D:/Data/Tmon/data/objects")) / "raw-payloads"
ALIASES = (
    "ProductionAndSales",
    "ServicesAndSale",
    "RealizedOperatingIncome",
    "AchievedRevenue",
    "MonthlyPerformance",
)
_ARABIC = str.maketrans("يكۀ", "یکه")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_ARABIC)).strip()


def _num(s: str) -> float | None:
    t = s.translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _datasource(html: str) -> dict | None:
    i = html.find("var datasource =")
    if i < 0:
        return None
    try:
        d, _ = json.JSONDecoder().raw_decode(html[i + len("var datasource =") :].lstrip())
    except ValueError:
        return None
    return d


def _headers(cells: list[dict]) -> dict[int, str]:
    """Column -> header text (every header cell spanning the column, joined)."""
    out: dict[int, list[str]] = {}
    for c in cells:
        if c["cellGroupName"] != "Header" or not c["value"]:
            continue
        for col in range(c["columnSequence"], c["columnSequence"] + max(c.get("colSpan") or 1, 1)):
            out.setdefault(col, []).append(_norm(c["value"]))
    return {k: " | ".join(v) for k, v in out.items()}


def _month_col(head: dict[int, str]) -> int | None:
    cands = [
        col
        for col, h in sorted(head.items())
        if col > 1 and ("یک ماهه" in h or "یک ما" in h or "طی دوره" in h or "دوره یکماهه" in h)
    ]
    money = [c for c in cands if "مبلغ" in head[c] or "درآمد" in head[c] or "حق بیمه" in head[c]]
    pick = money or cands
    if not pick:
        return None
    # production: the month group has «مبلغ فروش»; insurance: the premium column comes first
    sel = [c for c in pick if "مبلغ فروش" in head[c]]
    return (sel or pick)[0]


def parse_page(html: str) -> dict | None:
    d = _datasource(html)
    if d is None:
        return None
    for sheet in d.get("sheets", []):
        for t in sheet.get("tables", []):
            if t.get("aliasName") not in ALIASES:
                continue
            cells = t["cells"]
            head = _headers(cells)
            col = _month_col(head)
            if col is None:
                continue
            total_rows = sorted(
                {
                    c["rowSequence"]
                    for c in cells
                    if c["columnSequence"] == 1 and _norm(c["value"]) == "جمع"
                }
            )
            if not total_rows:
                continue
            row = total_rows[-1]
            val = next(
                (
                    _num(c["value"])
                    for c in cells
                    if c["rowSequence"] == row and c["columnSequence"] == col
                ),
                None,
            )
            if val is None:
                continue
            return {
                "template": t["aliasName"],
                "tracing_no": d.get("tracingNo"),
                "period_end": d.get("periodEndToDate"),
                "month": val,
            }
    return None


def build() -> pl.DataFrame:
    con = sqlite3.connect(DB, uri=True)
    keys = dict(
        con.execute(
            "select source_url, object_key from raw_payloads "
            "where source = 'codal' and source_url like '%Decision.aspx%let=58%' order by id"
        ).fetchall()
    )
    letters = {
        r[0]: r[1:]
        for r in con.execute(
            "select tracing_no, symbol, instrument_id, published_at, title from codal_letters"
        ).fetchall()
    }
    rows = []
    for url, key in keys.items():
        p = STORE / key
        if not p.exists():
            continue
        r = parse_page(p.read_text(encoding="utf-8", errors="ignore"))
        if r is None:
            rows.append({"tracing_no": None, "url": url, "template": None})
            continue
        sym, iid, pub, title = letters.get(r["tracing_no"], (None, None, None, None))
        rows.append({**r, "url": url, "symbol": sym, "instrument_id": iid, "published_at": pub, "title": title})
    return pl.DataFrame(rows)


if __name__ == "__main__":
    df = build()
    print(df.height, "pages;", df.filter(pl.col("template").is_not_null()).height, "parsed")
    print(df.group_by("template").len())
    print(df.filter(pl.col("template").is_not_null()).head(8))
