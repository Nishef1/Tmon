"""Typed loader for ``config/engine.yaml`` (every engine threshold lives there)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tmon.core.config import get_settings


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UniverseCfg(_Frozen):
    min_median_value_20d: float
    min_history_days: int
    exclude_queue_states: list[str]


class TimeframeCfg(_Frozen):
    horizon_days: int
    atr_scale_days: int


class LabelingCfg(_Frozen):
    k_tp: float
    k_sl: float
    atr_period: int
    timeframes: dict[str, TimeframeCfg]


class CostsCfg(_Frozen):
    slippage_fraction: float = Field(ge=0)


class TierACfg(_Frozen):
    p_win_min: float
    recent_bucket_accuracy_min: float


class TierBCfg(_Frozen):
    p_win_min: float


class TiersCfg(_Frozen):
    A: TierACfg
    B: TierBCfg


class ThresholdsCfg(_Frozen):
    p_min: dict[str, float]
    ev_min_cost_multiple: float
    min_bucket_samples: int
    tiers: TiersCfg


class SizingCfg(_Frozen):
    kelly_fraction: float
    max_position_pct: float
    risk_per_trade: float
    sector_cap_pct: float
    liquidity_cap_of_median_value: float
    correlation_window_days: int
    correlation_max: float


class BaselineD1Cfg(_Frozen):
    min_ind_buy_power: float
    min_rel_volume: float
    rsi_min: float
    rsi_max: float


class RegimeCfg(_Frozen):
    name: str
    start: date | None = None
    end: date | None = None


class ValidationCfg(_Frozen):
    retrain_every_days: int
    min_train_days: int
    embargo_equals_horizon: bool
    regimes: list[RegimeCfg]


class LightGBMCfg(_Frozen):
    params: dict[str, bool | int | float | str]
    num_boost_round: int
    early_stopping_rounds: int


class CalibrationCfg(_Frozen):
    method: str
    n_buckets: int


class DefensiveCfg(_Frozen):
    enabled: bool
    p_min_bump: float
    breadth_floor: float
    market_net_flow_negative_days: int


class ModelCfg(_Frozen):
    calibration_fraction: float = Field(gt=0, lt=0.5)
    early_stopping_fraction: float = Field(gt=0, lt=0.5)
    recent_days: int = Field(ge=1)
    min_recent_samples: int = Field(ge=1)
    tier_a_min_trades: int = Field(ge=1)


class BacktestCfg(_Frozen):
    max_new_positions_per_day: int = Field(ge=1)
    max_gross_exposure: float = Field(gt=0)
    initial_capital: float = Field(gt=0)


class BenchmarksCfg(_Frozen):
    fixed_income_annual_rate: float | None = None


class EngineConfig(_Frozen):
    universe: UniverseCfg
    labeling: LabelingCfg
    costs: CostsCfg
    thresholds: ThresholdsCfg
    sizing: SizingCfg
    baseline_d1: BaselineD1Cfg
    validation: ValidationCfg
    lightgbm: LightGBMCfg
    calibration: CalibrationCfg
    defensive_mode: DefensiveCfg
    backtest: BacktestCfg
    model: ModelCfg
    benchmarks: BenchmarksCfg

    @model_validator(mode="after")
    def _timeframes_known(self) -> EngineConfig:
        missing = {"D1", "W1", "M1"} - set(self.labeling.timeframes)
        if missing:
            raise ValueError(f"labeling.timeframes missing {sorted(missing)}")
        return self

    def regime_of(self, d: date) -> str:
        for r in self.validation.regimes:
            if (r.start is None or d >= r.start) and (r.end is None or d <= r.end):
                return r.name
        return "unknown"


def load_engine_config(path: Path | None = None) -> EngineConfig:
    p = path or get_settings().engine_config_path
    with p.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return EngineConfig.model_validate(raw)


@lru_cache
def get_engine_config() -> EngineConfig:
    return load_engine_config()
