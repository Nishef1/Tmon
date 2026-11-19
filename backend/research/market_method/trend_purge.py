"""Does any trend-ride mark use data from after its own day?

Report: docs/reports/trend-timing-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_purge.py

For each cut date D the prices and client flows after D are deleted, the whole pipeline (price
adjustment, panel, liquidity rank, signals, rides, swings) is rebuilt from what is left, and every
signal, buy and sale dated on or before D is compared with the same from the full data. A mark that
moves or disappears used the future. Hindsight swings are checked too: the run on cut data may
miss the last ones (not confirmed yet), but must never show one the full data does not have.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.features.store import load_inputs

CUTS = [date(2024, 6, 1), date(2025, 3, 1), date(2025, 12, 1), date(2026, 6, 1)]
OUT = Path(__file__).with_name("results_trend_purge.json")


def marks(prices: pl.DataFrame, clients: pl.DataFrame, rc) -> dict:  # noqa: ANN001
    panel = tp.build_panel(prices, clients)
    by = tr.all_rides(panel, rc.near_high, rc.trail, rc.max_hold_days, rc.same_day)
    out = {}
    for iid, (g, rs) in by.items():
        d = g["date"].to_list()
        c = g["close"].to_numpy()
        ev = set()
        for r in rs:
            ev.add(("signal", d[r.signal]))
            if r.entry is not None:
                ev.add(("buy", d[r.entry]))
            if r.exit is not None:
                ev.add(("sell", d[r.exit]))
        sw = {(k, d[i]) for i, k in tr.swings(c, rc.trail)}
        out[iid] = (ev, sw)
    return out


def main() -> None:
    rc = get_engine_config().v2.trend_ride
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    full = marks(prices, clients, rc)
    res: dict = {"cuts": []}
    for cut in CUTS:
        cutm = marks(
            prices.filter(pl.col("date") <= cut), clients.filter(pl.col("date") <= cut), rc
        )
        moved, extra_sw, n, nsw, missing_sw = [], 0, 0, 0, 0
        for iid, (ev, sw) in cutm.items():
            fev, fsw = full.get(iid, (set(), set()))
            a = {e for e in ev if e[1] <= cut}
            b = {e for e in fev if e[1] <= cut}
            n += len(a)
            if a != b:
                moved.append({"iid": iid, "cut_only": sorted(map(str, a - b)),
                              "full_only": sorted(map(str, b - a))})  # fmt: skip
            nsw += len(sw)
            extra_sw += len(sw - fsw)
            missing_sw += len({x for x in fsw if x[1] <= cut} - sw)
        row = {
            "cut": str(cut),
            "symbols": len(cutm),
            "marks": n,
            "symbols_differing": len(moved),
            "examples": moved[:5],
            "swings": nsw,
            "swings_not_in_full": extra_sw,
            "swings_only_in_full": missing_sw,  # the last ones, confirmed only after the cut
        }
        res["cuts"].append(row)
        print({k: v for k, v in row.items() if k != "examples"}, moved[:2])
    res["clean"] = all(r["symbols_differing"] == 0 and r["swings_not_in_full"] == 0
                       for r in res["cuts"])  # fmt: skip
    print("clean", res["clean"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
