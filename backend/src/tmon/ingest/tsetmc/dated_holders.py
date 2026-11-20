"""Monthly share counts and major-shareholder lists on past days, from TSETMC's dated pages.

``share_changes`` records capital raises only for the symbols TSETMC lists them for, and
``shareholders`` holds today's list only. For the most traded names (and every leveraged fund) this
samples the first trading day of each month:

- ``/api/Instrument/GetInstrumentHistory/{ins}/{yyyymmdd}``: ``zTitad``, the share count that day;
- ``/api/Shareholder/{ins}/{yyyymmdd}``: the holders of about 1% or more that day.

``python -m tmon.ingest.tsetmc.dated_holders --top 100 --months 36`` backfills; it is resumable
(months already stored are skipped). Every payload is stored raw before it is parsed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import httpx
from sqlalchemy import text

from tmon.core.db import session_scope
from tmon.core.timeutil import utcnow
from tmon.ingest.tsetmc.endpoints import CDN
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.storage.models import ShareholderHistory, SharesHistory
from tmon.storage.objectstore import get_object_store, store_raw_payload
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

SOURCE = "tsetmc_dated"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SHARES_URL = f"{CDN}/api/Instrument/GetInstrumentHistory/{{ins}}/{{d}}"
HOLDERS_URL = f"{CDN}/api/Shareholder/{{ins}}/{{d}}"


def plan_jobs(
    top: int, months: int, extra_types: Sequence[str] = ()
) -> list[tuple[int, str, date]]:
    """``(instrument_id, ins_code, day)`` for the first trading day of each of the last ``months``
    months, for the ``top`` stocks by traded value over the last year plus every instrument of
    ``extra_types``, minus the days already in ``shares_history``."""
    if not all(t.replace("_", "").isalnum() for t in extra_types):
        raise ValueError(f"bad instrument type in {extra_types!r}")
    extra = ", ".join(f"'{t}'" for t in extra_types) or "''"
    q = text(
        """
        with last as (select max(date) as d from prices_daily),
        firsts as (
            select min(date) as day from prices_daily, last
            where date > date(last.d, :span)
            group by strftime('%Y-%m', date)
        ),
        names as (
            select * from (
                select p.instrument_id as iid from prices_daily p, last, instruments i
                where i.id = p.instrument_id and i.instrument_type = 'stock'
                  and p.date > date(last.d, '-365 day') and p.volume > 0
                group by p.instrument_id order by sum(p.value) desc limit :top
            )
            union
            select i.id from instruments i where i.instrument_type in ({extra})
              and i.delisted_at is null
        )
        select i.id, i.ins_code, f.day
        from names n join instruments i on i.id = n.iid, firsts f
        where not exists (
            select 1 from shares_history h where h.instrument_id = i.id and h.date = f.day
        )
        order by i.id, f.day
        """.replace("{extra}", extra)
    )
    with session_scope() as s:
        rows = s.execute(q, {"top": top, "span": f"-{months} month"}).all()
    return [(int(r[0]), str(r[1]), date.fromisoformat(str(r[2]))) for r in rows]


def parse_shares(data: dict[str, Any]) -> tuple[float | None, float | None]:
    h = data.get("instrumentHistory") or {}
    z, b = h.get("zTitad"), h.get("baseVol")
    return (float(z) if z else None, float(b) if b else None)


def parse_holders(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for r in data.get("shareShareholder") or []:
        key, name = r.get("shareHolderShareID"), r.get("shareHolderName")
        if key is None or not name:
            continue
        n, p = r.get("numberOfShares"), r.get("perOfShares")
        out[int(key)] = {
            "holder_key": int(key),
            "name": normalize_fa(str(name)),
            "shares": None if n is None else float(n),
            "percent": None if p is None else float(p),
        }
    return list(out.values())


async def _get(client: httpx.AsyncClient, url: str, tries: int = 4) -> bytes | None:
    for k in range(tries):
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return r.content
            if r.status_code not in (429, 500, 502, 503, 504):
                return None
        except (httpx.TimeoutException, httpx.TransportError):
            pass
        await asyncio.sleep(2.0 * (k + 1))
    return None


def _store(results: list[tuple[int, date, str, bytes, str, bytes]]) -> tuple[int, int]:
    import json

    now = utcnow()
    shares: list[dict[str, Any]] = []
    holders: list[dict[str, Any]] = []
    with session_scope() as s:
        store = get_object_store()
        for iid, day, u_s, p_s, u_h, p_h in results:
            for u, p in ((u_s, p_s), (u_h, p_h)):
                store_raw_payload(
                    s,
                    store,
                    source=SOURCE,
                    source_url=u,
                    payload=p,
                    fetched_at=now,
                    ext="json",
                    content_type="application/json",
                )
            z, b = parse_shares(json.loads(p_s))
            shares.append(
                {
                    "instrument_id": iid,
                    "date": day,
                    "shares": z,
                    "base_volume": b,
                    "source_url": u_s,
                    "fetched_at": now,
                }
            )
            holders.extend(
                {"instrument_id": iid, "date": day, **h, "source_url": u_h, "fetched_at": now}
                for h in parse_holders(json.loads(p_h))
            )
        upsert(s, SharesHistory, shares)
        if holders:
            upsert(s, ShareholderHistory, holders)
    return len(shares), len(holders)


async def collect(
    jobs: Iterable[tuple[int, str, date]], concurrency: int = 6, batch: int = 100
) -> dict[str, int]:
    todo = list(jobs)
    sem = asyncio.Semaphore(concurrency)
    stats = {"jobs": len(todo), "days": 0, "holders": 0, "failed": 0}
    async with httpx.AsyncClient(headers=HEADERS, timeout=60, follow_redirects=True) as client:

        async def one(
            job: tuple[int, str, date],
        ) -> tuple[int, date, str, bytes, str, bytes] | None:
            iid, code, day = job
            d = day.strftime("%Y%m%d")
            u_s, u_h = SHARES_URL.format(ins=code, d=d), HOLDERS_URL.format(ins=code, d=d)
            async with sem:
                p_s = await _get(client, u_s)
                p_h = await _get(client, u_h) if p_s is not None else None
            if p_s is None or p_h is None:
                return None
            return iid, day, u_s, p_s, u_h, p_h

        for i in range(0, len(todo), batch):
            got = await asyncio.gather(*(one(j) for j in todo[i : i + batch]))
            ok = [g for g in got if g is not None]
            stats["failed"] += len(got) - len(ok)
            if ok:
                n_days, n_holders = _store(ok)
                stats["days"] += n_days
                stats["holders"] += n_holders
            log.info("dated_holders %d/%d %s", min(i + batch, len(todo)), len(todo), stats)
            print(min(i + batch, len(todo)), len(todo), stats, flush=True)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-dated-holders")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--months", type=int, default=36)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--extra-types", nargs="*", default=["etf_leveraged"])
    args = ap.parse_args()
    jobs = plan_jobs(args.top, args.months, args.extra_types)
    print("jobs", len(jobs), flush=True)
    print(asyncio.run(collect(jobs, args.concurrency)))


if __name__ == "__main__":
    main()
