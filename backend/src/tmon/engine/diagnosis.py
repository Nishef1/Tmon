"""Why did a day end with fewer recommendations than hoped? Exact counts and values.

The funnel is computed from the model's output for every symbol of the day's universe (the same
columns ``write_scores`` stores), so each stage is a count a reader can verify against the
screener: universe -> scored -> bucket has enough samples -> EV_net >= min -> p_win >= p_min ->
signal -> portfolio constraints. The binding stage is the first one that removes the most symbols,
and the nearest misses are the symbols closest to passing, with the shortfall in probability
points. Nothing here changes a decision; it only explains it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from tmon.core.engine_config import ThresholdsCfg

NEAREST = 5


def _finite(a: np.ndarray) -> np.ndarray:
    return np.isfinite(a)


def build_diagnosis(
    pred: pl.DataFrame,
    thresholds: ThresholdsCfg,
    *,
    selected: int,
    dropped_by: dict[str, int] | None = None,
) -> dict[str, Any]:
    """``pred`` is ``LightGBMStrategy.predict`` output for the day's universe."""
    n = pred.height
    if n == 0 or "p_win" not in pred.columns:
        return {"universe": n, "stages": [], "binding": None, "nearest": [], "stats": {}}

    p = pred["p_win"].cast(pl.Float64).to_numpy()
    ev = pred["ev"].cast(pl.Float64).to_numpy()
    p_min = pred["p_min"].cast(pl.Float64).to_numpy()
    p_be = pred["p_breakeven"].cast(pl.Float64).to_numpy()
    bucket_n = pred["bucket_n"].cast(pl.Float64).to_numpy()
    sig = pred["signal"].to_numpy().astype(bool)

    scored = _finite(p) & _finite(ev)
    enough = scored & (bucket_n >= thresholds.min_bucket_samples)
    ev_ok = enough & (ev >= thresholds.ev_min_abs)
    p_ok = ev_ok & _finite(p_min) & (p >= p_min)
    p_alone = scored & _finite(p_min) & (p >= p_min)
    alone = {
        "universe": n,
        "scored": int(scored.sum()),
        "bucket": int((scored & (bucket_n >= thresholds.min_bucket_samples)).sum()),
        "ev": int((scored & (ev >= thresholds.ev_min_abs)).sum()),
        "p_min": int(p_alone.sum()),
        "signal": int(sig.sum()),
        "portfolio": int(selected),
    }
    counts = [
        ("universe", "نمادهای جهان امروز", n),
        ("scored", "دارای امتیاز مدل", int(scored.sum())),
        (
            "bucket",
            f"سطل احتمال با دست‌کم {thresholds.min_bucket_samples} نمونهٔ آماری",
            int(enough.sum()),
        ),
        ("ev", f"سود خالص مورد انتظار ≥ {thresholds.ev_min_abs * 100:.2f}٪", int(ev_ok.sum())),
        ("p_min", "احتمال برد ≥ حداقل احتمال همان سطل", int(p_ok.sum())),
        ("signal", "سیگنال پس از همهٔ شرط‌ها", int(sig.sum())),
        ("portfolio", "پس از محدودیت‌های پرتفوی", int(selected)),
    ]
    stages: list[dict[str, Any]] = []
    prev = n
    for key, label, cnt in counts:
        stages.append(
            {
                "key": key,
                "label": label,
                "count": cnt,
                "lost": max(prev - cnt, 0),
                "alone": alone[key],
            }
        )
        prev = cnt
    # the first stage after "universe" that lost the most symbols is the binding one
    lost = [(s["lost"], s["key"]) for s in stages[1:]]
    binding = max(lost)[1] if lost and max(lost)[0] > 0 else None

    # nearest misses: highest EV among the scored symbols that did not become a signal
    miss = np.where(scored & ~sig)[0]
    order = miss[np.argsort(-ev[miss])][:NEAREST] if miss.size else np.array([], dtype=int)
    ids = pred["instrument_id"].to_list()
    nearest = [
        {
            "instrument_id": int(ids[i]),
            "p_win": float(p[i]),
            "p_min": None if not np.isfinite(p_min[i]) else float(p_min[i]),
            "shortfall": None if not np.isfinite(p_min[i]) else float(p_min[i] - p[i]),
            "ev": float(ev[i]),
            "bucket_n": int(bucket_n[i]) if np.isfinite(bucket_n[i]) else 0,
            "failed": _failed(
                bool(enough[i]), float(ev[i]), float(p[i]), float(p_min[i]), thresholds
            ),
        }
        for i in order
    ]

    def stat(a: np.ndarray, mask: np.ndarray, fn: Any) -> float | None:
        v = a[mask & _finite(a)]
        return float(fn(v)) if v.size else None

    return {
        "universe": n,
        "stages": stages,
        "binding": binding,
        "nearest": nearest,
        "dropped_by_portfolio": dropped_by or {},
        "stats": {
            "p_win_max": stat(p, scored, np.max),
            "p_win_median": stat(p, scored, np.median),
            "p_min_median": stat(p_min, scored, np.median),
            "p_breakeven_median": stat(p_be, scored, np.median),
            "ev_max": stat(ev, scored, np.max),
            "ev_median": stat(ev, scored, np.median),
            "n_ev_positive": int((scored & (ev > 0)).sum()),
            "n_distinct_p_win": int(np.unique(np.round(p[scored], 4)).size),
        },
        "thresholds": {
            "ev_min_abs": thresholds.ev_min_abs,
            "min_bucket_samples": thresholds.min_bucket_samples,
            "margin": thresholds.margin,
            "p_floor": thresholds.p_floor,
        },
    }


def _failed(enough: bool, ev: float, p: float, p_min: float, t: ThresholdsCfg) -> list[str]:
    out: list[str] = []
    if not enough:
        out.append("bucket")
    if ev < t.ev_min_abs:
        out.append("ev")
    if not np.isfinite(p_min) or p < p_min:
        out.append("p_min")
    return out
