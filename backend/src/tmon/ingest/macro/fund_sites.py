"""Daily NAV, units and asset mix of each fund from its own website, back to launch (docs/06).

fipiran gives one NAV a fund a day and only from the day we started collecting. Most fund
websites run on one of two platforms that publish the whole history:

- **Rayan Hamafza** (single-page app): ``/api/v1/public/fundItems`` lists the site's funds,
  ``/api/v1/public/nav/{fundId}`` the daily NAVs and units, and
  ``/api/v1/public/dailyAssetStructure/{fundId}`` the daily asset mix.
- **Tadbir** (server pages): the Excel exports ``/Download/DownloadNavChartList`` and
  ``/Download/FundDailyAssetDistribution``. Leveraged funds there carry both units: the premium
  (ممتاز) unit that trades on the exchange and the base (عادی) unit sold on the site.

``python -m tmon.ingest.macro.fund_sites`` backfills every fund whose website fipiran lists
(resumable: funds already stored up to the last week are skipped). ``run_daily`` refreshes the
leveraged funds' last weeks, because fipiran's NAV for them is the fund-level one. Every payload is
stored raw before it is parsed.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import text

from tmon.core.db import session_scope
from tmon.core.timeutil import from_jalali, tehran_today, utcnow
from tmon.storage.models import FundNavHistory
from tmon.storage.objectstore import get_object_store, store_raw_payload
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

SOURCE = "fund_site"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, */*"}
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TSE = re.compile(r"InstInfo/(\d+)")
ZWNJ = chr(0x200C)
VALUES = (
    "issue_nav",
    "cancel_nav",
    "statistical_nav",
    "base_nav",
    "units",
    "base_units",
    "units_issued",
    "units_revoked",
    "net_asset",
    "leverage",
    "unitholders",
    "stock_pct",
    "top5_pct",
    "bond_pct",
    "commodity_pct",
    "cash_pct",
    "fund_unit_pct",
    "other_pct",
)
TADBIR_NAV = "/Download/DownloadNavChartList?exportType=Excel&fromDate={f}&toDate={t}&basketId=0"
TADBIR_ASSET = "/Download/FundDailyAssetDistribution?exportType=Excel&fromDate={f}&toDate={t}"


@dataclass(frozen=True)
class Fund:
    reg_no: str
    ins_code: str | None
    instrument_id: int | None
    website: str
    instrument_type: str | None


def num(v: object) -> float | None:
    """'۱۵,۷۵۷', '%26.33', '-558011837' → float; blanks → None."""
    if v is None:
        return None
    s = str(v).translate(_FA).replace(",", "").replace("٬", "").replace("%", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def jdate(v: object) -> date | None:
    """'1405/08/26' (any digits) → Gregorian date."""
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", str(v or "").translate(_FA).strip())
    if not m:
        return None
    try:
        return from_jalali(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def read_xlsx(payload: bytes) -> list[list[str | None]]:
    """The first sheet as rows of cell text, placing each cell by its column letter."""
    z = zipfile.ZipFile(io.BytesIO(payload))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = [
            "".join(t.text or "" for t in si.iter(_NS + "t")) for si in sst.findall(_NS + "si")
        ]
    out: list[list[str | None]] = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(_NS + "row"):
        cells: dict[int, str | None] = {}
        for c in row.findall(_NS + "c"):
            ref = re.match(r"[A-Z]+", c.get("r", "")) if c.get("r") else None
            col = len(cells)
            if ref:
                col = 0
                for ch in ref.group(0):
                    col = col * 26 + ord(ch) - 64
                col -= 1
            v = c.find(_NS + "v")
            if c.get("t") == "s" and v is not None and v.text is not None:
                cells[col] = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                cells[col] = "".join(t.text or "" for t in c.iter(_NS + "t"))
            else:
                cells[col] = v.text if v is not None else None
        out.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
    return out


def _label(x: object) -> str:
    return re.sub(r"\s+", " ", str(x or "").replace(ZWNJ, "")).strip()


def _table(rows: list[list[str | None]]) -> list[dict[str, str | None]]:
    """Rows under the header row (the one holding «تاریخ»), keyed by the header text."""
    for i, r in enumerate(rows):
        labels = [_label(x) for x in r]
        if "تاریخ" in labels:
            body = rows[i + 1 :]
            return [
                {labels[j]: (r2[j] if j < len(r2) else None) for j in range(len(labels))}
                for r2 in body
            ]
    return []


def _pick(row: dict[str, str | None], *keys: str) -> float | None:
    for k in map(_label, keys):
        if k in row:
            v = num(row[k])
            if v is not None:
                return v
    return None


def parse_tadbir_nav(rows: list[list[str | None]]) -> dict[date, dict[str, Any]]:
    out: dict[date, dict[str, Any]] = {}
    for r in _table(rows):
        d = jdate(r.get("تاریخ"))
        if d is None:
            continue
        if (
            _label("قیمت ابطال واحد های ممتاز") in r
        ):  # leveraged: the premium unit is the traded one
            out[d] = {
                "issue_nav": _pick(r, "قیمت صدور واحد های ممتاز"),
                "cancel_nav": _pick(r, "قیمت ابطال واحد های ممتاز"),
                "statistical_nav": _pick(r, "قیمت اسمی واحد های ممتاز"),
                "base_nav": _pick(r, "قیمت واحد های عادی"),
                "units": _pick(r, "مانده گواهی ممتاز"),
                "base_units": _pick(r, "مانده گواهی عادی"),
                "units_issued": _pick(r, "تعداد واحد ممتاز صادر شده"),
                "units_revoked": _pick(r, "تعداد واحد ممتاز باطل شده"),
                "net_asset": _pick(r, "خالص ارزش صندوق"),
                "leverage": _pick(r, "نسبت اهرمی"),
                "unitholders": _pick(r, "تعداد سرمایه‌گذاران واحدهای عادی"),
            }
        else:
            out[d] = {
                "issue_nav": _pick(r, "قیمت صدور"),
                "cancel_nav": _pick(r, "(قیمت ابطال (خالص ارزش روز", "قیمت ابطال"),
                "statistical_nav": _pick(r, "قیمت آماری"),
                "units": _pick(r, "تعداد واحدهای سرمایه‌گذاری نزد سرمایه‌گذاران"),
                "units_issued": _pick(r, "تعداد واحد صادر شده امروز"),
                "units_revoked": _pick(r, "تعداد واحد باطل شده امروز"),
                "net_asset": _pick(r, "کل خالص ارزش دارایی‌ها"),
            }
    return out


def parse_tadbir_asset(rows: list[list[str | None]]) -> dict[date, dict[str, Any]]:
    out: dict[date, dict[str, Any]] = {}
    for r in _table(rows):
        d = jdate(r.get("تاریخ"))
        if d is None:
            continue
        top5 = _pick(r, "پنج سهم برتر به کل دارایی")
        rest = _pick(r, "سهام به کل دارایی", "سایر سهام به کل دارایی")
        bank = _pick(r, "وجه نقد به کل دارایی")
        dep = _pick(r, "اوراق سپرده به کل دارایی")
        out[d] = {
            "top5_pct": top5,
            "stock_pct": None if top5 is None and rest is None else (top5 or 0) + (rest or 0),
            "bond_pct": _pick(r, "اوراق مشارکت به کل دارایی"),
            "commodity_pct": _pick(r, "گواهی سپرده کالایی به کل دارایی"),
            "cash_pct": None if bank is None and dep is None else (bank or 0) + (dep or 0),
            "fund_unit_pct": _pick(r, "صندوق سرمایه گذاری به کل دارایی"),
            "other_pct": _pick(r, "سایر دارایی‌ها به کل دارایی"),
        }
    return out


def parse_rayan(
    nav: list[dict[str, Any]], asset: list[dict[str, Any]]
) -> dict[date, dict[str, Any]]:
    out: dict[date, dict[str, Any]] = {}
    for r in nav:
        d = jdate(r.get("jalaliDate"))
        if d is None:
            continue
        out[d] = {
            "issue_nav": num(r.get("purchaseNAVPerShare")),
            "cancel_nav": num(r.get("sellNAVPerShare")),
            "statistical_nav": num(r.get("statisticalNAVPerShare")),
            "units": num(r.get("units")),
            "units_issued": num(r.get("issuedUnits")),
            "units_revoked": num(r.get("revokedUnits")),
            "net_asset": num(r.get("nav")),
        }
    for r in asset:
        d = jdate(r.get("date"))
        if d is None:
            continue
        dep, cash = num(r.get("depositTodayPercent")), num(r.get("cashTodayPercent"))
        out.setdefault(d, {}).update(
            {
                "stock_pct": num(r.get("stockTodayPercent")),
                "top5_pct": num(r.get("topFiveStockTodayPercent")),
                "bond_pct": num(r.get("bondTodayPercent")),
                "commodity_pct": num(r.get("ccdTodayPercent")),
                "cash_pct": None if dep is None and cash is None else (dep or 0) + (cash or 0),
                "fund_unit_pct": num(r.get("fundUnitTodayPercent")),
                "other_pct": num(r.get("otherAssetTodayPercent")),
            }
        )
    return out


def targets(types: Sequence[str] = ()) -> list[Fund]:
    """Every fund fipiran lists with a website (latest row per fund), optionally by type."""
    q = text(
        """
        select f.reg_no, f.ins_code, coalesce(f.instrument_id, i.id), f.website, i.instrument_type
        from fund_nav f
        left join instruments i on i.ins_code = f.ins_code
        where f.website like 'http%'
          and f.date = (select max(g.date) from fund_nav g where g.reg_no = f.reg_no)
        """
    )
    with session_scope() as s:
        rows = s.execute(q).all()
    funds = [
        Fund(str(r[0]), r[1], r[2], str(r[3]).rstrip("/"), r[4])
        for r in rows
        if not types or r[4] in types
    ]
    return sorted(funds, key=lambda f: f.reg_no)


def _stored_through() -> dict[str, date]:
    with session_scope() as s:
        rows = s.execute(text("select reg_no, max(date) from fund_nav_history group by reg_no"))
        return {str(r[0]): date.fromisoformat(str(r[1])[:10]) for r in rows}


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    for attempt in range(3):
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return r
            if r.status_code < 500:
                return None
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2 * (attempt + 1))
    return None


def _keep(payload: bytes, url: str, ext: str, ctype: str) -> None:
    with session_scope() as s:
        store_raw_payload(
            s,
            get_object_store(),
            source=SOURCE,
            source_url=url,
            payload=payload,
            fetched_at=utcnow(),
            ext=ext,
            content_type=ctype,
        )


async def _rayan(
    client: httpx.AsyncClient, site: str, funds: list[Fund]
) -> dict[str, tuple[str, dict[date, dict[str, Any]]]] | None:
    r = await _get(client, site + "/api/v1/public/fundItems")
    try:
        items = r.json() if r is not None else None
    except ValueError:
        return None
    if not isinstance(items, list) or not items:
        return None
    by_code = {f.ins_code: f for f in funds if f.ins_code}
    out: dict[str, tuple[str, dict[date, dict[str, Any]]]] = {}
    for it in items:
        m = _TSE.search(str(it.get("tsetmcUrl") or ""))
        fund = by_code.get(m.group(1)) if m else None
        if fund is None and len(items) == 1 and len(funds) == 1:
            fund = funds[0]
        if fund is None:
            continue
        fid = it.get("fundId")
        u_nav = f"{site}/api/v1/public/nav/{fid}"
        u_ast = f"{site}/api/v1/public/dailyAssetStructure/{fid}"
        r_nav, r_ast = await _get(client, u_nav), await _get(client, u_ast)
        if r_nav is None:
            continue
        _keep(r_nav.content, u_nav, "json", "application/json")
        nav = r_nav.json()
        asset: list[dict[str, Any]] = []
        if r_ast is not None:
            _keep(r_ast.content, u_ast, "json", "application/json")
            try:
                asset = r_ast.json()
            except ValueError:
                asset = []
        out[fund.reg_no] = (u_nav, parse_rayan(nav if isinstance(nav, list) else [], asset))
    return out


async def _tadbir(
    client: httpx.AsyncClient, site: str, funds: list[Fund], since: date
) -> dict[str, tuple[str, dict[date, dict[str, Any]]]] | None:
    if len(funds) != 1:  # a Tadbir site serves one fund
        return None
    f_, t_ = since.strftime("%m/%d/%Y"), (tehran_today() + timedelta(days=1)).strftime("%m/%d/%Y")
    u_nav = site + TADBIR_NAV.format(f=f_.replace("/", "%2F"), t=t_.replace("/", "%2F"))
    r_nav = await _get(client, u_nav)
    if r_nav is None or not r_nav.content.startswith(b"PK"):
        return None
    _keep(r_nav.content, u_nav, "xlsx", "application/vnd.ms-excel")
    days = parse_tadbir_nav(read_xlsx(r_nav.content))
    u_ast = site + TADBIR_ASSET.format(f=f_.replace("/", "%2F"), t=t_.replace("/", "%2F"))
    r_ast = await _get(client, u_ast)
    if r_ast is not None and r_ast.content.startswith(b"PK"):
        _keep(r_ast.content, u_ast, "xlsx", "application/vnd.ms-excel")
        for d, v in parse_tadbir_asset(read_xlsx(r_ast.content)).items():
            days.setdefault(d, {}).update(v)
    return {funds[0].reg_no: (u_nav, days)}


async def collect(funds: Sequence[Fund], since: date, concurrency: int = 6) -> dict[str, Any]:
    """Fetch, store raw and upsert every fund's history from ``since``; returns a summary."""
    sites: dict[str, list[Fund]] = {}
    for f in funds:
        sites.setdefault(f.website, []).append(f)
    by_reg = {f.reg_no: f for f in funds}
    sem = asyncio.Semaphore(concurrency)
    summary: dict[str, Any] = {"sites": len(sites), "rayan": 0, "tadbir": 0, "none": [], "rows": 0}
    async with httpx.AsyncClient(headers=HEADERS, timeout=120, follow_redirects=True) as client:

        async def one(site: str, group: list[Fund]) -> None:
            async with sem:
                try:
                    got = await _rayan(client, site, group)
                    platform = "rayan"
                    if not got:
                        got = await _tadbir(client, site, group, since)
                        platform = "tadbir"
                except Exception as e:  # one broken site must not stop the run
                    log.warning("fund site %s failed: %s", site, e)
                    got = None
            if not got:
                summary["none"].append(site)
                return
            summary[platform] += 1
            now = utcnow()
            rows = [
                {
                    "reg_no": reg,
                    "date": d,
                    "instrument_id": by_reg[reg].instrument_id,
                    "platform": platform,
                    **{k: v.get(k) for k in VALUES},
                    "source_url": url,
                    "fetched_at": now,
                }
                for reg, (url, days) in got.items()
                for d, v in days.items()
                if d >= since and v.get("cancel_nav")
            ]
            with session_scope() as s:
                summary["rows"] += upsert(s, FundNavHistory, rows)
            print(f"{platform} {site} rows={len(rows)}", flush=True)

        await asyncio.gather(*[one(site, g) for site, g in sites.items()])
    return summary


def run_daily(days: int = 20) -> dict[str, Any]:
    """Cycle step: the leveraged funds' last ``days`` from their sites (premium-unit NAV)."""
    funds = targets(("etf_leveraged",))
    out = asyncio.run(collect(funds, tehran_today() - timedelta(days=days)))
    return {k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-fund-sites")
    ap.add_argument("--types", nargs="*", default=[], help="instrument types, e.g. etf_leveraged")
    ap.add_argument("--since", default="2005-01-01")
    ap.add_argument("--all", action="store_true", help="refetch funds already stored")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--report", default=None, help="write the summary as JSON here")
    args = ap.parse_args(argv)
    funds = targets(args.types)
    if not args.all:
        done = _stored_through()
        week = tehran_today() - timedelta(days=7)
        funds = [f for f in funds if done.get(f.reg_no, date.min) < week]
    print("funds", len(funds), flush=True)
    out = asyncio.run(collect(funds, date.fromisoformat(args.since), args.concurrency))
    print({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()})
    if args.report:
        with Path(args.report).open("w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
