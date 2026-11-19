"""Monthly CPI of all households from the Statistical Centre of Iran, as rows of
docs/data/inflation.csv (cpi_mom and cpi_yoy per month).

Source: the national CPI time-series workbook on amar.org.ir/prices («شاخص قیمت مصرف کننده کل
خانوارهای کشور»), sheet 9, row «كل كشور» (index, 1400 = 100). amar.org.ir serves an incomplete
certificate chain, so the fetch skips verification; the numbers are checked against the
published Mehr 1405 figures (monthly 4.4%, point-to-point 88.7%) before anything is written.

The workbook has no release dates. The Statistical Centre publishes in the first days of the
next month (Mehr 1405 ended on 22 October and came out on 28 October), so each row's release date
is the reference day plus ``RELEASE_LAG`` days, except rows already in the CSV, which keep theirs.

Usage: python scripts/sci_cpi_csv.py [--from-year 1399]
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from tmon.core.timeutil import from_jalali

URL = "https://amar.org.ir/Portals/0/Statistics/ts_national_140507-14050813162616.xlsx"
CSV = Path(__file__).resolve().parents[2] / "docs" / "data" / "inflation.csv"
RELEASE_LAG = 7
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _sheet(data: bytes, n: int) -> list[list[str]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = [
        "".join(t.text or "" for t in si.iter(f"{NS}t"))
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{NS}si")
    ]
    out = []
    for r in ET.fromstring(z.read(f"xl/worksheets/sheet{n}.xml")).iter(f"{NS}row"):
        vals: dict[int, str] = {}
        for c in r.findall(f"{NS}c"):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):  # type: ignore[union-attr]
                col = col * 26 + ord(ch) - 64
            v = c.find(f"{NS}v")
            if v is not None and v.text is not None:
                vals[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        out.append([vals.get(i, "") for i in range(1, max(vals, default=0) + 1)])
    return out


def _month_end(y: int, m: int):  # type: ignore[no-untyped-def]
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return from_jalali(ny, nm, 1) - timedelta(days=1)


def index_by_month(data: bytes) -> list[tuple[int, int, float]]:
    rows = _sheet(data, 9)
    head = next(r for r in rows if len(r) > 2 and r[1] == "" and "فروردین" in r)
    total = next(r for r in rows if len(r) > 1 and r[0] == "99")
    years = next(r for r in rows if any(str(x).startswith("سال ") for x in r))
    out, year = [], None
    for i in range(2, len(total)):
        if i < len(years) and str(years[i]).startswith("سال "):
            year = int(str(years[i]).split()[1])
        if not total[i] or year is None:
            continue
        month = [
            "فروردین",
            "اردیبهشت",
            "خرداد",
            "تیر",
            "مرداد",
            "شهریور",
            "مهر",
            "آبان",
            "آذر",
            "دی",
            "بهمن",
            "اسفند",
        ].index(head[i].strip()) + 1
        out.append((year, month, float(total[i])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=1399)
    a = ap.parse_args()
    data = httpx.get(URL, verify=False, timeout=60, follow_redirects=True).content
    idx = index_by_month(data)
    at = {(y, m): v for y, m, v in idx}
    rows = []
    for y, m, v in idx:
        if y < a.from_year:
            continue
        prev = at.get((y - 1, 12) if m == 1 else (y, m - 1))
        ago = at.get((y - 1, m))
        ref = _month_end(y, m)
        for series, base in (("cpi_mom", prev), ("cpi_yoy", ago)):
            if base:
                rows.append((series, ref, v / base - 1))
    last = {s: val for s, ref, val in rows if ref == max(r for _, r, _ in rows)}
    if abs(last["cpi_mom"] - 0.044) > 0.002 or abs(last["cpi_yoy"] - 0.887) > 0.002:
        print(f"check failed against Mehr 1405: {last}", file=sys.stderr)
        return 1
    with CSV.open(encoding="utf-8") as f:
        old = list(csv.DictReader(f))
    kept = {(r["series"], r["ref_period"]): r for r in old}
    new = {}
    for series, ref, val in rows:
        k = (series, ref.isoformat())
        if k in kept:
            continue
        new[k] = {
            "series": series,
            "source": "sci",
            "ref_period": ref.isoformat(),
            "value": f"{val:.4f}",
            "release_date": (ref + timedelta(days=RELEASE_LAG)).isoformat(),
            "source_url": URL,
        }
    allrows = sorted([*old, *new.values()], key=lambda r: (r["ref_period"], r["series"]))
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(old[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(allrows)
    print({"added": len(new), "kept": len(old), "last": {k: round(v, 4) for k, v in last.items()}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
