"""Daily engine run: dataset -> backtest gate -> final model -> signals -> database.

``train_and_publish`` is the one entry point (Celery calls it after the day's features are
computed). It never fabricates a recommendation: when nothing passes the thresholds, or the data
is too short to train, it records a :class:`SignalNote` saying so and writes no ``Signal`` rows.

Entry prices: a D1 signal is decided at the close of day ``t`` and bought at the open of
``t+1``, which is unknown at decision time. The stored ``entry_price`` is therefore the close of
``t`` (the reference price) and ``entry_rule`` says how the real entry is taken. Take-profit and
stop-loss are built from that reference with the same ATR multiples as the training labels.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from tmon.backtest.baseline import BaselineD1
from tmon.backtest.runner import BacktestRun, prepare_dataset, prepare_label_sets, run_backtest
from tmon.core.config import get_settings
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.engine.gating import BRIER_RECENT_DAYS, GateResult, brier_degraded, evaluate_gate
from tmon.engine.portfolio import select_portfolio
from tmon.features.builder import get_feature_set
from tmon.labeling.grid import Combo, with_labels
from tmon.models.explain import top_reasons
from tmon.models.lgbm import LightGBMStrategy, _matrix
from tmon.storage.models import ModelRun, Signal, SignalNote
from tmon.storage.objectstore import ObjectStore

ENTRY_RULE = "open_next_day"
NO_DATA = "داده کافی برای آموزش مدل وجود ندارد؛ توصیه‌ای صادر نشد."
NO_CANDIDATE = (
    "امروز توصیه‌ای وجود ندارد: هیچ نماد از آستانه‌های احتمال و ارزش مورد انتظار عبور نکرد."
)
NO_PORTFOLIO = "امروز توصیه‌ای وجود ندارد: نمادهای واجد شرایط با محدودیت‌های پرتفوی حذف شدند."
OUTCOMES = {"tp": "tp", "sl": "sl", "sl_same_day": "sl_same_day", "expiry": "expiry"}


@dataclass
class PublishResult:
    timeframe: str
    as_of: date | None
    model_version: str | None = None
    data_snapshot_id: str | None = None
    n_candidates: int = 0
    scores_uri: str | None = None
    n_recommended: int = 0
    defensive_mode: bool = False
    message: str = ""
    gate: GateResult | None = None
    tier_a_disabled_by_monitor: bool = False
    signals: pl.DataFrame = field(default_factory=pl.DataFrame)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_snapshot(ds: pl.DataFrame, store: ObjectStore, bucket: str, prefix: str) -> str:
    """Store the exact dataset a model was built from; return its id (content-addressed)."""
    buf = io.BytesIO()
    ds.write_parquet(buf)
    data = buf.getvalue()
    sid = _sha(data)[:16]
    store.put(bucket, f"{prefix}/{sid}.parquet", data, "application/vnd.apache.parquet")
    return sid


def _barrier_of(metrics: dict[str, Any] | None) -> Combo | None:
    b = ((metrics or {}).get("model") or {}).get("barrier")
    return (float(b[0]), float(b[1])) if b else None


def resolve_outcomes(
    session: Session,
    ds: pl.DataFrame,
    timeframe: str,
    label_sets: Mapping[Combo, pl.DataFrame] | None = None,
) -> int:
    """Fill ``outcome``/``realized_return``/``outcome_date`` of pending signals whose label window
    has closed. A signal is resolved with the barrier pair its model version was trained and
    published with (``ModelRun.metrics["model"]["barrier"]``); versions without a recorded pair, or
    pairs missing from ``label_sets``, use the labels already in ``ds``."""
    pending = session.execute(
        select(Signal.id, Signal.instrument_id, Signal.date, Signal.model_version).where(
            Signal.timeframe == timeframe, Signal.outcome == "pending"
        )
    ).all()
    if not pending:
        return 0
    barriers = {
        r.version: _barrier_of(r.metrics)
        for r in session.execute(
            select(ModelRun.version, ModelRun.metrics).where(ModelRun.timeframe == timeframe)
        ).all()
    }
    p = pl.DataFrame(
        {
            "id": [r.id for r in pending],
            "instrument_id": [r.instrument_id for r in pending],
            "date": [r.date for r in pending],
            "barrier": [barriers.get(r.model_version) for r in pending],
        },
        schema={
            "id": pl.Int64,
            "instrument_id": pl.Int64,
            "date": pl.Date,
            "barrier": pl.List(pl.Float64),
        },
    )
    cols = ("instrument_id", "date", "exit_reason", "realized_return", "exit_date")
    parts: list[pl.DataFrame] = []
    for key in p["barrier"].unique().to_list():
        sub = p.filter(
            pl.col("barrier").is_null() if key is None else pl.col("barrier") == pl.Series([key])
        )
        combo = (float(key[0]), float(key[1])) if key else None
        labels = (
            label_sets[combo] if label_sets and combo is not None and combo in label_sets else ds
        )
        parts.append(
            sub.join(labels.filter(pl.col("valid")).select(*cols), on=["instrument_id", "date"])
        )
    done = pl.concat(parts) if parts else pl.DataFrame()
    rows = [
        {"id": i, "outcome": OUTCOMES.get(r, r), "realized_return": g, "outcome_date": d}
        for i, r, g, d in done.select(
            "id", "exit_reason", "realized_return", "exit_date"
        ).iter_rows()
    ]
    if rows:
        # Bulk UPDATE by primary key. An upsert would INSERT a partial row first, which fails the
        # NOT NULL constraints on signals before ON CONFLICT is ever considered.
        session.execute(update(Signal), rows)
    return len(rows)


def recent_resolved(session: Session, timeframe: str) -> tuple[np.ndarray, np.ndarray]:
    """``(p_win, hit)`` of resolved published signals from the last ``BRIER_RECENT_DAYS``
    signal dates (docs/10 section 9: "Brier of the last 20 days")."""
    done = (Signal.timeframe == timeframe, Signal.outcome != "pending")
    days = session.scalars(
        select(Signal.date)
        .where(*done)
        .distinct()
        .order_by(Signal.date.desc())
        .limit(BRIER_RECENT_DAYS)
    ).all()
    if not days:
        return np.array([]), np.array([])
    rows = session.execute(
        select(Signal.p_win, Signal.outcome).where(*done, Signal.date >= min(days))
    ).all()
    p = np.array([r.p_win for r in rows], dtype=float)
    y = np.array([1.0 if r.outcome == "tp" else 0.0 for r in rows])
    return p, y


def monitor_tier_a(session: Session, timeframe: str, backtest_brier: float | None) -> bool:
    """True when tier A must be switched off: the Brier score of the last
    ``BRIER_RECENT_DAYS`` signal dates of resolved published signals is >20% worse than the
    backtest's (the kill switch of docs/10 section 9)."""
    if backtest_brier is None:
        return False
    p, y = recent_resolved(session, timeframe)
    return brier_degraded(p, y, backtest_brier)


