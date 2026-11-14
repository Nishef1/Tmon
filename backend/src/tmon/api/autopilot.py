"""The autopilot as the pages show it: what ``tmon.tools.autopilot`` last stored."""

from __future__ import annotations

from typing import Any

from tmon.api.schemas import AutopilotDeep, AutopilotEvent, AutopilotOut, AutopilotRegime
from tmon.tools.autopilot import KEY

__all__ = ["KEY", "autopilot_out"]


def autopilot_out(doc: dict[str, Any] | None) -> AutopilotOut:
    if not doc:
        return AutopilotOut(available=False)
    reg = doc.get("regime")
    return AutopilotOut(
        available=True,
        checked_at=doc["checked_at"],
        as_of=doc["as_of"],
        regime=AutopilotRegime(**reg) if reg else None,
        deep=AutopilotDeep(**doc["deep"]),
        events=[AutopilotEvent(**e) for e in reversed(doc["events"])],
    )
