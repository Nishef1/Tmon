"""Download the PDF of every monthly-activity letter (ن-۳۰) of the basket from TSETMC (no CAPTCHA, no quota):
cdn.tsetmc.com/api/Codal/GetContentFileByTracingNo/{tracingNo}/1  (the Excel variant /0 answers 500).
Files go to data/monthly-pdf/{tracing}.pdf; a file that exists is skipped, so the run is resumable.
The PDF text is read by monthly_pdf.py (digit order is rebuilt from glyph positions).
Run from backend/ with the live env:  python research/market_method/monthly_pdf_fetch.py [part parts]
(parts workers, each takes every parts-th letter; a PDF takes several seconds to arrive)
"""

from __future__ import annotations

import asyncio
import json
import sys
import sqlite3
from pathlib import Path

from tmon.ingest.http import FetchError, PoliteClient

DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
OUT = Path("D:/Data/Tmon/data/monthly-pdf")
URL = "https://cdn.tsetmc.com/api/Codal/GetContentFileByTracingNo/{t}/1"


def todo() -> list[int]:
    basket = set(json.load(open("D:/Data/Tmon/data/liquid-basket.json", encoding="utf-8"))["symbols"])
    con = sqlite3.connect(DB, uri=True)
    rows = con.execute(
        "select tracing_no, symbol from codal_letters where title like 'گزارش فعالیت ماهانه%' "
        "and published_at >= '2023-04-01' order by published_at desc"
    ).fetchall()
    return [t for t, s in rows if s in basket and not (OUT / f"{t}.pdf").exists()]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ids = todo()
    part, parts = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 1)
    ids = ids[part::parts]
    print("to fetch", len(ids), flush=True)
    client = PoliteClient()
    ok = bad = 0
    try:
        for t in ids:
            try:
                r = await client.get(URL.format(t=t))
            except FetchError as exc:
                bad += 1
                print("fail", t, str(exc)[:80], flush=True)
                continue
            if r.content[:4] != b"%PDF":
                bad += 1
                continue
            (OUT / f"{t}.pdf").write_bytes(r.content)
            ok += 1
            if ok % 100 == 0:
                print("ok", ok, "bad", bad, flush=True)
    finally:
        await client.aclose()
    print("done ok", ok, "bad", bad, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