def _risks(
    row: dict[str, Any], defensive: bool, rules: RuleBook, tier_a_blocked: bool
) -> list[str]:
    risks: list[str] = []
    if defensive:
        risks.append("defensive_mode")
    if rules.unverified():
        risks.append("unverified_rules")
    if tier_a_blocked:
        risks.append("tier_a_disabled")
    if (row.get("bucket_n") or 0) < 2 * get_engine_config().thresholds.min_bucket_samples:
        risks.append("thin_probability_bucket")
    risks.append("gap_risk_next_open")  # a D1 entry at the next open can gap away from the close
    return risks


def _record_run(session: Session, *, r: PublishResult) -> None:
    session.execute(
        delete(SignalNote).where(
            SignalNote.date == r.as_of,
            SignalNote.timeframe == r.timeframe,
            SignalNote.model_version == (r.model_version or "none"),
        )
    )
    session.add(
        SignalNote(
            date=r.as_of,
            timeframe=r.timeframe,
            model_version=r.model_version or "none",
            data_snapshot_id=r.data_snapshot_id or "none",
            n_candidates=r.n_candidates,
            n_recommended=r.n_recommended,
            defensive_mode=r.defensive_mode,
            message=r.message[:256],
            created_at=datetime.now(UTC),
        )
    )


