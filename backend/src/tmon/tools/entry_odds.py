"""Entry-odds document (``tmon.backtest.entry_odds``).

``python -m tmon.tools.entry_odds`` writes one JSON document (object store key
``v2/entry_odds.json``): the tested history of every entry setup (green and red streaks, entry
candles in a months-long base, pullbacks in an uptrend) and, per symbol, its streaks, the setups
it is in now and its entry events of the last year for the chart. ``/research/entry-odds`` serves
the history and each symbol's dashboard its part.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from typing import Any

from tmon.backtest import entry_odds as eo
from tmon.backtest import ta_signals as ts
from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs
from tmon.storage.objectstore import get_object_store

KEY = "v2/entry_odds.json"


def build_document() -> dict[str, Any]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
    p = eo.flags(eo.prepare(prices, clients))
    as_of: date = p["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    return {
        "as_of": str(as_of),
        "round_trip_cost": cost,
        "liquid_share": ts.LIQUID_SHARE,
        "horizons": list(eo.H),
        "dir_edge": eo.DIR_EDGE,
        "dip": eo.DIP,
        "dip_within": eo.DIP_WITHIN,
        "win": eo.WIN,
        "loss": eo.LOSS,
        "path": eo.PATH,
        "recent_days": eo.RECENT,
        "base_rule": {"dd": eo.BASE_DD, "range": eo.BASE_RANGE, "days": eo.BASE_DAYS},
        "groups": eo.GROUPS,
        **eo.history(p),
        "now": {str(k): v for k, v in eo.current(p).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-entry-odds")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
    print(f"as_of={doc['as_of']} history={doc['first']}..{doc['last']} split={doc['split_date']}")
    print(f"labels={dict(Counter(v['label'] for v in doc['setups'].values()))}")
    nan = float("nan")
    for k, v in doc["setups"].items():
        cells = []
        for h in eo.H:
            x = v.get(f"h{h}") or {}
            hv = [round(100 * ((b.get(f"h{h}") or {}).get("edge") or nan), 1) for b in v["halves"]]
            cells.append(
                f"h{h} {100 * x.get('up', nan):4.1f}/{100 * x.get('up_all', nan):4.1f} {hv}"
            )
        print(
            f"{k:17s} {v['label']:7s} n={v['n']:8d} dip={100 * (v['dip_hit'] or nan):4.1f}/"
            f"{100 * (v['dip_hit_all'] or nan):4.1f} win={100 * (v['win'] or nan):4.1f}/"
            f"{100 * (v['win_all'] or nan):4.1f} lock={100 * (v['locked_share'] or 0):4.1f} | "
            + " | ".join(cells)
        )
    states = Counter(k for v in doc["now"].values() for k in v["active"])
    print(f"now: symbols={len(doc['now'])} active={dict(states)}")


if __name__ == "__main__":
    main()
