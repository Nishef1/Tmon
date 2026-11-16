"""The autopilot: keeps the living algorithm's evidence current without anyone checking.

Nobody knows in advance when the answer changes (a new regime, a champion that loses its edge). So
every daily cycle (``run()``) compares the champions of the living ranking and the regime reading
of the official index with the last check, turns every change into an event and writes the result
to ``v2/autopilot.json``, which the model page shows.

Nothing here changes the production score: that is still decided by the gate in ``engine.adapt``.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from tmon.core.config import get_settings
from tmon.core.timeutil import utcnow
from tmon.storage.objectstore import get_object_store
from tmon.tools import adapt_cycle

KEY = "v2/autopilot.json"
EVENTS_KEEP = 60


def _load(key: str) -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, key)
    except (FileNotFoundError, KeyError):
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


def _events(
    previous: dict[str, Any] | None,
    champions: dict[str, str],
    regime: dict[str, Any] | None,
    at: str,
) -> list[dict[str, Any]]:
    """What changed since the last check, as structured events (the page words them)."""
    if previous is None:
        return []
    new: list[dict[str, Any]] = []
    for h, name in champions.items():
        before = (previous.get("champions") or {}).get(h)
        if before and before != name:
            new.append(
                {"at": at, "kind": "champion", "horizon": int(h), "before": before, "after": name}
            )
    was = (previous.get("regime") or {}).get("stress")
    if regime is not None and was is not None and bool(was) != bool(regime["stress"]):
        new.append({"at": at, "kind": "regime", "after": "stress" if regime["stress"] else "calm"})
    return new


def assess(
    adapt_state: dict[str, Any], previous: dict[str, Any] | None, *, checked_at: str
) -> dict[str, Any]:
    """The autopilot document for the data as it stands. Pure: all inputs are arguments."""
    as_of = date.fromisoformat(adapt_state["as_of"])
    champions = {h: v["champion"] for h, v in adapt_state["horizons"].items()}
    regime = adapt_state.get("regime")
    events = list((previous or {}).get("events") or [])
    events += _events(previous, champions, regime, str(as_of))
    return {
        "checked_at": checked_at,
        "as_of": str(as_of),
        "regime": regime,
        "champions": champions,
        "events": events[-EVENTS_KEEP:],
    }


def _store(doc: dict[str, Any]) -> None:
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")


def run() -> dict[str, Any]:
    """One check of the stored living-ranking state against the previous check."""
    state = adapt_cycle.load_state()
    if state is None:
        return {"skipped": "no adapt state yet"}
    doc = assess(state, _load(KEY), checked_at=utcnow().isoformat(timespec="seconds"))
    _store(doc)
    return {"as_of": doc["as_of"], "events": len(doc["events"])}


def main() -> None:
    print(run())


if __name__ == "__main__":
    main()
