"""How much the fixed 100-name basket flatters a study (docs/reports/survivorship-basket-2026-11.md).

Compares, per period, the equal-weight daily return (clipped at +-15%, no costs) of
  basket  the 100 names of data/liquid-basket.json on every day
  pit     the day's top 100 by 20-day median traded value up to the day before (universe.py)
and counts how many basket names were in the day's top 100.
Run from backend/ with the live env:  python research/market_method/survivorship_bias.py
Output: results_survivorship.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

import universe as uv  # noqa: E402
from fundamentals_study import DB  # noqa: E402
from treasure_hunt import basket_ids  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
PERIODS = {"O": ("2019-01-01", "2023-04-01"), "A": ("2023-04-01", "2025-01-01"), "B": ("2025-01-01", "2100-01-01")}


def main() -> None:
    ids = uv.stock_ids(DB)
    fixed = set(basket_ids())
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
    a = (
        apply_adjustments(prices)
        .filter((C("close") > 0) & C(G).is_in(list(ids)))
        .with_columns(C("date").cast(pl.Date))
        .sort(G, "date")
        .with_columns(r=(C("adj_close") / C("adj_close").shift(1) - 1).over(G).clip(-0.15, 0.15))
    )
    mem = uv.pit_members(prices, ids)
    pit = a.join(mem, on=["date", G], how="semi").group_by("date").agg(pit=C("r").mean())
    fx = a.filter(C(G).is_in(list(fixed))).group_by("date").agg(basket=C("r").mean())
    both = mem.filter(C(G).is_in(list(fixed))).group_by("date").agg(overlap=pl.len())
    d = pit.join(fx, on="date").join(both, on="date", how="left").drop_nulls(["pit", "basket"]).sort("date")
    d = d.with_columns(C("overlap").fill_null(0))
    res: dict = {}
    for name, (lo, hi) in PERIODS.items():
        x = d.filter((C("date") >= pl.lit(lo).str.to_date()) & (C("date") < pl.lit(hi).str.to_date()))
        n = x.height
        gb, gp = float((1 + x["basket"]).product()), float((1 + x["pit"]).product())
        res[name] = {
            "days": n,
            "basket_month": gb ** (21 / n) - 1,
            "pit_month": gp ** (21 / n) - 1,
            "overlap_mean": float(x["overlap"].mean()),
            "overlap_min": int(x["overlap"].min()),
            "overlap_max": int(x["overlap"].max()),
        }
        print(name, {k: round(v, 4) if isinstance(v, float) else v for k, v in res[name].items()})
    (HERE / "results_survivorship.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
