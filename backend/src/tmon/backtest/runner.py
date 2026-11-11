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
    labels = triple_barrier_labels(prices, rules, timeframe, c)
    ds = build_dataset(feats, labels, c)
    if sectors is not None and "sector_code" not in ds.columns:
        ds = ds.join(sectors.select("instrument_id", "sector_code"), on="instrument_id", how="left")
    return add_defensive_flag(ds, c)


def benchmark_series(
    ds: pl.DataFrame, start: Any, end: Any, cfg: EngineConfig
) -> dict[str, pl.DataFrame]:
    """Daily return series for the comparison lines, restricted to ``[start, end]``.

    * ``equal_weight_all``: equal-weight mean daily return of every tradable instrument
      (``mkt_ret_ew``), a proxy for an equal-weight index; no costs, rebalanced daily;
    * ``equal_weight_universe``: same, over the liquid universe the strategies draw from;
    * ``fixed_income``: constant growth at ``benchmarks.fixed_income_annual_rate`` (only when
      configured).
    """
    # membership must be known *before* the return it earns: use yesterday's universe flag, or
    # the benchmark would skip the limit-down days that excluded stocks from today's universe
    span = ds.sort("instrument_id", "date").with_columns(
        pl.col("in_universe").shift(1).over("instrument_id").fill_null(False).alias("_member_prev")
    )
    span = span.filter((pl.col("date") >= start) & (pl.col("date") <= end))
    out: dict[str, pl.DataFrame] = {
        "equal_weight_all": span.group_by("date")
        .agg(pl.col("mkt_ret_ew").first().fill_null(0.0).alias("ret"))
        .sort("date"),
        "equal_weight_universe": span.filter(pl.col("_member_prev"))
        .group_by("date")
        .agg(pl.col("ret_1").mean().fill_null(0.0).alias("ret"))
        .sort("date"),
    }
    rate = cfg.benchmarks.fixed_income_annual_rate
    if rate is not None:
        dates = out["equal_weight_all"]["date"]
        years = (dates.to_list()[-1] - dates.to_list()[0]).days / 365.25
        per_year = dates.len() / years if years > 0 else 1.0
        out["fixed_income"] = pl.DataFrame({"date": dates}).with_columns(
            pl.lit((1 + rate) ** (1 / per_year) - 1).alias("ret")
        )
    return out


def run_backtest(
    ds: pl.DataFrame,
    rules: RuleBook,
    strategies: Mapping[str, StrategyFactory],
    *,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> BacktestRun:
    c = cfg or get_engine_config()
    reg = regime_frame(ds["date"].unique().sort().to_list(), c)
    run: BacktestRun | None = None
    for name, factory in strategies.items():
        wf = run_walk_forward(ds, factory, timeframe=timeframe, cfg=c)
        if run is None:
            run = BacktestRun(timeframe, ds, wf.folds, wf.train_sizes)
        if wf.predictions.is_empty():
            run.warnings.append(f"{name}: no test folds (history shorter than min_train_days)")
            continue
        sim = simulate(wf.predictions, ds, rules, timeframe, c)
        summary = summarise(
            sim.trades,
            sim.daily,
            risk_free_annual=c.benchmarks.fixed_income_annual_rate,
        )
        summary["counts"] = sim.counts
        if "p_win" in wf.predictions.columns:
            lab = wf.predictions.join(
                ds.select("instrument_id", "date", "y", "valid"), on=["instrument_id", "date"]
            ).filter(pl.col("valid") & pl.col("y").is_not_null() & pl.col("p_win").is_not_null())
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
        run.benchmark_daily = benchmark_series(ds, start, end, c)
        for name, df in run.benchmark_daily.items():
            df = df.join(reg, on="date", how="left")
            run.benchmark_daily[name] = df
            run.benchmarks[name] = {
                "portfolio": portfolio_metrics(
                    df, risk_free_annual=c.benchmarks.fixed_income_annual_rate
                )
            }
    run.warnings.extend(data_warnings(rules, c, run))
    run.meta = {
        "timeframe": timeframe,
        "folds": len(run.folds),
        "instruments": int(ds["instrument_id"].n_unique()),
        "decision_rows": ds.height,
        "slippage_fraction": c.costs.slippage_fraction,
        "retrain_every_days": c.validation.retrain_every_days,
        "min_train_days": c.validation.min_train_days,
    }
    return run


def data_warnings(rules: RuleBook, cfg: EngineConfig, run: BacktestRun) -> list[str]:
    """Caveats that must travel with every report."""
    w: list[str] = []
    used = [
        r
        for r in rules.unverified()
        if r.rule in {"commission_buy", "commission_sell", "sell_tax", "price_limit"}
    ]
    for r in used:
        w.append(f"قانون «{r.rule}» تأییدنشده است (verified=false)؛ هزینه‌ها و حدود قیمت تقریبی‌اند.")
    if cfg.benchmarks.fixed_income_annual_rate is None:
        w.append(
            "نرخ صندوق درآمد ثابت/اخزا در دسترس نیست؛ مقایسه با آن انجام نشد و نسبت شارپ با نرخ بدون ریسک صفر محاسبه شده است."
        )
    w.append("شاخص رسمی در دسترس نیست؛ شاخص هم‌وزن از قیمت‌های خود نمادها ساخته شده است.")
    for name, sr in run.strategies.items():
        years = sr.summary["portfolio"].get("years")
        if years is not None and years < 1.0:
            w.append(f"{name}: دورهٔ آزمون کمتر از یک سال است؛ نتایج از نظر آماری ضعیف‌اند.")
    return w
