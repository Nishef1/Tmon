"""Orchestration: features + labels -> walk-forward -> simulation -> metrics -> benchmarks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from tmon.backtest.dataset import build_dataset
from tmon.backtest.metrics import portfolio_metrics, probabilistic_summary, summarise
from tmon.backtest.simulate import SimResult, regime_frame, simulate
from tmon.backtest.walkforward import Fold, Strategy, run_walk_forward
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.engine.defensive import add_defensive_flag
from tmon.features.builder import build_features
from tmon.labeling.grid import Combo, grid_combos
from tmon.labeling.relative import apply_target
from tmon.labeling.triple_barrier import triple_barrier_labels

StrategyFactory = Callable[[], Strategy]


@dataclass
class StrategyRun:
    name: str
    predictions: pl.DataFrame
    sim: SimResult
    summary: dict[str, Any]


@dataclass
class BacktestRun:
    timeframe: str
    dataset: pl.DataFrame
    folds: list[Fold]
    train_sizes: list[int]
    strategies: dict[str, StrategyRun] = field(default_factory=dict)
    benchmarks: dict[str, dict[str, Any]] = field(default_factory=dict)
    benchmark_daily: dict[str, pl.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    # per strategy: barrier pair chosen in every fold and each pair's inner-validation score
    fold_infos: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def prepare_dataset(
    prices: pl.DataFrame,
    client_types: pl.DataFrame | None,
    rules: RuleBook,
    *,
    sectors: pl.DataFrame | None = None,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> pl.DataFrame:
    c = cfg or get_engine_config()
    feats = build_features(prices, client_types, rules, sectors=sectors, config=c)
    labels = apply_target(triple_barrier_labels(prices, rules, timeframe, c), timeframe, c)
    ds = build_dataset(feats, labels, c)
    if sectors is not None and "sector_code" not in ds.columns:
        ds = ds.join(sectors.select("instrument_id", "sector_code"), on="instrument_id", how="left")
    return add_defensive_flag(ds, c)


def prepare_label_sets(
    prices: pl.DataFrame,
    rules: RuleBook,
    *,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> dict[Combo, pl.DataFrame]:
    """One label frame per barrier pair of the grid (ADR 0002 section 4)."""
    from tmon.labeling.grid import label_sets

    return label_sets(prices, rules, timeframe, cfg)


def _index_returns(index_daily: pl.DataFrame, code: str, start: Any, end: Any) -> pl.DataFrame:
    """Daily close-to-close return of one index over ``[start, end]`` (``date``, ``ret``)."""
    one = index_daily.filter(pl.col("index_code") == code).sort("date")
    return (
        one.with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"))
        .filter(pl.col("ret").is_not_null() & (pl.col("date") >= start) & (pl.col("date") <= end))
        .select("date", "ret")
    )


def risk_free_daily(rf: pl.DataFrame, dates: pl.Series) -> pl.DataFrame:
    """Daily return of holding the one-year treasury bill, per trading day in ``dates``.

    ``rf`` holds ``date`` and ``value`` (annual effective yield, as a fraction). Each day uses the
    latest yield known on or before it; days before the first yield are left out (no invented
    rate). The per-day step is ``(1 + yield) ** (1 / trading_days_per_year) - 1``.
    """
    span = dates.to_list()
    years = (span[-1] - span[0]).days / 365.25 if len(span) > 1 else 0.0
    per_year = len(span) / years if years > 0 else 1.0
    day = pl.DataFrame({"date": dates}).sort("date")
    return (
        day.join_asof(rf.sort("date").select("date", "value"), on="date")
        .filter(pl.col("value").is_not_null())
        .select("date", ((1 + pl.col("value")) ** (1 / per_year) - 1).alias("ret"))
    )


def mean_risk_free(
    rf: pl.DataFrame | None, start: Any, end: Any, cfg: EngineConfig
) -> float | None:
    """Annual risk-free rate for the Sharpe ratio: the mean treasury-bill yield over the days of
    ``[start, end]`` that have one; the configured fallback rate; or ``None`` (Sharpe uses 0)."""
    if rf is not None and not rf.is_empty():
        v = rf.filter((pl.col("date") >= start) & (pl.col("date") <= end))["value"].drop_nulls()
        if v.len():
            return float(v.mean())  # type: ignore[arg-type]
    return cfg.benchmarks.fixed_income_annual_rate


def benchmark_series(
    ds: pl.DataFrame,
    start: Any,
    end: Any,
    cfg: EngineConfig,
    *,
    index_daily: pl.DataFrame | None = None,
    rf: pl.DataFrame | None = None,
) -> dict[str, pl.DataFrame]:
    """Daily return series for the comparison lines, restricted to ``[start, end]``.

    * ``tedpix`` / ``equal_weight_index``: the official TSETMC overall and equal-weight indices
      (``market_index_daily``; ADR 0002 section 6);
    * ``equal_weight_all`` / ``equal_weight_universe``: equal-weight mean daily return of every
      tradable instrument (``mkt_ret_ew``) / of the liquid universe the strategies draw from; no
      costs, rebalanced daily;
    * ``fixed_income``: holding the treasury bill nearest to one year (``macro_series``
      ``rf_1y_ytm``), only on days where that yield exists.
    """
    # membership must be known *before* the return it earns: use yesterday's universe flag, or
    # the benchmark would skip the limit-down days that excluded stocks from today's universe
    span = ds.sort("instrument_id", "date").with_columns(
        pl.col("in_universe").shift(1).over("instrument_id").fill_null(False).alias("_member_prev")
    )
    span = span.filter((pl.col("date") >= start) & (pl.col("date") <= end))
    out: dict[str, pl.DataFrame] = {}
    if index_daily is not None and not index_daily.is_empty():
        names = {"tedpix": "tedpix", "equal_weight": "equal_weight_index"}
        for key, code in cfg.benchmarks.indices.items():
            r = _index_returns(index_daily, code, start, end)
            if not r.is_empty():
                out[names.get(key, key)] = r
    out["equal_weight_all"] = (
        span.group_by("date")
        .agg(pl.col("mkt_ret_ew").first().fill_null(0.0).alias("ret"))
        .sort("date")
    )
    out["equal_weight_universe"] = (
        span.filter(pl.col("_member_prev"))
        .group_by("date")
        .agg(pl.col("ret_1").mean().fill_null(0.0).alias("ret"))
        .sort("date")
    )
    dates = out["equal_weight_all"]["date"]
    if rf is not None and not rf.is_empty():
        fi = risk_free_daily(rf, dates)
        if not fi.is_empty():
            out["fixed_income"] = fi
    elif cfg.benchmarks.fixed_income_annual_rate is not None:
        flat = pl.DataFrame(
            {"date": dates, "value": [cfg.benchmarks.fixed_income_annual_rate] * dates.len()}
        )
        out["fixed_income"] = risk_free_daily(flat, dates)
    return out


def run_backtest(
    ds: pl.DataFrame,
    rules: RuleBook,
    strategies: Mapping[str, StrategyFactory],
    *,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
    label_sets: Mapping[Combo, pl.DataFrame] | None = None,
    index_daily: pl.DataFrame | None = None,
    rf: pl.DataFrame | None = None,
) -> BacktestRun:
    """Walk-forward every strategy, simulate it and compare it with the benchmarks.

    ``label_sets`` switches on the nested barrier selection (one label frame per grid pair);
    ``index_daily`` (``index_code``, ``date``, ``close``) and ``rf`` (``date``, ``value``) supply the
    official indices and the treasury-bill yield. Without them the report says so.
    """
    c = cfg or get_engine_config()
    reg = regime_frame(ds["date"].unique().sort().to_list(), c)
    run: BacktestRun | None = None
    rf_annual: float | None = None
    for name, factory in strategies.items():
        wf = run_walk_forward(ds, factory, timeframe=timeframe, cfg=c, label_sets=label_sets)
        if run is None:
            run = BacktestRun(timeframe, ds, wf.folds, wf.train_sizes)
        if wf.fold_infos:
            run.fold_infos[name] = wf.fold_infos
        if wf.predictions.is_empty():
            run.warnings.append(f"{name}: no test folds (history shorter than min_train_days)")
            continue
        sim = simulate(wf.predictions, ds, rules, timeframe, c)
        rf_annual = mean_risk_free(
            rf, wf.predictions["date"].min(), wf.predictions["date"].max(), c
        )
        summary = summarise(sim.trades, sim.daily, risk_free_annual=rf_annual)
        summary["counts"] = sim.counts
        if "p_win" in wf.predictions.columns:
            if "y" in wf.predictions.columns:  # labels of the per-fold chosen pair
                lab = wf.predictions
            else:
                lab = wf.predictions.join(
                    ds.select("instrument_id", "date", "y", "valid"), on=["instrument_id", "date"]
                )
            lab = lab.filter(
                pl.col("valid") & pl.col("y").is_not_null() & pl.col("p_win").is_not_null()
            )
            summary["probabilistic"] = probabilistic_summary(
                lab["p_win"].to_numpy().astype(float),
                lab["y"].cast(pl.Float64).to_numpy(),
                c.calibration.n_buckets,
            )
        run.strategies[name] = StrategyRun(name, wf.predictions, sim, summary)
    if run is None:
        raise ValueError("no strategies given")

    if run.strategies:
        first = next(iter(run.strategies.values())).sim.daily
        start, end = first["date"].min(), first["date"].max()
        run.benchmark_daily = benchmark_series(ds, start, end, c, index_daily=index_daily, rf=rf)
        rf_annual = mean_risk_free(rf, start, end, c)
        for name, df in run.benchmark_daily.items():
            df = df.join(reg, on="date", how="left")
            run.benchmark_daily[name] = df
            run.benchmarks[name] = {"portfolio": portfolio_metrics(df, risk_free_annual=rf_annual)}
    run.warnings.extend(data_warnings(rules, c, run, rf_annual=rf_annual))
    run.meta = {
        "grid_combos": [list(x) for x in grid_combos(timeframe, c)] if label_sets else [],
        "risk_free_annual": rf_annual,
        "timeframe": timeframe,
        "folds": len(run.folds),
        "instruments": int(ds["instrument_id"].n_unique()),
        "decision_rows": ds.height,
        "slippage_fraction": c.costs.slippage_fraction,
        "retrain_every_days": c.validation.retrain_every_days,
        "min_train_days": c.validation.min_train_days,
    }
    return run


def data_warnings(
    rules: RuleBook, cfg: EngineConfig, run: BacktestRun, *, rf_annual: float | None = None
) -> list[str]:
    """Caveats that must travel with every report."""
    w: list[str] = []
    used = [
        r
        for r in rules.unverified()
        if r.rule in {"commission_buy", "commission_sell", "sell_tax", "price_limit"}
    ]
    if used:
        names = {
            "commission_buy": "کارمزد خرید",
            "commission_sell": "کارمزد فروش",
            "sell_tax": "مالیات فروش",
            "price_limit": "حد نوسان قیمت",
        }
        listed = "، ".join(names[r.rule] for r in used)
        w.append(
            f"این قوانین هنوز با منبع رسمی تطبیق داده نشده‌اند: {listed}. "
            "هزینه‌ها و حدود قیمت در محاسبه تقریبی‌اند."
        )
    if rf_annual is None:
        w.append(
            "نرخ اخزا در دسترس نیست؛ مقایسه با درآمد ثابت انجام نشد و نسبت شارپ با نرخ بدون ریسک صفر محاسبه شده است."
        )
    if "tedpix" not in run.benchmarks:
        w.append("شاخص رسمی در دسترس نیست؛ شاخص هم‌وزن از قیمت‌های خود نمادها ساخته شده است.")
    for name, sr in run.strategies.items():
        years = sr.summary["portfolio"].get("years")
        if years is not None and years < 1.0:
            w.append(f"{name}: دورهٔ آزمون کمتر از یک سال است؛ نتایج از نظر آماری ضعیف‌اند.")
    return w