def train_and_publish(
    session: Session,
    store: ObjectStore,
    *,
    timeframe: str = "D1",
    inputs: tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame] | None = None,
    rules: RuleBook | None = None,
    cfg: EngineConfig | None = None,
    capital: float | None = None,
    bucket: str | None = None,
) -> PublishResult:
    """Run the whole daily pipeline. ``inputs`` (prices, client types, sectors) and ``rules`` are
    injectable for tests; by default they are read from the database."""
    c = cfg or get_engine_config()
    bucket = bucket or get_settings().minio_artifact_bucket
    capital = capital or c.backtest.initial_capital
    load_bench = inputs is None  # injected inputs (tests) bring no benchmark tables
    if inputs is None:
        from tmon.features.store import load_inputs

        inputs = load_inputs(session)
    prices, clients, sectors = inputs
    rules = rules or RuleBook.from_session(session)
    if prices.is_empty():
        res = PublishResult(timeframe, None, message=NO_DATA)
        return res

    ds = prepare_dataset(prices, clients, rules, sectors=sectors, timeframe=timeframe, cfg=c)
    label_sets = prepare_label_sets(prices, rules, timeframe=timeframe, cfg=c)
    as_of: date = ds["date"].max()  # type: ignore[assignment]
    res = PublishResult(timeframe, as_of)
    fs = get_feature_set(timeframe)
    resolve_outcomes(session, ds, timeframe, label_sets)

    # 1. out-of-sample comparison with the baseline decides what the model may publish
    index_daily: pl.DataFrame | None = None
    rf: pl.DataFrame | None = None
    if load_bench:
        from tmon.features.store import load_benchmark_inputs

        index_daily, rf = load_benchmark_inputs(session)
    run: BacktestRun = run_backtest(
        ds,
        rules,
        {
            "baseline_d1": lambda: BaselineD1(c, rules, timeframe),
            "lgbm_d1": lambda: LightGBMStrategy(rules, c, timeframe=timeframe),
        },
        timeframe=timeframe,
        cfg=c,
        label_sets=label_sets,
        index_daily=index_daily,
        rf=rf,
    )
    chal = run.strategies.get("lgbm_d1")
    base = run.strategies.get("baseline_d1")
    if chal is None:
        res.gate = GateResult(False, ["دادهٔ تاریخی برای آزمون خارج از نمونه کافی نیست."])
    else:
        res.gate = evaluate_gate(chal.summary, base.summary if base else None, c)
    backtest_brier = (chal.summary.get("probabilistic", {}) or {}).get("brier") if chal else None
    res.tier_a_disabled_by_monitor = monitor_tier_a(session, timeframe, backtest_brier)
    allow_a = res.gate.tier_a_allowed and not res.tier_a_disabled_by_monitor

    # 2. final model on every label already resolved at the decision date; the barrier pair is
    #    chosen the same way as in each walk-forward window (ADR 0002 section 4)
    window = ds.filter(pl.col("in_universe") & (pl.col("date") < as_of))

    def train_for(combo: Combo) -> pl.DataFrame:
        lab = with_labels(window, label_sets[combo])
        return lab.filter(pl.col("trainable") & (pl.col("exit_date") < as_of))

    model = LightGBMStrategy(rules, c, timeframe=timeframe, allow_tier_a=allow_a)
    model.fit_grid(list(label_sets), train_for)
    train = train_for(model.barrier)
    snapshot_id = write_snapshot(ds, store, bucket, f"snapshots/{timeframe}/{as_of}")
    res.data_snapshot_id = f"{timeframe}-{as_of:%Y%m%d}-{snapshot_id}"
    if not model.info.get("usable"):
        res.message = NO_DATA
        _record_run(session, r=res)
        return res

    artifact = model.to_bytes()
    res.model_version = f"lgbm-{timeframe.lower()}-{as_of:%Y%m%d}-{_sha(artifact)[:8]}"
    uri = f"models/{timeframe}/{res.model_version}.json"
    store.put(bucket, uri, artifact, "application/json")

    # 3. today's candidates
    today = ds.filter((pl.col("date") == as_of) & pl.col("in_universe"))
    pred = model.predict(today)
    res.defensive_mode = bool(pred["defensive"].any()) if "defensive" in pred.columns else False
    cand = pred.filter(pl.col("signal"))
    res.n_candidates = cand.height
    res.scores_uri = write_scores(
        store, bucket, timeframe, as_of, today, pred, model, str(res.model_version)
    )

    sel = pl.DataFrame()
    if cand.height:
        extra = today.select(
            "instrument_id", "sector_code", "median_value_20", "atr_14", "atr_14_pct"
        )
        close = prices.filter(pl.col("date") == as_of).select("instrument_id", "close")
        cand = cand.join(extra, on="instrument_id", how="left").join(
            close, on="instrument_id", how="left"
        )
        sel, _dropped = select_portfolio(
            cand, ds.select("instrument_id", "date", "ret_1"), capital=capital, cfg=c
        )
    res.n_recommended = sel.height
    if not sel.height:
        res.message = NO_CANDIDATE if not cand.height else NO_PORTFOLIO
        _record_run(session, r=res)
        _write_model_run(session, res, run, model, uri, fs.key, train, c)
        return res

    # 4. explanations, price levels, persistence
    chosen = today.join(sel.select("instrument_id"), on="instrument_id", how="semi")
    x = _matrix(chosen, model.features)
    order = chosen["instrument_id"]
    assert model.booster is not None
    reasons = top_reasons(model.booster, x, model.features, 5)
    by_inst = dict(zip(order.to_list(), reasons, strict=True))

    tf = c.labeling.timeframes[timeframe]
    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for r in sel.iter_rows(named=True):  # a handful of recommended rows
        p0 = float(r["close"])
        move = float(r["atr_14"]) * math.sqrt(tf.atr_scale_days)
        rows.append(
            {
                "date": as_of,
                "timeframe": timeframe,
                "instrument_id": int(r["instrument_id"]),
                "entry_price": p0,
                "entry_rule": ENTRY_RULE,
                "take_profit": p0 + model.barrier[0] * move,
                "stop_loss": p0 - model.barrier[1] * move,
                "horizon_days": tf.horizon_days,
                "p_win": float(r["p_win"]),
                "ev": float(r["ev"]),
                "rank": int(r["rank"]),
                "confidence_tier": str(r["tier"]),
                "position_pct": float(r["position_pct"]),
                "top_reasons": by_inst[int(r["instrument_id"])],
                "risks": _risks(r, bool(r["defensive"]), rules, not allow_a),
                "model_version": res.model_version,
                "data_snapshot_id": res.data_snapshot_id,
                "outcome": "pending",
                "created_at": now,
            }
        )
    session.execute(
        delete(Signal).where(
            Signal.date == as_of,
            Signal.timeframe == timeframe,
            Signal.model_version == res.model_version,
        )
    )
    session.add_all([Signal(**row) for row in rows])
    res.signals = pl.DataFrame(rows, strict=False) if rows else pl.DataFrame()
    res.message = f"{sel.height} توصیه برای {as_of.isoformat()}"
    _record_run(session, r=res)
    _write_model_run(session, res, run, model, uri, fs.key, train, c)
    session.flush()
    return res


