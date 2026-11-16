"""Glossary-signals document (``tmon.backtest.ta_signals``).

``python -m tmon.tools.ta_signals`` writes one JSON document (object store key
``v2/ta_signals.json``): the tested history of every classic reading of the glossary terms
(1 to 60 candles, both halves of the history), and per symbol its current indicator values, the
readings it fired in its last trading days and its one-year risk numbers. The API serves the
history to the glossary and each symbol's part to its dashboard.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select

from tmon.backtest import ta_signals as ts
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs
from tmon.storage.models import MacroSeries
from tmon.storage.objectstore import write_artifact

KEY = "v2/ta_signals.json"


def build_document() -> dict[str, Any]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
        rf_row = s.execute(
            select(MacroSeries.ref_period, MacroSeries.value)
            .where(MacroSeries.series == "rf_1y_ytm")
            .order_by(MacroSeries.ref_period.desc())
            .limit(1)
        ).first()
    p = ts.flags(ts.with_outcomes(ts.indicators(prices, clients)))
    as_of: date = p["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    rf = float(rf_row[1]) if rf_row is not None else None
    # the yield may be stored in percent
    if rf is not None and rf > 1:
        rf /= 100
    return {
        "as_of": str(as_of),
        "round_trip_cost": cost,
        "liquid_share": ts.LIQUID_SHARE,
        "horizons": list(ts.H),
        "dir_edge": ts.DIR_EDGE,
        "recent_days": ts.RECENT,
        "rf_annual": rf,
        "rf_date": str(rf_row[0]) if rf_row is not None else None,
        **ts.history(p, cost),
        "now": {str(k): v for k, v in ts.current(p).items()},
        "risk": {str(k): v for k, v in ts.risk(p, rf).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-ta-signals")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    write_artifact(KEY, doc, a.out)
    labels = Counter(v["label"] for v in doc["signals"].values())
    print(f"as_of={doc['as_of']} cost={doc['round_trip_cost']:.4f} rf={doc['rf_annual']}")
    print(f"symbols now={len(doc['now'])} risk={len(doc['risk'])} verdicts={dict(labels)}")
    for k, v in doc["signals"].items():
        h20, h5 = v.get("h20") or {}, v.get("h5") or {}
        print(
            f"{k:32s} {v['side']:4s} n={v['n']:6d} {v['label']:14s} "
            f"x5={h5.get('excess_mean', float('nan')):+.4f} "
            f"x20={h20.get('excess_mean', float('nan')):+.4f} "
            f"h20={[round(x, 4) if x is not None else None for x in h20.get('halves', [])]} "
            f"up5={h5.get('up', float('nan')):.3f}/{h5.get('up_all', float('nan')):.3f}"
        )


if __name__ == "__main__":
    main()
