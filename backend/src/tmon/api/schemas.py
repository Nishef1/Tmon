"""API response models. Dates are ISO strings; the UI converts to Jalali for display."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Timeframe = Literal["D1", "W1", "M1"]
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("D1", "W1", "M1")

DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست"


class ApiModel(BaseModel):
    """Base of every response model.

    Fields with defaults are always serialised, so the OpenAPI schema marks them required;
    the frontend's generated types then have no spurious ``| undefined``.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class InstrumentOut(ApiModel):
    id: int
    symbol: str
    name: str | None = None
    sector_code: str | None = None
    instrument_type: str | None = None


class Reason(ApiModel):
    feature: str
    value: float | None = None
    contribution: float


class SignalOut(ApiModel):
    id: int
    date: dt.date
    timeframe: str
    rank: int
    instrument: InstrumentOut
    entry_price: float
    entry_rule: str
    take_profit: float
    stop_loss: float
    horizon_days: int
    p_win: float
    ev: float
    confidence_tier: str
    position_pct: float
    top_reasons: list[Reason]
    risks: list[str]
    model_version: str
    data_snapshot_id: str
    outcome: str = "pending"
    realized_return: float | None = None
    outcome_date: dt.date | None = None


class RunOut(ApiModel):
    date: dt.date
    model_version: str
    data_snapshot_id: str
    n_candidates: int
    n_recommended: int
    defensive_mode: bool
    message: str | None = None
    created_at: dt.datetime


class GateOut(ApiModel):
    tier_a_allowed: bool
    reasons: list[str]


class RecommendationsOut(ApiModel):
    timeframe: str
    supported: bool
    date: dt.date | None
    available_dates: list[dt.date]
    no_recommendation: bool
    message: str
    disclaimer: str = DISCLAIMER
    run: RunOut | None = None
    gate: GateOut | None = None
    signals: list[SignalOut]


class Candle(ApiModel):
    date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class FeatureValue(ApiModel):
    feature: str
    value: float | None


class CorporateEventOut(ApiModel):
    type: str
    stage: str | None = None
    title: str | None = None
    announced_at: dt.date | None = None
    url: str | None = None  # the Codal letter


class InstrumentDetail(ApiModel):
    instrument: InstrumentOut
    adjusted: bool
    candles: list[Candle]
    features_date: dt.date | None
    features: list[FeatureValue]
    signals: list[SignalOut]
    events: list[CorporateEventOut] = []
    disclaimer: str = DISCLAIMER


class AgmInputOut(ApiModel):
    name: str
    value: float
    source: str  # where the value came from: "user", a table and date, or "default 0"


class AgmDecisionOut(ApiModel):
    instrument_id: int
    decision: Literal["hold", "sell"]
    pv_dividend: float
    net_hold: float
    net_sell: float
    inputs: list[AgmInputOut]
    disclaimer: str = DISCLAIMER


class HistorySummary(ApiModel):
    total: int
    resolved: int
    pending: int
    take_profit: int
    stop_loss: int
    expired: int
    mean_realized_return: float | None  # gross, before costs, over resolved signals


class HistoryOut(ApiModel):
    timeframe: str
    items: list[SignalOut]
    total: int
    limit: int
    offset: int
    summary: HistorySummary
    disclaimer: str = DISCLAIMER


class CalibrationBucket(ApiModel):
    bucket: str
    n: int
    mean_p: float | None
    hit_rate: float | None


class CalibrationBlock(ApiModel):
    n: int
    base_rate: float | None = None
    auc: float | None = None
    brier: float | None = None
    brier_base_rate: float | None = None
    brier_skill: float | None = None
    buckets: list[CalibrationBucket] = []


class CalibrationOut(ApiModel):
    timeframe: str
    supported: bool
    model_version: str | None
    trained_through: str | None
    backtest: CalibrationBlock | None
    live: CalibrationBlock
    gate: GateOut | None
    warnings: list[str]
    extra: dict[str, Any] = {}
    disclaimer: str = DISCLAIMER


class BookLevelOut(ApiModel):
    row: int
    bid_price: float
    bid_volume: float
    bid_count: int
    ask_price: float
    ask_volume: float
    ask_count: int


class LiveOut(ApiModel):
    """Latest stored intraday snapshot and order book of one instrument (what the poller last
    wrote, not a direct pass-through of the exchange)."""

    instrument_id: int
    available: bool
    as_of: dt.datetime | None = None
    age_seconds: int | None = None
    stale: bool = True
    last_price: float | None = None
    cum_volume: float | None = None
    reference_price: float | None = None  # previous trading day's official close
    change_pct: float | None = None
    book_as_of: dt.datetime | None = None
    book: list[BookLevelOut] = []
    message: str | None = None
    disclaimer: str = DISCLAIMER


class InflationReleaseOut(ApiModel):
    ref_period: dt.date
    release_date: dt.date
    value: float
    source_url: str | None = None


class InflationOut(ApiModel):
    source: str
    value: float
    method: str
    releases: list[InflationReleaseOut]


class CompareRow(ApiModel):
    series: str
    label: str
    source: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    start_value: float | None = None
    end_value: float | None = None
    nominal_return: float | None = None
    real_return: float | None = None
    beats_inflation: bool | None = None
    note: str | None = None


class CompareOut(ApiModel):
    as_of: dt.date | None = None
    months: int
    inflation_source: str
    inflation: InflationOut | None = None
    monthly_inflation: InflationOut | None = None
    annualised_monthly: float | None = None  # docs/07 threshold
    rows: list[CompareRow]
    disclaimer: str = DISCLAIMER


class FundOut(ApiModel):
    reg_no: str
    name: str | None = None
    symbol: str | None = None
    instrument_id: int | None = None
    fund_type: int | None = None
    listed: bool
    nav_date: dt.date
    cancel_nav: float | None = None
    issue_nav: float | None = None
    net_asset: float | None = None
    price: float | None = None
    bubble: float | None = None
    bubble_note: str | None = None


class FundsOut(ApiModel):
    nav_date: dt.date | None = None
    funds: list[FundOut]
    disclaimer: str = DISCLAIMER


class LiveDayOut(ApiModel):
    date: dt.date
    n: int
    hits: int
    mean_p: float
    brier: float


class LiveAccuracyOut(ApiModel):
    timeframe: str
    as_of: dt.date | None = None
    resolved: int
    pending: int
    hit_rate: float | None = None
    mean_p: float | None = None
    backtest_brier: float | None = None
    recent_days: int
    recent_n: int
    recent_brier: float | None = None
    degradation_limit: float
    kill_switch_active: bool
    defensive_mode: bool | None = None
    days: list[LiveDayOut]
    disclaimer: str = DISCLAIMER


class ScreenerRow(ApiModel):
    """One symbol on the latest trading day: market data, a few features and, when a scores
    artifact exists, the model's raw output. ``signal`` true means it passed every threshold."""

    instrument: InstrumentOut
    close: float | None = None
    change_pct: float | None = None
    value: float | None = None
    trades: int | None = None
    rsi_14: float | None = None
    rel_volume: float | None = None
    atr_14_pct: float | None = None
    ind_buy_power: float | None = None
    ind_net_flow_ratio: float | None = None
    p_win: float | None = None
    ev: float | None = None
    p_min: float | None = None
    signal: bool | None = None
    reasons: list[Reason] | None = None


class ScreenerOut(ApiModel):
    timeframe: str
    prices_date: dt.date | None = None
    scores_date: dt.date | None = None
    model_version: str | None = None
    tier_a_allowed: bool | None = None
    gate_reasons: list[str] = []
    total: int
    rows: list[ScreenerRow]
