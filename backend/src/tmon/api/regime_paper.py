"""The market-state paper test as the pages show it: what ``tmon.tools.regime_paper`` stored."""

from __future__ import annotations

from typing import Any

from tmon.api.schemas import RegimeDecision, RegimePaperOut
from tmon.tools.regime_paper import KEY

__all__ = ["KEY", "regime_paper_out"]


def regime_paper_out(doc: dict[str, Any] | None) -> RegimePaperOut:
    if not doc:
        return RegimePaperOut(available=False)
    pending = doc.get("pending")
    fields = {k: doc[k] for k in RegimePaperOut.model_fields if k in doc and k != "pending"}
    return RegimePaperOut(
        available=True,
        **fields,
        pending=RegimeDecision(**pending, state=doc["state"], breadth=doc["breadth"], ranked=[])
        if pending
        else None,
    )
