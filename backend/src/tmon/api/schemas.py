"""API response models. Dates are ISO strings; the UI converts to Jalali for display."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Timeframe = Literal["D1", "W1", "M1"]
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("D1",)  # Phase 1 only trains the D1 model

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


class InstrumentDetail(ApiModel):
    instrument: InstrumentOut
    adjusted: bool
    candles: list[Candle]
    features_date: dt.date | None
    features: list[FeatureValue]
    signals: list[SignalOut]
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
