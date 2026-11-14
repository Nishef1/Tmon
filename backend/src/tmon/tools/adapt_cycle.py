"""One cycle of the living ranking (``tmon.engine.adapt``), stored for the API and the pages.

``python -m tmon.tools.adapt_cycle`` re-tests the candidates on the latest window, names the
champion per horizon and writes ``v2/adapt_state.json`` to the artifact store, keeping the history
of earlier cycles (and the last replay). ``--replay`` also re-runs the gate on the whole past
(minutes) and stores what the living ranking would have chosen and how it scored against the fixed
equal weights. Nothing here changes the production score; see ``engine.adapt.weights_for``.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from tmon.backtest.walkforward_study import Panel, build_panel
from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.engine import adapt
from tmon.storage.objectstore import get_object_store

KEY = "v2/adapt_state.json"


def load_state() -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, KEY)
    except (FileNotFoundError, KeyError):
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


def replay_is_stale(previous: dict[str, Any] | None, today: date, refresh_days: int) -> bool:
    """No replay yet, or the last one is ``refresh_days`` or more older than the data."""
    rep = (previous or {}).get("replay")
    if not rep or not rep.get("as_of"):
        return True
    return (today - date.fromisoformat(rep["as_of"])).days >= refresh_days


def build_state(*, with_replay: bool | None = None) -> dict[str, Any]:
    """One cycle. ``with_replay`` None = redo the replay only when it is older than
    ``adapt.replay_refresh_days``; the previous replay is carried over otherwise."""
    cfg = get_engine_config()
    panel = Panel(build_panel())
    with session_scope() as s:
        rules = RuleBook.from_session(s)
    previous = load_state()
    cost = CostModel.from_rules(rules, panel.dates[-1], cfg.costs.slippage_fraction).round_trip
    state = adapt.run_cycle(panel, cfg.adapt, cost, previous)
    if with_replay is None:
        with_replay = replay_is_stale(previous, panel.dates[-1], cfg.adapt.replay_refresh_days)
    if with_replay:
        state["replay"] = adapt.replay(panel, cfg.adapt, cost)
        state["replay"]["as_of"] = state["as_of"]
    return state


def store_state(state: dict[str, Any]) -> bytes:
    data = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    return data


def run() -> dict[str, Any]:
    """The daily-cycle step: one cycle, stored; returns a short summary for the cycle log."""
    state = build_state()
    store_state(state)
    return {
        "as_of": state["as_of"],
        "champions": {h: v["champion"] for h, v in state["horizons"].items()},
        "replay": (state.get("replay") or {}).get("as_of"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-adapt-cycle")
    ap.add_argument("--replay", action="store_true", help="also replay the gate over the past")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    state = build_state(with_replay=True if a.replay else None)
    data = store_state(state)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
    print(f"{KEY}: {len(data)} bytes, as_of={state['as_of']}")
    for h, v in state["horizons"].items():
        print(f"h{h:>4}: {v['champion']:14s} {v['why']}")


if __name__ == "__main__":
    main()
