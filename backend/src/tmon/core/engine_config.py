"""Typed loader for ``config/engine.yaml`` (every engine threshold lives there)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

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


class GridCfg(_Frozen):
    """Barrier multiples tried per walk-forward window (ADR 0002 section 4)."""

    k_tp: list[float] = Field(min_length=1)
    k_sl: list[float] = Field(min_length=1)


class LabelingCfg(_Frozen):
    # default pair: used when no grid selection runs (single-label datasets, live fallback)
    k_tp: float
    k_sl: float
    atr_period: int
    timeframes: dict[str, TimeframeCfg]
    grid: dict[str, GridCfg]
    # per timeframe: "barrier" (TP before SL) or "relative" (beat the same-day median,
    # OPEN_QUESTIONS 67); a timeframe left out uses "barrier"
    target: dict[str, Literal["barrier", "relative"]] = Field(default_factory=dict)


class CostsCfg(_Frozen):
    slippage_fraction: float = Field(ge=0)


class TierACfg(_Frozen):
    # offsets above the break-even probability (ADR 0002 section 3)
    p_win_margin: float
    recent_bucket_accuracy_margin: float


class TierBCfg(_Frozen):
    p_win_margin: float


class TiersCfg(_Frozen):
    A: TierACfg
    B: TierBCfg


class ThresholdsCfg(_Frozen):
    """``p_min = max(p_breakeven + margin, p_floor)`` and ``EV_net >= ev_min_abs`` (ADR 0002
    section 3). ``p_breakeven = (L + c) / (W + L)`` is computed per probability bucket."""

    margin: float
    p_floor: float
    ev_min_abs: float
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


class RegimePlanCfg(_Frozen):
    """Market-state plan and its forward (paper) test (docs/reports/regime-switch-2026-11.md,
    docs/reports/timing-and-codal-2026-11.md)."""

    breadth_low: float = Field(gt=0, lt=1)  # at or below: falling
    breadth_high: float = Field(gt=0, lt=1)  # above: rising
    confirm_days: int = Field(ge=1)  # a new state counts after this many days in a row
    renew_days: int = Field(ge=1)  # names are renewed after this many trading days
    top: int = Field(ge=1)
    exit_ma: int = Field(ge=2)  # sell a held name closing under its mean of this many days
    start: date  # first decision of the forward test (the plan was frozen on this date)
    capital: float = Field(gt=0)  # toman, for the paper account


class ModelCfg(_Frozen):
    calibration_fraction: float = Field(gt=0, lt=0.5)
    early_stopping_fraction: float = Field(gt=0, lt=0.5)
    recent_days: int = Field(ge=1)
    min_recent_samples: int = Field(ge=1)
    tier_a_min_trades: int = Field(ge=1)
    # fewer signals than this on the inner validation slice => the barrier pair has no score
    grid_min_signals: int = Field(ge=1)


class BacktestCfg(_Frozen):
    max_new_positions_per_day: int = Field(ge=1)
    max_gross_exposure: float = Field(gt=0)
    initial_capital: float = Field(gt=0)


class BenchmarksCfg(_Frozen):
    fixed_income_annual_rate: float | None = None
    # name -> TSETMC index code (ADR 0002 section 6)
    indices: dict[str, str] = {}
    # Risk-free rate from treasury bills (ADR 0002 section 6)
    treasury_bill_face_value: float | None = None
    rf_target_days: int = 365
    rf_min_days_to_maturity: int = 30


class ExposureCfg(_Frozen):
    trend_window_days: int = Field(ge=2)
    abs_mom_days: int = Field(ge=2)
    vol_window_days: int = Field(ge=2)
    target_vol_annual: float | None = Field(default=None, gt=0)
    stress_window_days: int = Field(ge=1)
    max_exposure: float = Field(gt=0, le=1)
    sensitivity_target_vols: list[float] = []


class PortfolioCfg(_Frozen):
    n_names: int = Field(ge=1)
    n_tranches: int = Field(ge=1)
    review_every_days: int = Field(ge=1)
    buy_top_frac: float = Field(gt=0, le=1)
    hold_top_frac: float = Field(gt=0, le=1)
    entry_delay_days: int = Field(ge=1)
    warmup_days: int = Field(ge=0)
    min_cross_section: int = Field(ge=1)


class GatesCfg(_Frozen):
    min_year_win_share: float
    min_days_per_year: int
    max_monthly_one_way_turnover: float
    min_monthly_excess_t: float
    robust_names_delta: int
    robust_entry_delay_days: int
    robust_cost_multiplier: float
    pbo_splits: int
    survivorship_resolved: bool


class InvestedCfg(_Frozen):
    """ADR 0004 section 4: the seven pre-registered configurations S0-S6 (S2 is ``v2.portfolio``)
    and the rules that judge them. None of these numbers is tuned on the data."""

    core_review_days: int = Field(ge=1)  # S0: membership and weights reviewed this often
    warmup_days: int = Field(ge=0)  # statistics start this many days after the book starts
    s1_drop_bottom_frac: float = Field(gt=0, lt=1)  # S1: names in this bottom share of scores
    slow_n_names: int = Field(ge=1)  # S3 ("slow book")
    slow_n_tranches: int = Field(ge=1)
    slow_review_every_days: int = Field(ge=1)
    slow_buy_top_frac: float = Field(gt=0, le=1)
    slow_hold_top_frac: float = Field(gt=0, le=1)
    min_phase_share: float = Field(gt=0, le=1)  # condition 3: share of start phases that beat S0
    cost_multiplier: float = Field(gt=0)  # condition 4
    profile_horizons: tuple[int, ...]  # decile profile, trading days
    profile_top_n: int = Field(ge=10)  # the liquid basket the profile is cut from
    grade_min_net_edge: float  # ADR section 6, grade "proven": net excess at least this ...
    grade_min_t: float  # ... and t at least this


class VerdictCfg(_Frozen):
    """ADR 0004 sections 5-7: the per-symbol verdict. Every number is read off the Phase 2 report
    (docs/reports/invested-book-2026-11-17.md, profile "within the basket"); a test ties them to
    ``docs/data/invested-study.json``. Change them only with a new report."""

    horizon_days: int = Field(ge=1)  # the horizon the zones are read at
    candidate_top_frac: float = Field(gt=0, lt=1)  # candidate zone = top share of the basket
    avoid_bottom_frac: float = Field(gt=0, lt=1)  # avoid zone = bottom share of the basket
    candidate_grade: Literal["proven", "probable", "unproven"]
    avoid_grade: Literal["proven", "probable", "unproven"]


class V2Cfg(_Frozen):
    exposure: ExposureCfg
    portfolio: PortfolioCfg
    gates: GatesCfg
    invested: InvestedCfg
    verdict: VerdictCfg


class AdaptCfg(_Frozen):
    window_dates: int = Field(ge=100)
    min_half_dates: int = Field(ge=20)
    min_t: float = Field(ge=0)
    switch_margin_t: float = Field(ge=0)
    history_keep: int = Field(ge=1)
    replay_every_dates: int = Field(ge=1)
    replay_refresh_days: int = Field(default=28, ge=1)
    stress_days: int = Field(default=120, ge=20)
    stress_drawdown: float = Field(default=0.2, gt=0, lt=1)
    candidates: tuple[str, ...]


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
    regime_plan: RegimePlanCfg
    backtest: BacktestCfg
    model: ModelCfg
    benchmarks: BenchmarksCfg
    v2: V2Cfg
    adapt: AdaptCfg
    # Timeframes trained and published by the daily cycle, in order (D1 first: it is required).
    publish_timeframes: tuple[str, ...] = ("D1",)

    @model_validator(mode="after")
    def _timeframes_known(self) -> EngineConfig:
        missing = {"D1", "W1", "M1"} - set(self.labeling.timeframes)
        if missing:
            raise ValueError(f"labeling.timeframes missing {sorted(missing)}")
        no_grid = set(self.labeling.timeframes) - set(self.labeling.grid)
        if no_grid:
            raise ValueError(f"labeling.grid missing {sorted(no_grid)}")
        unknown = set(self.publish_timeframes) - set(self.labeling.timeframes)
        if unknown:
            raise ValueError(f"publish_timeframes has unknown {sorted(unknown)}")
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
