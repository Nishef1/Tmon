"""Which holding horizon does the per-symbol verdict have evidence for?

The verdict's zones (top half of the day's 100 most liquid names without a buy queue = candidate,
bottom 40% = avoid) are measured exactly as the daily ranking measures them (tools/v2_ranking.py
zone_profile, backtest/invested_study.py decile_table and zone_stats), at 1, 5, 20, 60 and 120
trading days. Net = the zone's mean excess over the 100 names minus one round trip. Each window is
split into two halves of time. Windows: the whole panel and the last three years.
Run from backend/ with the live env:  python research/market_method/horizon_profile.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from tmon.backtest.invested_study import decile_table, zone_stats
from tmon.backtest.signal_decay import build_panel
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.builder import build_features
from tmon.features.store import load_inputs
from tmon.tools.v2_ranking import adjusted_close

HORIZONS = (1, 5, 20, 60, 120)
OUT = Path(__file__).with_name("results_horizon_profile.json")


def main() -> None:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    panel = build_panel(feats, adj, cfg, horizons=HORIZONS)
    last = panel["date"].max()
    assert isinstance(last, date)
    rt = CostModel.from_rules(rules, last, cfg.costs.slippage_fraction).round_trip
    liquidity = feats.select("instrument_id", "date", "median_value_20")
    vc = cfg.v2.verdict
    n_top, n_bot = round(vc.candidate_top_frac * 10), round(vc.avoid_bottom_frac * 10)
    top_idx, bot_idx = list(range(10 - n_top, 10)), list(range(n_bot))
    windows = {
        "all": panel,
        "last3y": panel.filter(pl.col("date") >= date(last.year - 3, last.month, 1)),
    }
    out: dict[str, object] = {"round_trip": rt, "last": str(last), "windows": {}}
    for wname, p in windows.items():
        res = {}
        for h in HORIZONS:
            tab = decile_table(p, liquidity, h, top_n=cfg.v2.invested.profile_top_n)
            mat = tab["mat"]
            res[str(h)] = {
                "days": len(tab["dates"]),
                "first": str(tab["dates"][0]),
                "last": str(tab["dates"][-1]),
                "independent_windows": len(tab["dates"]) // h,
                "candidate": zone_stats(mat, top_idx, 1.0, h, rt, cfg),
                "avoid": zone_stats(mat, bot_idx, -1.0, h, rt, cfg),
                "top_decile": zone_stats(mat, [9], 1.0, h, rt, cfg),
                # before cost, so the gross edge can be set against the round trip
                "candidate_gross": zone_stats(mat, top_idx, 1.0, h, 0.0, cfg)["net"],
            }
            c = res[str(h)]["candidate"]
            print(
                f"{wname:7} h={h:3} days={res[str(h)]['days']:5} gross={res[str(h)]['candidate_gross']:+.4f}"
                f" net={c['net']:+.4f} h1={c['net_h1']:+.4f} h2={c['net_h2']:+.4f} t={c['t']}"
                f" avoid={res[str(h)]['avoid']['net']:+.4f}"
                f" ({res[str(h)]['avoid']['net_h1']:+.4f}/{res[str(h)]['avoid']['net_h2']:+.4f})",
                flush=True,
            )
        out["windows"][wname] = res  # type: ignore[index]
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
