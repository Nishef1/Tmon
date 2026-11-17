"""Round 3 of the wide search: whole strategies built from the themes the search found, with a
100-million account that withdraws 10 million every 20 trading days.
(docs/reports/treasure-hunt-2026-11.md)

Every strategy picks up to 10 stocks at a close, buys at the next close, holds 20 trading days and
sells (1.75% round trip); out of the market it earns CASH per period (an assumed deposit rate, about
27% a year, untested). Every start day is used: a start on each of the 20 offsets gives 20 separate
monthly paths per period, so the result is not tied to one rebalance calendar. Periods: O 2019-01 to
2023-03, A 2023-04 to 2024-12, B 2025-01 to the end. B was already looked at in round 2, so it is no
longer clean out of sample; only data after 2026-11-17 is.
Run from backend/ with the live env:  python research/market_method/treasure_strategies.py
Output: results_treasure_strategies.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from treasure_hunt import CASH, H, panel

C = pl.col
HERE = Path(__file__).parent
TOP = 10
TAKE = 10.0

ALL = pl.lit(True)
TIMED = C("q_breadth") == 2
STRATS: dict[str, tuple[pl.Expr, pl.Expr, str | None]] = {
    # name: (stock filter, market gate, rank column descending; None = lowest vol20)
    "basket (all 100)": (ALL, ALL, "all"),
    "basket, only when breadth high": (ALL, TIMED, "all"),
    "top power 5d": (ALL, ALL, "pow5"),
    "top power 5d, sector rising": (C("q_sec_r20") >= 3, ALL, "pow5"),
    "top power 5d, sector rising, timed": (C("q_sec_r20") >= 3, TIMED, "pow5"),
    "dust + money (deep drawdown, power up)": ((C("q_dd") == 0) & (C("q_pow5") >= 3), ALL, "pow5"),
    "usual floor reached + power up": ((C("ddr") >= 1) & (C("q_pow5") >= 3), ALL, "pow5"),
    "deepest drawdown (dust)": (C("q_dd") == 0, ALL, "dd_neg"),
    "trend: 120d top, upper range": ((C("q_r120") == 4) & (C("q_pos60") >= 3), ALL, "r120"),
    "trend, timed": ((C("q_r120") == 4) & (C("q_pos60") >= 3), TIMED, "r120"),
}


def period_returns(a: pl.DataFrame, filt: pl.Expr, gate: pl.Expr, rank: str | None) -> pl.DataFrame:
    """Each day: the H-day return of the strategy bought that day (cash if gated out or empty)."""
    d = a.with_columns(dd_neg=-C("dd"))
    on = d.group_by("date").agg(gate=gate.first() if gate is not ALL else pl.lit(True))
    if rank == "all":
        r = d.group_by("date").agg(r=C("f20").mean(), k=pl.len())
    else:
        r = (
            d.filter(filt)
            .sort("date", rank, descending=[False, True], nulls_last=True)
            .group_by("date", maintain_order=True)
            .head(TOP)
            .group_by("date")
            .agg(r=C("f20").mean(), k=pl.len())
        )
    out = on.join(r, on="date", how="left").with_columns(
        r=pl.when(C("gate") & (C("k").fill_null(0) > 0)).then(C("r")).otherwise(CASH)
    )
    return out.join(a.select("date", "half").unique(), on="date").sort("date")


def paths(per: pl.DataFrame, half: str) -> list[list[float]]:
    d = per.filter(C("half") == half)["r"].to_list()
    return [d[o::H] for o in range(H)]


def account(rs: list[float]) -> tuple[float, int]:
    cap = 100.0
    for i, r in enumerate(rs):
        cap = cap * (1 + r) - TAKE * 1.0113
        if cap <= 0:
            return 0.0, i + 1
    return cap, len(rs)


def main() -> None:
    a, _ids = panel()
    out = {}
    for name, (filt, gate, rank) in STRATS.items():
        per = period_returns(a, filt, gate, rank)
        row = {}
        for h in ("O", "A", "B"):
            ps = paths(per, h)
            allr = np.array([x for p in ps for x in p])
            acc = [account(p[:12]) for p in ps if len(p) >= 12]
            grow = [float(np.prod([1 + x for x in p])) ** (1 / len(p)) - 1 for p in ps if p]
            row[h] = {
                "mean": float(allr.mean()),
                "median": float(np.median(allr)),
                "geo_month": float(np.median(grow)),
                "p10": float(np.percentile(allr, 10)),
                "ge10": float((allr >= 0.10).mean()),
                "neg": float((allr < 0).mean()),
                "end12_median": float(np.median([c for c, _ in acc])) if acc else None,
                "broke12": float(np.mean([c <= 0 for c, _ in acc])) if acc else None,
            }
        out[name] = row
        print(
            name,
            "  ".join(
                f"{h}: geo {v['geo_month'] * 100:+.1f}% >=10% {v['ge10'] * 100:.0f}% "
                f"neg {v['neg'] * 100:.0f}% 12m {v['end12_median'] or 0:.0f} broke {v['broke12']}"
                for h, v in row.items()
            ),
        )
    (HERE / "results_treasure_strategies.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
