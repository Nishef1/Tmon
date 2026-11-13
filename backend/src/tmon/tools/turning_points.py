"""Turning-point document for the symbol page (``tmon.backtest.turning``).

``python -m tmon.tools.turning_points`` writes one JSON document (object store key
``v2/turning.json``): every state's history, today's market state and each symbol's current state.
The API adds the symbol's part to ``/instruments/{id}/dashboard``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from typing import Any

from tmon.backtest import turning as tp
from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs
from tmon.storage.objectstore import get_object_store

KEY = "v2/turning.json"


def build_document() -> dict[str, Any]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
    panel = tp.build_panel(prices, clients)
    as_of: date = panel["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    return {
        "as_of": str(as_of),
        "round_trip_cost": cost,
        "liquid_share": tp.LIQUID_SHARE,
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
        "symbols": {str(k): v for k, v in tp.current_states(panel).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-turning-points")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
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
