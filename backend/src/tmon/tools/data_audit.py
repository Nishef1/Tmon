"""Data completeness audit: what the database holds against what the official list says exists.

``python -m tmon.tools.data_audit [--out docs/reports/data-completeness.md]``

Read-only. Every figure is counted from the database; nothing is estimated.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from tmon.core.db import session_scope
from tmon.storage.models import (
    ClientTypeDaily,
    CodalLetter,
    CodalReport,
    Instrument,
    PriceDaily,
    ShareChange,
)


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def collect() -> dict[str, Any]:
    with session_scope() as s:
        ins = list(s.scalars(select(Instrument)))
        bars = {
            iid: (n, first, last)
            for iid, n, first, last in s.execute(
                select(
                    PriceDaily.instrument_id,
                    func.count(),
                    func.min(PriceDaily.date),
                    func.max(PriceDaily.date),
                ).group_by(PriceDaily.instrument_id)
            )
        }
        ct = {
            iid: n
            for iid, n in s.execute(
                select(ClientTypeDaily.instrument_id, func.count()).group_by(
                    ClientTypeDaily.instrument_id
                )
            )
        }
        letters = {
            iid: n
            for iid, n in s.execute(
                select(CodalLetter.instrument_id, func.count())
                .where(CodalLetter.instrument_id.is_not(None))
                .group_by(CodalLetter.instrument_id)
            )
        }
        reports = s.scalar(select(func.count()).select_from(CodalReport)) or 0
        n_letters = s.scalar(select(func.count()).select_from(CodalLetter)) or 0
        n_shares = s.scalar(select(func.count()).select_from(ShareChange)) or 0
        n_bars = s.scalar(select(func.count()).select_from(PriceDaily)) or 0
        newest = s.scalar(select(func.max(PriceDaily.date)))
        by_type: dict[str, Counter[str]] = {}
        for i in ins:
            c = by_type.setdefault(i.instrument_type, Counter())
            c["total"] += 1
            if i.id in bars:
                c["with_bars"] += 1
            if i.id in ct:
                c["with_client_type"] += 1
            if i.id in letters:
                c["with_codal"] += 1
            if i.delisted_at is not None:
                c["exited"] += 1
        in_list = sum(1 for i in ins if (i.tags or {}).get("in_full_list"))
        no_bars = [i for i in ins if i.id not in bars]
        no_bars_in_list = [i for i in no_bars if (i.tags or {}).get("in_full_list")]
        first_year = Counter(bars[i.id][1].year for i in ins if i.id in bars)
        stock_gap = [
            i.symbol_fa
            for i in ins
            if i.instrument_type == "stock" and i.id not in letters and i.id in bars
        ]
        return {
            "instruments": len(ins),
            "in_full_list": in_list,
            "bars": n_bars,
            "newest": newest,
            "n_no_bars": len(no_bars),
            "n_no_bars_in_list": len(no_bars_in_list),
            "no_bars_sample": [i.symbol_fa for i in no_bars_in_list[:15]],
            "by_type": by_type,
            "first_year": dict(sorted(first_year.items())),
            "letters": n_letters,
            "reports": reports,
            "shares": n_shares,
            "stocks_without_codal": len(stock_gap),
            "stocks_without_codal_sample": stock_gap[:20],
        }


def render(d: dict[str, Any]) -> str:
    out = [
        "# Data completeness audit",
        "",
        f"Counted from the database on {date.today().isoformat()}; newest price bar {d['newest']}.",
        "",
        f"- instruments stored: {d['instruments']} (of them in the official full list: "
        f"{d['in_full_list']})",
        f"- daily price bars: {d['bars']:,}",
        f"- instruments in the official list with no price bar at all: "
        f"{d['n_no_bars_in_list']} (never traded, or the source holds none); sample: "
        f"{', '.join(d['no_bars_sample']) or '-'}",
        f"- share-count events: {d['shares']:,}",
        f"- Codal letters: {d['letters']:,}; parsed reports: {d['reports']:,}",
        f"- stocks with bars but no Codal letter: {d['stocks_without_codal']}",
        "",
        "## By instrument type",
        "",
        "| type | total | with bars | with client-type history | with Codal letters | exited |",
        "|---|---|---|---|---|---|",
    ]
    for t, c in sorted(d["by_type"].items(), key=lambda kv: -kv[1]["total"]):
        out.append(
            f"| {t} | {c['total']} | {c['with_bars']} ({_pct(c['with_bars'], c['total'])}) | "
            f"{c['with_client_type']} | {c['with_codal']} | {c['exited']} |"
        )
    out += ["", "## First bar year", "", "| year | instruments |", "|---|---|"]
    out += [f"| {y} | {n} |" for y, n in d["first_year"].items()]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    text = render(collect())
    if a.out:
        Path(a.out).write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    main()
