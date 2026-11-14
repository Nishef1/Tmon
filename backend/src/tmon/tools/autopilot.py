"""The autopilot: keeps the living algorithm and its evidence current without anyone checking.

Nobody knows in advance when the answer changes (a new regime, a method that finally passes the
gate, a champion that loses its edge). So the system watches itself and writes what it saw to
``v2/autopilot.json``, which the model page shows:

* every daily cycle (``run()``, cheap): the champions of the living ranking and the regime reading
  are compared with the last check; every change becomes an event;
* the deep study (``run(refresh_deep=True)``, hours on a GPU, so it runs from its own beat task and
  from ``python -m tmon.tools.autopilot --deep``): redone when it is older than
  ``adapt.deep_refresh_days`` than the data, missing, or when the regime flag flipped after it was
  made. A host without torch cannot redo it; that is recorded as an event and the page says the
  study is old, never silently shows an old study as current.

Nothing here changes the production score: that is still decided by the gate in ``engine.adapt``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from tmon.core.config import get_settings
from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import utcnow
from tmon.storage.objectstore import get_object_store
from tmon.tools import adapt_cycle
from tmon.tools.deep_doc import KEY as DEEP_KEY

KEY = "v2/autopilot.json"
EVENTS_KEEP = 60
DEEP_TIMEOUT_SECONDS = 8 * 3600

# Why the deep study is due (codes; the page words them).
NO_STUDY = "no_study"
OLD = "old"
REGIME = "regime"


def torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def _load(key: str) -> dict[str, Any] | None:
    try:
        raw = get_object_store().get(get_settings().minio_artifact_bucket, key)
    except (FileNotFoundError, KeyError):
        return None
    doc: dict[str, Any] = json.loads(raw)
    return doc


def deep_passed(doc: dict[str, Any] | None) -> list[str]:
    """``method@horizon`` of every method that passed the gate in the stored deep study."""
    out: list[str] = []
    for h, cells in ((doc or {}).get("results") or {}).items():
        for name, cell in cells.items():
            if (cell.get("gate") or {}).get("passed"):
                out.append(f"{name}@{h}")
    return sorted(out)


def _deep_status(
    deep: dict[str, Any] | None,
    as_of: date,
    forced_since: str | None,
    refresh_days: int,
    can_run: bool,
) -> dict[str, Any]:
    last = date.fromisoformat(deep["last"]) if deep and deep.get("last") else None
    age = (as_of - last).days if last else None
    reason: str | None = None
    if last is None:
        reason = NO_STUDY
    elif age is not None and age >= refresh_days:
        reason = OLD
    elif forced_since and last < date.fromisoformat(forced_since):
        reason = REGIME
    return {
        "present": last is not None,
        "last": str(last) if last else None,
        "age_days": age,
        "refresh_days": refresh_days,
        "due": reason is not None,
        "reason": reason,
        "can_run": can_run,
        "passed": deep_passed(deep),
    }


def _events(
    previous: dict[str, Any] | None,
    champions: dict[str, str],
    regime: dict[str, Any] | None,
    deep: dict[str, Any],
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
    was_passed = set((previous.get("deep") or {}).get("passed") or [])
    now_passed = set(deep["passed"])
    if (previous.get("deep") or {}).get("last") != deep["last"]:
        new.append({"at": at, "kind": "deep_refreshed", "passed": sorted(now_passed)})
    if now_passed - was_passed:
        new.append({"at": at, "kind": "deep_passed", "methods": sorted(now_passed - was_passed)})
    if was_passed - now_passed:
        new.append({"at": at, "kind": "deep_lost", "methods": sorted(was_passed - now_passed)})
    return new


def assess(
    adapt_state: dict[str, Any],
    deep: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    *,
    checked_at: str,
    refresh_days: int,
    can_run: bool,
) -> dict[str, Any]:
    """The autopilot document for the data as it stands. Pure: all inputs are arguments."""
    as_of = date.fromisoformat(adapt_state["as_of"])
    champions = {h: v["champion"] for h, v in adapt_state["horizons"].items()}
    regime = adapt_state.get("regime")
    forced = (previous or {}).get("forced_since")
    was = ((previous or {}).get("regime") or {}).get("stress")
    if regime is not None and was is not None and bool(was) != bool(regime["stress"]):
        forced = str(as_of)  # the evidence was made under the other regime: redo it
    status = _deep_status(deep, as_of, forced, refresh_days, can_run)
    if (
        forced
        and status["last"]
        and date.fromisoformat(status["last"]) >= date.fromisoformat(forced)
    ):
        forced = None
        status = _deep_status(deep, as_of, None, refresh_days, can_run)
    events = list((previous or {}).get("events") or [])
    events += _events(previous, champions, regime, status, str(as_of))
    return {
        "checked_at": checked_at,
        "as_of": str(as_of),
        "regime": regime,
        "champions": champions,
        "deep": status,
        "forced_since": forced,
        "events": events[-EVENTS_KEEP:],
    }


def _run_deep_study() -> None:
    """The deep study in its own process (torch stays out of this one); the study stores its own
    judged document at the end, so an interrupted run leaves the previous study in place."""
    with tempfile.TemporaryDirectory(prefix="tmon-deep-") as tmp:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tmon.backtest.deep_study",
                "--out",
                str(Path(tmp) / "study.json"),
            ],
            check=True,
            timeout=DEEP_TIMEOUT_SECONDS,
        )


def _store(doc: dict[str, Any]) -> None:
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")


def run(*, refresh_deep: bool = False) -> dict[str, Any]:
    """One check; with ``refresh_deep`` also redo the deep study when it is due (and possible)."""
    state = adapt_cycle.load_state()
    if state is None:
        return {"skipped": "no adapt state yet"}
    days = get_engine_config().adapt.deep_refresh_days
    previous = _load(KEY)
    can_run = torch_available()
    now = utcnow().isoformat(timespec="seconds")
    doc = assess(
        state, _load(DEEP_KEY), previous, checked_at=now, refresh_days=days, can_run=can_run
    )
    if refresh_deep and doc["deep"]["due"]:
        if can_run:
            _run_deep_study()
            doc = assess(
                state, _load(DEEP_KEY), doc, checked_at=now, refresh_days=days, can_run=True
            )
        else:
            skipped = {"at": doc["as_of"], "kind": "deep_skipped"}
            if skipped not in doc["events"]:  # once per data date, not once per check
                doc["events"] = [*doc["events"], skipped][-EVENTS_KEEP:]
    _store(doc)
    return {
        "as_of": doc["as_of"],
        "deep_due": doc["deep"]["due"],
        "deep_reason": doc["deep"]["reason"],
        "events": len(doc["events"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-autopilot")
    ap.add_argument("--deep", action="store_true", help="also redo the deep study when it is due")
    a = ap.parse_args()
    print(run(refresh_deep=a.deep))


if __name__ == "__main__":
    main()