SCORES_EXPLAINED = 30  # rows by EV that get feature contributions in the scores artifact
SCORE_COLUMNS = ("p_win", "ev", "p_min", "p_breakeven", "tier", "signal")


def write_scores(
    store: ObjectStore,
    bucket: str,
    timeframe: str,
    as_of: date,
    today: pl.DataFrame,
    pred: pl.DataFrame,
    model: LightGBMStrategy,
    model_version: str,
) -> str | None:
    """Store the model's output for every symbol in today's universe, published or not, so the
    screener can show it. The top rows by EV also carry their feature contributions."""
    if pred.is_empty() or model.booster is None:
        return None
    cols = [c for c in SCORE_COLUMNS if c in pred.columns]
    tab = pred.select("instrument_id", *cols)
    top = tab.filter(pl.col("ev").is_finite()).sort("ev", descending=True).head(SCORES_EXPLAINED)
    ids = top["instrument_id"].to_list()
    explained: dict[int, list[dict[str, Any]]] = {}
    if ids:
        rows = today.filter(pl.col("instrument_id").is_in(ids))
        reasons = top_reasons(model.booster, _matrix(rows, model.features), model.features, 5)
        explained = dict(zip(rows["instrument_id"].to_list(), reasons, strict=True))
    doc = {
        "timeframe": timeframe,
        "date": as_of.isoformat(),
        "model_version": model_version,
        "rows": [
            {**_json_safe(r), "reasons": explained.get(int(r["instrument_id"]))}
            for r in tab.iter_rows(named=True)
        ],
    }
    uri = f"scores/{timeframe}/{as_of:%Y%m%d}.json"
    store.put(bucket, uri, json.dumps(doc, allow_nan=False).encode(), "application/json")
    return uri


def _write_model_run(
    session: Session,
    res: PublishResult,
    run: BacktestRun,
    model: LightGBMStrategy,
    uri: str,
    fs_key: str,
    train: pl.DataFrame,
    cfg: EngineConfig,
) -> None:
    metrics: dict[str, Any] = {
        "model": {k: v for k, v in model.info.items() if k != "usable"},
        "gate": res.gate.to_dict() if res.gate else None,
        "tier_a_disabled_by_monitor": res.tier_a_disabled_by_monitor,
        "backtest": {
            n: {k: v for k, v in s.summary.items() if k != "by_regime"}
            for n, s in run.strategies.items()
        },
        "benchmarks": run.benchmarks,
        "warnings": run.warnings,
        "scores_uri": res.scores_uri,
    }
    window = {
        "start": str(train["date"].min()),
        "end": str(train["date"].max()),
        "rows": train.height,
        "retrain_every_days": cfg.validation.retrain_every_days,
    }
    session.execute(
        delete(ModelRun).where(
            ModelRun.timeframe == res.timeframe, ModelRun.version == res.model_version
        )
    )
    session.add(
        ModelRun(
            timeframe=res.timeframe,
            version=str(res.model_version),
            train_window=window,
            metrics=_json_safe(metrics),
            artifact_uri=uri,
            feature_set_version=fs_key,
            created_at=datetime.now(UTC),
        )
    )


def _json_safe(obj: Any) -> Any:
    """Replace NaN/inf (not valid JSON) with None, recursively."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
