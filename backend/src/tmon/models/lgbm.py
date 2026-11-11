"""LightGBM D1 model: classifier -> isotonic calibration -> expected value -> signal and tier.

Follows docs/10 sections 5-8.

Every training window is split in time order into three parts that never share a label window::

    | fit (trees) | early stopping | calibration |

* the trees are fitted on the first part and stopped on the second;
* the third part, which the trees never saw, fits the isotonic map ``raw score -> p_win`` and
  provides the conditional returns for every probability bucket: E[return | win] and
  E[return | lose], taken from the empirical distribution of rows whose calibrated probability
  falls in the same bucket;
* ``EV = p * E[win] + (1 - p) * E[lose] - round_trip_cost`` (``E[lose]`` is negative or small).

A row becomes a signal only if ``p >= p_min`` (raised in defensive mode), ``EV >= multiple *
cost`` and its bucket holds at least ``min_bucket_samples`` calibration rows. Tier A additionally
needs a high ``p`` and a recent bucket accuracy, and is only ever produced when the caller has
explicitly allowed it (``allow_tier_a``) - the engine allows it only after the backtest gate
(``tmon.engine.gating``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from tmon.backtest.costs import round_trip_expr
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import get_feature_set

ARTIFACT_FORMAT = 1


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


class LightGBMStrategy:
    """Implements :class:`tmon.backtest.walkforward.Strategy`."""

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
        # the ranking quality can be measured even when p_min leaves nothing. Never published.
        self.enforce_thresholds = enforce_thresholds
        self.name = name
        self.features: list[str] = list(get_feature_set(timeframe).columns)
        self.booster: lgb.Booster | None = None
        self.cal_x = np.array([0.0, 1.0])
        self.cal_y = np.array([0.0, 1.0])
        self.buckets: BucketTable | None = None
        self.info: dict[str, Any] = {}

    # --- training ---------------------------------------------------------------------------

    def fit(self, train: pl.DataFrame) -> None:
        c = self.cfg
        mc = c.model
        dates = train["date"].unique().sort()
        n_days = dates.len()
        self.info = {"n_train_rows": train.height, "n_days": n_days, "usable": False}
        if n_days < 30:
            return
        cal_i = int(n_days * (1 - mc.calibration_fraction))
        es_i = int(n_days * (1 - mc.calibration_fraction - mc.early_stopping_fraction))
        es_start, cal_start = dates[es_i], dates[cal_i]
        fit = train.filter((pl.col("date") < es_start) & (pl.col("exit_date") < es_start))
        es = train.filter(
            (pl.col("date") >= es_start)
            & (pl.col("date") < cal_start)
            & (pl.col("exit_date") < cal_start)
        )
        cal = train.filter(pl.col("date") >= cal_start)
        params = dict(c.lightgbm.params)
        if min(fit.height, es.height, cal.height) < 2 * int(params.get("min_data_in_leaf", 20)):
            return
        y_fit = fit["y"].cast(pl.Int8).to_numpy()
        y_es = es["y"].cast(pl.Int8).to_numpy()
        y_cal = cal["y"].cast(pl.Int8).to_numpy().astype(float)
        if (
            len(set(y_fit.tolist())) < 2
            or len(set(y_es.tolist())) < 2
            or y_cal.min() == y_cal.max()
        ):
            return

        d_fit = lgb.Dataset(_matrix(fit, self.features), y_fit, feature_name=self.features)
        d_es = lgb.Dataset(_matrix(es, self.features), y_es, reference=d_fit)
        self.booster = lgb.train(
            params,
            d_fit,
            num_boost_round=c.lightgbm.num_boost_round,
            valid_sets=[d_es],
            callbacks=[
                lgb.early_stopping(c.lightgbm.early_stopping_rounds, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        raw_cal = self.booster.predict(
            _matrix(cal, self.features), num_iteration=self.booster.best_iteration or None
        )
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
        p_cal = np.asarray(iso.fit_transform(raw_cal, y_cal))
        self.cal_x = np.asarray(iso.X_thresholds_, dtype=float)
        self.cal_y = np.asarray(iso.y_thresholds_, dtype=float)

        recent_cut = dates[max(0, n_days - mc.recent_days)]
        recent = (cal["date"] >= recent_cut).to_numpy()
        ret = cal["realized_return"].to_numpy().astype(float)
        self.buckets = build_buckets(p_cal, y_cal, ret, recent, c.calibration.n_buckets)
        self.info.update(
            usable=True,
            n_fit=fit.height,
            n_es=es.height,
            n_cal=cal.height,
            best_iteration=int(self.booster.best_iteration or c.lightgbm.num_boost_round),
            es_auc=float(roc_auc_score(y_es, self.booster.predict(_matrix(es, self.features)))),
            cal_base_rate=float(y_cal.mean()),
            cal_brier=float(np.mean((p_cal - y_cal) ** 2)),
            cal_start=cal_start.isoformat(),
        )

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

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        c = self.cfg
        t = c.thresholds
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
        e_win, e_loss = bk.e_win[idx], bk.e_loss[idx]
        cost = (
            test.select(round_trip_expr(self.rules, c.costs.slippage_fraction, "date").alias("c"))[
                "c"
            ]
            .to_numpy()
            .astype(float)
        )
        ev = p * e_win + (1 - p) * e_loss - cost
        defensive = (
            test["defensive"].to_numpy().astype(bool)
            if "defensive" in test.columns
            else np.zeros(test.height, dtype=bool)
        )
        p_min = t.p_min[self.timeframe] + c.defensive_mode.p_min_bump * defensive
        enough = bk.n[idx] >= t.min_bucket_samples
        if self.enforce_thresholds:
            signal = (
                np.isfinite(ev)
                & enough
                & (p >= p_min)
                & (ev >= t.ev_min_cost_multiple * cost)
                & (ev > 0)
            )
        else:
            signal = np.isfinite(ev) & enough & (ev > 0)

        ta, tb = t.tiers.A, t.tiers.B
        recent_ok = (bk.recent_n[idx] >= c.model.min_recent_samples) & (
            bk.recent_accuracy[idx] >= ta.recent_bucket_accuracy_min
        )
        tier_a_ok = signal & (p >= ta.p_win_min) & recent_ok
        tier = np.where(
            tier_a_ok & self.allow_tier_a, "A", np.where(signal & (p >= tb.p_win_min), "B", "C")
        )

        tf = c.labeling.timeframes[self.timeframe]
        atr = test["atr_14_pct"].to_numpy().astype(float)
        risk_w = c.sizing.risk_per_trade / (c.labeling.k_sl * math.sqrt(tf.atr_scale_days) * atr)
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
            pl.Series("signal", signal),
            pl.Series("score", np.where(np.isfinite(ev), ev, -1.0)),
            pl.Series("p_win", p),
            pl.Series("p_raw", raw),
            pl.Series("ev", ev),
            pl.Series("tier", tier),
            pl.Series("tier_a_eligible", tier_a_ok),
            pl.Series("weight", weight),
            pl.Series("bucket_n", bk.n[idx]),
            pl.Series("bucket_recent_accuracy", bk.recent_accuracy[idx]),
            pl.Series("round_trip_cost", cost),
            pl.Series("defensive", defensive),
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
        s.info = doc["info"]
        return s
