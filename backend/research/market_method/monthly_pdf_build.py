"""Parse every downloaded monthly-activity PDF into one table: D:/Data/Tmon/data/monthly-sales.csv
(symbol, jy, jm, published_at, month, ytd), month in million rial. One row per (symbol, month): the first
publication (a later correction is ignored so the date is the day the number first became known).
Only 1-month reports of the production template whose total row has 6 amounts are kept; the rest are skipped
(about a third of the PDFs: other templates or a column layout the parser does not read).
Run with a Python that has pymupdf:  PYTHONPATH=<pymupdf dir> python monthly_pdf_build.py
"""

from __future__ import annotations

import csv
import re
import sqlite3
from multiprocessing import Pool
from pathlib import Path

from monthly_pdf import parse_pdf

DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
PDFS = Path("D:/Data/Tmon/data/monthly-pdf")
OUT = Path("D:/Data/Tmon/data/monthly-sales.csv")
_T = re.compile(r"دوره\s*([0-9۰-۹]+)\s*ماهه منتهی به\s*([0-9۰-۹]{4})/([0-9۰-۹]{2})/")
_D = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _one(t: int):
    f = PDFS / f"{t}.pdf"
    return t, (parse_pdf(f) if f.exists() else None)


def main() -> None:
    con = sqlite3.connect(DB, uri=True)
    rows = con.execute(
        "select tracing_no, symbol, published_at, title from codal_letters "
        "where title like 'گزارش فعالیت ماهانه%' order by published_at"
    ).fetchall()
    with Pool(6) as p:
        parsed = dict(p.map(_one, [r[0] for r in rows], chunksize=20))
    seen: set[tuple[str, int, int]] = set()
    out = []
    for t, sym, pub, title in rows:
        m = _T.search(title or "")
        r = parsed.get(t)
        if not m or r is None or r["ytd"] <= 0:
            continue
        if int(m.group(1).translate(_D)) != 1:
            continue
        jy, jm = int(m.group(2).translate(_D)), int(m.group(3).translate(_D))
        if (sym, jy, jm) in seen:
            continue
        seen.add((sym, jy, jm))
        out.append((sym, jy, jm, pub[:10], r["month"], r["ytd"]))
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "jy", "jm", "published_at", "month", "ytd"])
        w.writerows(out)
    print("rows", len(out), "symbols", len({r[0] for r in out}))


if __name__ == "__main__":
    main()
