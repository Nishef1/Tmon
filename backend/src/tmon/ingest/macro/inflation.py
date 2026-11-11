"""Inflation import from CSV (C5): the official sources (amar.org.ir, cbi.ir) were not reachable
from this machine on 2026-11-12, so inflation enters by file, one row per release, and every row
must name its source URL and release date (docs/08 point-in-time rule).

Columns (header required, UTF-8): ``series,source,ref_period,value,release_date,source_url``.

* ``series``: ``cpi_mom`` (monthly change), ``cpi_yoy`` (point-to-point) or ``cpi_12m``
  (twelve-month average), as a fraction (0.044 = 4.4%).
* ``source``: ``sci`` (Statistical Centre) or ``cbi`` (central bank).
* ``ref_period``: last Gregorian day of the reference month, ``YYYY-MM-DD``.
* ``release_date``: the day the figure was published, ``YYYY-MM-DD``.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from tmon.ingest.tsetmc.parsers import ParseError

SERIES = ("cpi_mom", "cpi_yoy", "cpi_12m")
SOURCES = ("sci", "cbi")
COLUMNS = ("series", "source", "ref_period", "value", "release_date", "source_url")


def parse_csv(text: str) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = set(COLUMNS) - set(reader.fieldnames or [])
    if missing:
        raise ParseError(f"inflation CSV: missing columns {sorted(missing)}")
    out = []
    for n, r in enumerate(reader, start=2):
        try:
            series, source = r["series"].strip(), r["source"].strip()
            if series not in SERIES or source not in SOURCES:
                raise ValueError(f"series {series!r} / source {source!r} not allowed")
            url = r["source_url"].strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError("source_url must be a URL")
            ref, rel = date.fromisoformat(r["ref_period"]), date.fromisoformat(r["release_date"])
            if rel < ref:
                raise ValueError("release_date before ref_period")
            value = float(r["value"])
            if not -0.5 < value < 1.5:  # 4.4 for 4.4% would be a percent
                raise ValueError(f"value {value} is not a fraction")
        except (ValueError, KeyError, AttributeError) as exc:
            raise ParseError(f"inflation CSV line {n}: {exc}") from exc
        out.append(
            {
                "series": series,
                "source": source,
                "ref_period": ref,
                "value": value,
                "release_date": rel,
                "source_url": url,
            }
        )
    return out
