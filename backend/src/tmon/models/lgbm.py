"""LightGBM model: classifier -> isotonic calibration -> expected value -> signal and tier.

Follows docs/10 sections 5-8, with the thresholds and calibration of ADR 0002 sections 3-5.

Every training window is split in time order into four parts that never share a label window
(:mod:`tmon.models.splits`)::

    | fit (trees) | early stopping | cal_a (isotonic) | cal_b (bucket statistics) |

* the trees are fitted on ``fit`` and stopped on ``es``;
* ``cal_a`` fits the isotonic map ``raw score -> p_win``;
* ``cal_b``, which neither the trees nor the isotonic map saw, provides the statistics of every
  probability bucket: count, accuracy, ``W = E[return | win]`` and the mean return of every
  non-win (stop-loss, same-day, expiry), whose negative is ``L``;
* ``EV_net = p * W + (1 - p) * E[return | not win] - round_trip_cost``.

A row becomes a signal only if ``p >= max(p_breakeven + margin, p_floor)`` (raised in defensive
mode), ``EV_net >= ev_min_abs`` and its bucket holds at least ``min_bucket_samples`` rows
(:mod:`tmon.engine.thresholds`). Tier A additionally needs a high ``p`` and a recent bucket
accuracy, and is only ever produced when the caller has explicitly allowed it (``allow_tier_a``)
- the engine allows it only after the backtest gate (``tmon.engine.gating``).

The barrier pair ``(k_tp, k_sl)`` is chosen by :meth:`LightGBMStrategy.fit_grid`: every pair of the
grid is fitted inside the window and scored by the mean net return per trade its own signals earn
on ``cal_b`` (the inner validation slice); the test period is never involved. The bucket
statistics of that slice also define its signals, so the score is mildly optimistic, equally for
every pair; it only ranks the pairs and is never reported as a result.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from tmon.backtest.costs import add_costs, round_trip_expr
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.engine.thresholds import Decision, decide
from tmon.features.builder import get_feature_set
from tmon.labeling.grid import Combo, default_combo
from tmon.models.splits import split_training_window

ARTIFACT_FORMAT = 2


@dataclass
class BucketTable:
    """Per-bucket statistics of the calibration slice."""

    edges: np.ndarray
    n: np.ndarray
    accuracy: np.ndarray  # share of y == 1
    e_win: np.ndarray  # mean gross return of winners (y == 1)
    e_loss: np.ndarray  # mean gross return of non-winners (y == 0), signed
    recent_n: np.ndarray
    recent_accuracy: np.ndarray

    def index(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(np.clip(np.digitize(p, self.edges[1:-1]), 0, len(self.n) - 1))

    def to_json(self) -> dict[str, Any]:
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in vars(self).items()}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> BucketTable:
        return cls(**{k: np.asarray(v, dtype=float) for k, v in d.items()})


def build_buckets(
    p: np.ndarray,
    y: np.ndarray,
    ret: np.ndarray,
    recent: np.ndarray,
    n_buckets: int,
) -> BucketTable:
    """Bucket statistics over equal-width bins of the calibrated probability.

    A bucket without winners (or losers) borrows the pooled mean of the whole slice, so an EV is
    always defined; whether it may be *used* is decided by ``n`` (and the sample minimum).
    """
    edges = np.linspace(0.0, 1.0, n_buckets + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, n_buckets - 1)
    pooled_win = float(ret[y == 1].mean()) if (y == 1).any() else math.nan
    pooled_loss = float(ret[y == 0].mean()) if (y == 0).any() else math.nan
    n = np.zeros(n_buckets)
    acc = np.full(n_buckets, math.nan)
    ew = np.full(n_buckets, pooled_win)
    el = np.full(n_buckets, pooled_loss)
    rn = np.zeros(n_buckets)
    racc = np.full(n_buckets, math.nan)
    for b in range(n_buckets):  # ten buckets, not market rows
        m = which == b
        n[b] = m.sum()
        if not m.any():
            continue
        acc[b] = y[m].mean()
        if (m & (y == 1)).any():
            ew[b] = ret[m & (y == 1)].mean()
        if (m & (y == 0)).any():
            el[b] = ret[m & (y == 0)].mean()
        r = m & recent
        rn[b] = r.sum()
        if r.any():
            racc[b] = y[r].mean()
    return BucketTable(edges, n, acc, ew, el, rn, racc)


def _matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    return df.select([pl.col(c).cast(pl.Float64) for c in cols]).to_numpy()


@dataclass
class _Fitted:
    """One fitted window (a candidate when the grid is searched)."""

    booster: lgb.Booster
    cal_x: np.ndarray
    cal_y: np.ndarray
    buckets: BucketTable
    info: dict[str, Any]
    cal_b: pl.DataFrame  # inner validation slice, kept only until it has been scored


class LightGBMStrategy:
    """Implements :class:`tmon.backtest.walkforward.Strategy` (and ``fit_grid``)."""

    def __init__(
        self,
        rules: RuleBook,
        cfg: EngineConfig | None = None,
        *,
        timeframe: str = "D1",
        allow_tier_a: bool = False,
        enforce_thresholds: bool = True,
        name: str = "lgbm_d1",
    ) -> None:
        self.cfg = cfg or get_engine_config()
        self.rules = rules
        self.timeframe = timeframe
        self.allow_tier_a = allow_tier_a
        # False = diagnostic only: any EV-positive row with a populated bucket is a "signal", so
        # the ranking quality can be measured even when the thresholds leave nothing. Never
        # published.
        self.enforce_thresholds = enforce_thresholds
        self.name = name
        self.features: list[str] = list(get_feature_set(timeframe).columns)
        self.booster: lgb.Booster | None = None
        self.cal_x = np.array([0.0, 1.0])
        self.cal_y = np.array([0.0, 1.0])
        self.buckets: BucketTable | None = None
        self.info: dict[str, Any] = {}
        self.barrier: Combo = default_combo(timeframe, self.cfg)
        self.grid_log: list[dict[str, Any]] = []

    # --- training ---------------------------------------------------------------------------

    def _fit_window(self, train: pl.DataFrame) -> _Fitted | None:
        """Fit trees, isotonic map and bucket statistics on one label set; ``None`` if the window
        is too short or lacks both classes."""
        c = self.cfg
        sp = split_training_window(train, c.model)
        if sp is None:
            return None
        params = dict(c.lightgbm.params)
        floor = 2 * int(params.get("min_data_in_leaf", 20))
        if min(sp.fit.height, sp.es.height, sp.cal_a.height, sp.cal_b.height) < floor:
            return None
        y_fit = sp.fit["y"].cast(pl.Int8).to_numpy()
        y_es = sp.es["y"].cast(pl.Int8).to_numpy()
        y_a = sp.cal_a["y"].cast(pl.Int8).to_numpy().astype(float)
        y_b = sp.cal_b["y"].cast(pl.Int8).to_numpy().astype(float)
        if any(len(set(v.tolist())) < 2 for v in (y_fit, y_es, y_a, y_b)):
            return None

        d_fit = lgb.Dataset(_matrix(sp.fit, self.features), y_fit, feature_name=self.features)
        d_es = lgb.Dataset(_matrix(sp.es, self.features), y_es, reference=d_fit)
        booster = lgb.train(
            params,
            d_fit,
            num_boost_round=c.lightgbm.num_boost_round,
            valid_sets=[d_es],
            callbacks=[
                lgb.early_stopping(c.lightgbm.early_stopping_rounds, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        it = booster.best_iteration or None
        raw_a = booster.predict(_matrix(sp.cal_a, self.features), num_iteration=it)
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
        iso.fit(raw_a, y_a)
        cal_x = np.asarray(iso.X_thresholds_, dtype=float)
        cal_y = np.asarray(iso.y_thresholds_, dtype=float)

        raw_b = np.asarray(booster.predict(_matrix(sp.cal_b, self.features), num_iteration=it))
        p_b = np.asarray(np.interp(raw_b, cal_x, cal_y))
        recent = (sp.cal_b["date"] >= sp.recent_cut).to_numpy()
        ret_b = sp.cal_b["realized_return"].to_numpy().astype(float)
        buckets = build_buckets(p_b, y_b, ret_b, recent, c.calibration.n_buckets)
        info = {
            "usable": True,
            "n_fit": sp.fit.height,
            "n_es": sp.es.height,
            "n_cal_a": sp.cal_a.height,
            "n_cal_b": sp.cal_b.height,
            "best_iteration": int(booster.best_iteration or c.lightgbm.num_boost_round),
            "es_auc": float(roc_auc_score(y_es, booster.predict(_matrix(sp.es, self.features)))),
            "cal_base_rate": float(y_b.mean()),
            "cal_brier": float(np.mean((p_b - y_b) ** 2)),  # on cal_b: out of sample for both maps
            "cal_start": sp.cal_a_start.isoformat(),
            "cal_b_start": sp.cal_b_start.isoformat(),
        }
        return _Fitted(booster, cal_x, cal_y, buckets, info, sp.cal_b)

    def _adopt(self, f: _Fitted, combo: Combo, n_rows: int, n_days: int) -> None:
        self.booster, self.cal_x, self.cal_y, self.buckets = f.booster, f.cal_x, f.cal_y, f.buckets
        self.barrier = combo
        self.info = {
            "n_train_rows": n_rows,
            "n_days": n_days,
            **f.info,
            "barrier": [combo[0], combo[1]],
        }

    def fit(self, train: pl.DataFrame) -> None:
        """Fit on one label set (the barrier pair stays the configured default)."""
        self.booster, self.buckets = None, None
        n_days = int(train["date"].n_unique()) if train.height else 0
        self.info = {"n_train_rows": train.height, "n_days": n_days, "usable": False}
        f = self._fit_window(train)
        if f is not None:
            self._adopt(f, self.barrier, train.height, n_days)

    def fit_grid(
        self, combos: Sequence[Combo], train_for: Callable[[Combo], pl.DataFrame]
    ) -> Combo:
        """Fit every barrier pair inside the window and keep the one whose signals earned the best
        mean net return per trade on the inner validation slice ``cal_b``.

        ``train_for(combo)`` returns the window's training rows labelled with that pair. A pair
        scores only if it produced at least ``model.grid_min_signals`` signals there; if none does,
        the default pair is kept. Every pair's outcome is recorded in ``grid_log``.
        """
        self.booster, self.buckets = None, None
        self.grid_log = []
        best: tuple[float, Combo, _Fitted, int, int] | None = None
        fallback: tuple[Combo, _Fitted, int, int] | None = None
        default = default_combo(self.timeframe, self.cfg)
        for combo in combos:
            train = train_for(combo)
            n_days = int(train["date"].n_unique()) if train.height else 0
            f = self._fit_window(train)
            rec: dict[str, Any] = {"k_tp": combo[0], "k_sl": combo[1], "usable": f is not None}
            if f is None:
                self.grid_log.append({**rec, "n_signals": 0, "score": None})
                continue
            score, n_sig = self._inner_score(f)
            self.grid_log.append({**rec, "n_signals": n_sig, "score": score})
            f.cal_b = f.cal_b.clear()  # the slice has been used; do not keep it per candidate
            if combo == default or fallback is None:
                fallback = (combo, f, train.height, n_days)
            if score is not None and (best is None or score > best[0]):
                best = (score, combo, f, train.height, n_days)
        if best is not None:
            _, combo, f, rows, days = best
        elif fallback is not None:
            combo, f, rows, days = fallback
        else:
            self.info = {"n_train_rows": 0, "n_days": 0, "usable": False, "grid": self.grid_log}
            self.barrier = default
            return default
        self._adopt(f, combo, rows, days)
        self.info["grid"] = self.grid_log
        self.info["grid_selected_by_score"] = best is not None
        return combo

    def _inner_score(self, f: _Fitted) -> tuple[float | None, int]:
        """Mean net return per trade of the signals this fit would have produced on ``cal_b``."""
        cb = f.cal_b
        raw = np.asarray(
            f.booster.predict(
                _matrix(cb, self.features), num_iteration=f.booster.best_iteration or None
            )
        )
        p = np.asarray(np.interp(raw, f.cal_x, f.cal_y))
        dec, _cost, _w, _l = self._decide(cb, p, f.buckets)
        sig = dec.signal
        n = int(sig.sum())
        if n < self.cfg.model.grid_min_signals:
            return None, n
        net = add_costs(
            cb.select("entry_date", "exit_date", "realized_return"),
            self.rules,
            self.cfg.costs.slippage_fraction,
        )["net_return"].to_numpy()
        return float(np.mean(net[sig])), n

    # --- scoring ----------------------------------------------------------------------------

    def calibrate(self, raw: np.ndarray) -> np.ndarray:
        return np.asarray(np.interp(raw, self.cal_x, self.cal_y))

    def predict_proba(self, df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """``(raw, calibrated)`` probabilities of the triple-barrier win."""
        if self.booster is None:
            base = float(self.info.get("cal_base_rate", 0.0))
            z = np.full(df.height, base)
            return z, z
        raw = self.booster.predict(
            _matrix(df, self.features), num_iteration=self.booster.best_iteration or None
        )
        raw = np.asarray(raw, dtype=float)
        return raw, self.calibrate(raw)

    def _decide(
        self, df: pl.DataFrame, p: np.ndarray, bk: BucketTable
    ) -> tuple[Decision, np.ndarray, np.ndarray, np.ndarray]:
        """Look the bucket statistics up and apply the ADR 0002 rules to ``df``."""
        c = self.cfg
        idx = bk.index(p)
        e_win, e_loss = bk.e_win[idx], bk.e_loss[idx]
        cost = (
            df.select(round_trip_expr(self.rules, c.costs.slippage_fraction, "date").alias("c"))[
                "c"
            ]
            .to_numpy()
            .astype(float)
        )
        defensive = (
            df["defensive"].to_numpy().astype(bool)
            if "defensive" in df.columns
            else np.zeros(df.height, dtype=bool)
        )
        dec = decide(
            p,
            e_win,
            e_loss,
            cost,
            bk.n[idx],
            bk.recent_n[idx],
            bk.recent_accuracy[idx],
            thresholds=c.thresholds,
            model=c.model,
            defensive_bump=c.defensive_mode.p_min_bump * defensive,
            allow_tier_a=self.allow_tier_a,
            enforce=self.enforce_thresholds,
        )
        return dec, cost, e_win, e_loss

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        c = self.cfg
        base = test.select("instrument_id", "date")
        if self.booster is None or self.buckets is None:
            return base.with_columns(
                pl.lit(False).alias("signal"),
                pl.lit(0.0).alias("score"),
                pl.lit(None, dtype=pl.Float64).alias("p_win"),
            )
        raw, p = self.predict_proba(test)
        bk = self.buckets
        idx = bk.index(p)
        dec, cost, e_win, e_loss = self._decide(test, p, bk)
        ev = dec.ev
        defensive = (
            test["defensive"].to_numpy().astype(bool)
            if "defensive" in test.columns
            else np.zeros(test.height, dtype=bool)
        )

        tf = c.labeling.timeframes[self.timeframe]
        k_tp, k_sl = self.barrier
        atr = test["atr_14_pct"].to_numpy().astype(float)
        risk_w = c.sizing.risk_per_trade / (k_sl * math.sqrt(tf.atr_scale_days) * atr)
        with np.errstate(divide="ignore", invalid="ignore"):
            b = np.where(e_loss < 0, e_win / np.abs(e_loss), np.inf)
            kelly = np.where(np.isfinite(b) & (b > 0), p - (1 - p) / b, c.sizing.max_position_pct)
        weight = np.clip(
            np.minimum.reduce(
                [
                    c.sizing.kelly_fraction * kelly,
                    np.full_like(p, c.sizing.max_position_pct),
                    risk_w,
                ]
            ),
            0.0,
            None,
        )
        weight = np.nan_to_num(weight, nan=0.0)

        return base.with_columns(
            pl.Series("signal", dec.signal),
            pl.Series("score", np.where(np.isfinite(ev), ev, -1.0)),
            pl.Series("p_win", p),
            pl.Series("p_raw", raw),
            pl.Series("ev", ev),
            pl.Series("p_breakeven", dec.p_breakeven),
            pl.Series("p_min", dec.p_min),
            pl.Series("tier", dec.tier),
            pl.Series("tier_a_eligible", dec.tier_a_eligible),
            pl.Series("weight", weight),
            pl.Series("bucket_n", bk.n[idx]),
            pl.Series("bucket_recent_accuracy", bk.recent_accuracy[idx]),
            pl.Series("round_trip_cost", cost),
            pl.Series("defensive", defensive),
            pl.lit(k_tp).alias("k_tp"),
            pl.lit(k_sl).alias("k_sl"),
        )

    # --- persistence (JSON + LightGBM text: no pickle) ---------------------------------------

    def to_bytes(self) -> bytes:
        if self.booster is None or self.buckets is None:
            raise ValueError("model is not fitted")
        doc = {
            "format": ARTIFACT_FORMAT,
            "timeframe": self.timeframe,
            "features": self.features,
            "booster": self.booster.model_to_string(),
            "best_iteration": self.booster.best_iteration,
            "cal_x": self.cal_x.tolist(),
            "cal_y": self.cal_y.tolist(),
            "buckets": self.buckets.to_json(),
            "barrier": list(self.barrier),
            "info": self.info,
        }
        return json.dumps(doc, allow_nan=True).encode()

    @classmethod
    def from_bytes(
        cls, data: bytes, rules: RuleBook, cfg: EngineConfig | None = None, **kw: Any
    ) -> LightGBMStrategy:
        doc = json.loads(data)
        if doc.get("format") != ARTIFACT_FORMAT:
            raise ValueError(f"unsupported model artifact format {doc.get('format')!r}")
        s = cls(rules, cfg, timeframe=doc["timeframe"], **kw)
        s.features = doc["features"]
        s.booster = lgb.Booster(model_str=doc["booster"])
        s.booster.best_iteration = int(doc.get("best_iteration") or 0)
        s.cal_x, s.cal_y = np.asarray(doc["cal_x"]), np.asarray(doc["cal_y"])
        s.buckets = BucketTable.from_json(doc["buckets"])
        s.barrier = (float(doc["barrier"][0]), float(doc["barrier"][1]))
        s.info = doc["info"]
        return s
