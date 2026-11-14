"""The deep-learning study as the pages show it: what ``tmon.tools.deep_doc`` last stored."""

from __future__ import annotations

from typing import Any

from tmon.api.schemas import DeepHorizon, DeepMethod, DeepOut
from tmon.tools.deep_doc import KEY

__all__ = ["KEY", "deep_out"]


def deep_out(doc: dict[str, Any] | None) -> DeepOut:
    if not doc or "round_trip_cost" not in doc:  # absent, or not yet judged
        return DeepOut(available=False)
    return DeepOut(
        available=True,
        first=doc["first"],
        oos_from=doc["oos_from"],
        mid=doc["mid"],
        last=doc["last"],
        device=doc.get("device"),
        torch=doc.get("torch"),
        seeds=doc["seeds"],
        settings=doc["settings"],
        round_trip_cost=doc["round_trip_cost"],
        min_t=doc["min_t"],
        horizons=[
            DeepHorizon(
                horizon_days=int(h),
                methods={n: DeepMethod(**c) for n, c in doc["results"][h].items()},
            )
            for h in sorted(doc["results"], key=int)
        ],
    )
