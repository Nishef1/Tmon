"""Turning-point document for the symbol page (``tmon.backtest.turning``).

``python -m tmon.tools.turning_points`` writes one JSON document (object store key
``v2/turning.json``): every state's history, today's market state and each symbol's current state.
The API adds the symbol's part to ``/instruments/{id}/dashboard``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from typing import Any

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs
from tmon.storage.objectstore import write_artifact

KEY = "v2/turning.json"
# the trend ride's chart lines, one small document per symbol: in the shared document they would
# make it about six times larger, and every page and search reads that one whole
LINES_KEY = "v2/ride_lines/{iid}.json"


def lines_key(instrument_id: int) -> str:
    return LINES_KEY.format(iid=instrument_id)


def fund_rides(prices: Any, clients: Any, rc: Any) -> dict[str, Any]:
    """``{id: current ride}`` of the comparison funds with a year of history."""
    panel = tp.build_panel(prices, clients) if not prices.is_empty() else None
    if panel is None or panel.is_empty():
        return {}
    out: dict[str, Any] = {}
    for iid, (g, rs) in tr.all_rides(
        panel, rc.near_high, rc.trail, rc.max_hold_days, rc.same_day
    ).items():
        ride = tr.current(g, rs, rc.trail, rc.near_high, rc.max_hold_days)
        if ride:
            out[str(iid)] = ride
    return out


def build_document() -> dict[str, Any]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        fund_prices, fund_clients, _ = load_inputs(s, comparison_funds=True)
        rules = RuleBook.from_session(s)
    panel = tp.build_panel(prices, clients)
    as_of: date = panel["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    rc = cfg.v2.trend_ride
    by_symbol = tr.all_rides(panel, rc.near_high, rc.trail, rc.max_hold_days, rc.same_day)
    symbols = {str(k): v for k, v in tp.current_states(panel).items()}
    for iid, (g, rs) in by_symbol.items():
        ride = tr.current(g, rs, rc.trail, rc.near_high, rc.max_hold_days)
        if ride and str(iid) in symbols:
            symbols[str(iid)]["ride"] = ride
    return {
        "as_of": str(as_of),
        "round_trip_cost": cost,
        "liquid_share": tp.LIQUID_SHARE,
        # the ride of funds the model does not take in (fixed income, commodity, leveraged): the
        # rule needs only the fund's own prices, so it is shown with the fund's own test and
        # without any state, whose history is the stocks' (docs/reports/fund-verdict-2026-11.md)
        "fund_rides": fund_rides(fund_prices, fund_clients, rc),
        "states": [
            {
                "key": st.key,
                "title": st.title,
                "meaning": st.meaning,
                "triggers": [{"to": k, "when": w} for k, w in tp.TRIGGERS.get(st.key, [])],
            }
            for st in tp.STATES
        ],
        "history": tp.state_stats(panel, cost),
        "warning": {
            "key": tp.WARNING.key,
            "title": tp.WARNING.title,
            "meaning": tp.WARNING.meaning,
            "recent_days": tp.WARN_RECENT,
            **tp.warning_stats(panel),
        },
        "market": tp.market_now(panel),
        "trend_ride": {
            "near_high": rc.near_high,
            "trail": rc.trail,
            "max_hold_days": rc.max_hold_days,
            "same_day": rc.same_day,
            "warn_band": rc.warn_band,
            "grade": rc.grade,
            "history_years": rc.history_years,
            "history": tr.history(
                by_symbol, panel, cost, as_of.replace(year=as_of.year - rc.history_years)
            ),
        },
        "symbols": symbols,
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-turning-points")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    for iid, ride in [
        *((i, v.get("ride")) for i, v in doc["symbols"].items()),
        *doc["fund_rides"].items(),
    ]:
        if ride and "sell_line" in ride:
            lines = {k: ride.pop(k) for k in ("sell_line", "buy_line")}
            write_artifact(lines_key(int(iid)), {"as_of": doc["as_of"], **lines})
    write_artifact(KEY, doc, a.out)
    counts = Counter(v["state"] for v in doc["symbols"].values())
    print(f"as_of={doc['as_of']} symbols={len(doc['symbols'])} states={dict(counts)}")
    nan = float("nan")
    w = doc["warning"]
    print(
        f"warning n={w['n']} x60={(w.get('h60') or {}).get('excess_mean', nan):+.3f} "
        f"halves60={[round((b.get('h60') or {}).get('excess_mean', nan), 3) for b in w['halves']]} "
        f"x120={(w.get('h120') or {}).get('excess_mean', nan):+.3f} "
        f"now={sum(1 for v in doc['symbols'].values() if v.get('warn_date'))}"
    )
    rh = doc["trend_ride"]["history"]
    rides = Counter(v["ride"]["status"] for v in doc["symbols"].values() if v.get("ride"))
    print(
        f"trend_ride n={rh['n']} net={rh.get('net_mean', nan):+.3f}"
        f" x={rh.get('excess_mean', nan):+.3f}"
        f" halves={[round(b['excess_mean'], 3) for b in rh.get('halves', [])]} now={dict(rides)}"
    )
    for k, v in doc["history"]["states"].items():
        h = v.get("h120") or {}
        halves = [round((b.get("h120") or {}).get("excess_mean", nan), 3) for b in v["halves"]]
        print(
            f"{k:22s} tone={v['tone']:4s} n={v['n']:7d} ep={v['episodes']:6d} "
            f"x120={h.get('excess_mean', nan):+.3f} med={h.get('excess_median', nan):+.3f} "
            f"halves={halves} up50={h.get('p_up50', nan):.2f} dn20={h.get('p_dn20', nan):.2f}"
        )


if __name__ == "__main__":
    main()
