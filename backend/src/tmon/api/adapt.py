"""The living ranking as the pages show it: what ``tmon.tools.adapt_cycle`` last stored."""

from __future__ import annotations

from typing import Any

from tmon.api.schemas import (
    AdaptConfigOut,
    AdaptDrift,
    AdaptHistoryRow,
    AdaptHorizon,
    AdaptOut,
    AdaptReplay,
    AdaptReplayHorizon,
)
from tmon.tools.adapt_cycle import KEY

__all__ = ["KEY", "adapt_out"]


def _horizon(cell: dict[str, Any]) -> AdaptHorizon:
    win = cell["window"]
    return AdaptHorizon(
        horizon_days=cell["horizon_days"],
        window_from=win["from"],
        window_to=win["to"],
        window_dates=win["dates"],
        champion=cell["champion"],
        why=cell["why"],
        production_expressible=cell["production_expressible"],
        weights=cell["weights"],
        reference_weights=cell["reference_weights"],
        candidates=cell["candidates"],
    )


def adapt_out(doc: dict[str, Any] | None) -> AdaptOut:
    if not doc:
        return AdaptOut(available=False)
    rep = doc.get("replay")
    return AdaptOut(
        available=True,
        as_of=doc["as_of"],
        round_trip_cost=doc["round_trip_cost"],
        config=AdaptConfigOut(**doc["config"]),
        horizons=[_horizon(doc["horizons"][k]) for k in sorted(doc["horizons"], key=int)],
        drift={k: AdaptDrift(**v) for k, v in doc["drift"].items()},
        history=[AdaptHistoryRow(**r) for r in doc["history"]],
        replay=(
            AdaptReplay(
                every=rep["every"],
                as_of=rep.get("as_of"),
                horizons={k: AdaptReplayHorizon(**v) for k, v in rep["horizons"].items()},
            )
            if rep
            else None
        ),
    )
