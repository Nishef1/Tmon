"""Per-signal explanations: the features that moved the model's score the most (docs/10 section 7).

Contributions are SHAP values of the tree ensemble in log-odds space, i.e. *before* isotonic
calibration. They answer "what pushed this score up" and are not probabilities.
"""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np


def contributions(booster: lgb.Booster, x: np.ndarray) -> np.ndarray:
    """``(n_rows, n_features)`` SHAP values. Uses ``shap.TreeExplainer`` and falls back to
    LightGBM's own exact tree contributions (``pred_contrib``) if SHAP cannot read the model."""
    if x.shape[0] == 0:
        return np.zeros((0, x.shape[1]))
    try:
        import warnings

        import shap

        with warnings.catch_warnings():  # SHAP warns that binary LightGBM returns a list; handled
            warnings.simplefilter("ignore", UserWarning)
            vals: Any = shap.TreeExplainer(booster).shap_values(x)
        if isinstance(vals, list):  # older SHAP: one array per class
            vals = vals[-1]
        arr = np.asarray(vals, dtype=float)
        if arr.ndim == 3:  # (rows, features, classes)
            arr = arr[:, :, -1]
        return arr
    except Exception:  # SHAP/LightGBM version skew; the fallback is exact too
        full = booster.predict(x, pred_contrib=True, num_iteration=booster.best_iteration or None)
        return np.asarray(full, dtype=float)[:, :-1]  # last column is the bias term


def top_reasons(
    booster: lgb.Booster, x: np.ndarray, names: list[str], k: int = 5
) -> list[list[dict[str, Any]]]:
    """For each row the ``k`` features with the largest absolute contribution, strongest first.

    Each entry: ``{"feature", "value", "contribution"}``. ``value`` is the feature's value on that
    row (``None`` when missing).
    """
    c = contributions(booster, x)
    k = min(k, c.shape[1]) if c.size else 0
    order = np.argsort(-np.abs(c), axis=1)[:, :k]
    out: list[list[dict[str, Any]]] = []
    for r in range(c.shape[0]):  # one entry per recommended signal (a handful), not market data
        row: list[dict[str, Any]] = []
        for j in order[r]:
            v = x[r, j]
            row.append(
                {
                    "feature": names[j],
                    "value": None if not np.isfinite(v) else float(v),
                    "contribution": float(c[r, j]),
                }
            )
        out.append(row)
    return out
