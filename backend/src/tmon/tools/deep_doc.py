"""The deep-learning study as a stored document (no torch needed to read or judge it).

``tmon.backtest.deep_study`` writes the raw per-method numbers. This module adds the same four-part
gate the living ranking uses (``tmon.engine.adapt.gate``) to every method of every horizon, judged
over the whole out-of-sample period, and stores the result as ``v2/deep_study.json`` for the API.

``python -m tmon.tools.deep_doc [docs/data/deep-study.json]`` re-judges an existing file (after a
change of the gate or the cost) without re-running the study. Nothing here changes production.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.engine.adapt import NOT_ENOUGH, R_COST, R_EXCESS, R_HALVES, R_IC
from tmon.storage.objectstore import get_object_store

KEY = "v2/deep_study.json"
DEFAULT_PATH = Path("docs/data/deep-study.json")
MIN_DATES = 300  # fewer paired dates than this cannot be judged in two halves


def _mean(stat: dict[str, Any] | None) -> float | None:
    return None if not stat else stat.get("mean")


def judge(cell: dict[str, Any], cost: float, min_t: float) -> dict[str, Any]:
    """The gate for one method's numbers; same four conditions as ``adapt.gate``."""
    d_ic, d_ex = cell.get("d_ic"), cell.get("d_ex")
    if not d_ic or (d_ic.get("n") or 0) < MIN_DATES:
        return {"passed": False, "reasons": [NOT_ENOUGH]}
    early, late = _mean(cell.get("d_ic_early")), _mean(cell.get("d_ic_late"))
    t, mean = d_ic.get("t"), d_ic.get("mean")
    top = _mean(cell.get("ex"))
    reasons: list[str] = []
    if not (mean is not None and mean > 0 and t is not None and t >= min_t):
        reasons.append(R_IC)
    if not (early is not None and late is not None and early > 0 and late > 0):
        reasons.append(R_HALVES)
    if not ((_mean(d_ex) or 0) > 0):
        reasons.append(R_EXCESS)
    if not (top is not None and top > cost):
        reasons.append(R_COST)
    return {"passed": not reasons, "reasons": reasons}


def finalize(doc: dict[str, Any], cost: float, min_t: float) -> dict[str, Any]:
    """Add the cost and every method's gate verdict to the study document (in place)."""
    doc["round_trip_cost"] = cost
    doc["min_t"] = min_t
    for cells in doc["results"].values():
        for name, cell in cells.items():
            cell["gate"] = None if name == "equal" else judge(cell, cost, min_t)
    return doc


def store_doc(doc: dict[str, Any]) -> None:
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")


def current_cost(day: Any) -> float:
    cfg = get_engine_config()
    with session_scope() as s:
        rules = RuleBook.from_session(s)
    return float(CostModel.from_rules(rules, day, cfg.costs.slippage_fraction).round_trip)


def finish_file(path: Path) -> dict[str, Any]:
    """Judge the study file at ``path``, rewrite it with the verdicts and store it for the API."""
    from datetime import date

    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf8"))
    cost = current_cost(date.fromisoformat(doc["last"]))
    finalize(doc, cost, get_engine_config().adapt.min_t)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf8")
    store_doc(doc)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-deep-doc")
    ap.add_argument("path", nargs="?", default=str(DEFAULT_PATH))
    a = ap.parse_args()
    doc = finish_file(Path(a.path))
    for h, cells in doc["results"].items():
        passed = [n for n, c in cells.items() if c.get("gate") and c["gate"]["passed"]]
        print(f"h{h:>4}: passed the gate -> {passed or 'none'}")
    print(f"{KEY} stored (round trip {doc['round_trip_cost']:.6f})")


if __name__ == "__main__":
    main()
