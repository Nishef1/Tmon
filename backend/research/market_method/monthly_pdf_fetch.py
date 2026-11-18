"""Download the PDF of every monthly-activity letter (ن-۳۰) from TSETMC (no CAPTCHA, no quota):
cdn.tsetmc.com/api/Codal/GetContentFileByTracingNo/{tracingNo}/1 (the Excel variant /0 gives 500).
Files go to data/monthly-pdf/{tracing}.pdf; a file that exists is skipped, so the run is resumable.
The PDF text is read by monthly_pdf.py (digit order is rebuilt from glyph positions).
Run from backend/ with the live env:
  python research/market_method/monthly_pdf_fetch.py [--pit] [part parts]
--pit: every stock that was in the day's top 100 since 2023, letters from 1401 (default: the
fixed basket, letters from 1402). parts workers each take every parts-th letter; a PDF takes
several seconds to arrive. Only letters already in codal_letters are fetched.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from tmon.ingest.http import FetchError, PoliteClient

DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
OUT = Path("D:/Data/Tmon/data/monthly-pdf")
BASKET = "D:/Data/Tmon/data/liquid-basket.json"
URL = "https://cdn.tsetmc.com/api/Codal/GetContentFileByTracingNo/{t}/1"


def pit_symbols() -> set[str]:
    """Every stock that was among the day's top 100 (universe.py) on some day since 2023, so the
    sales table is not limited to survivors (docs/reports/survivorship-basket-2026-11.md)."""
    sys.path.insert(0, str(Path(__file__).parent))
    import universe as uv

    from tmon.core.db import session_scope
    from tmon.features.store import load_inputs

    ids = uv.stock_ids(DB)
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
    mem = uv.pit_members(prices, ids)
    return {ids[i] for i in mem.filter(mem["date"] >= date(2023, 1, 1))["instrument_id"].unique()}


def todo(pit: bool) -> list[int]:
    if pit:  # from 1401 too, so a 1402 month has its base month a year earlier
        names, since = pit_symbols(), "2022-04-01"
    else:
        basket = json.loads(
            Path("D:/Data/Tmon/data/liquid-basket.json").read_text(encoding="utf-8")
        )
        names, since = set(basket["symbols"]), "2023-04-01"
    con = sqlite3.connect(DB, uri=True)
    rows = con.execute(
        "select tracing_no, symbol from codal_letters where title like 'گزارش فعالیت ماهانه%' "
        "and published_at >= ? order by published_at desc",
        (since,),
    ).fetchall()
    return [t for t, s in rows if s in names and not (OUT / f"{t}.pdf").exists()]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pit = "--pit" in sys.argv
    args = [x for x in sys.argv[1:] if x != "--pit"]
    ids = todo(pit)
    part, parts = (int(args[0]), int(args[1])) if len(args) > 1 else (0, 1)
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
