"""SQLAlchemy 2 models (docs/11-architecture-and-data-model.md).

Time-series tables are turned into TimescaleDB hypertables by the Alembic
migration; the models themselves stay portable so unit tests can run on SQLite.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")
Rial = Numeric(24, 4)


class Base(DeclarativeBase):
    pass


class Provenance:
    """Mixin: every ingested record carries its origin (docs/02, crawler rule 3)."""

    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ins_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    symbol_fa: Mapped[str] = mapped_column(String(64), index=True)
    name_fa: Mapped[str | None] = mapped_column(String(256))
    isin: Mapped[str | None] = mapped_column(String(16), index=True)
    market: Mapped[str] = mapped_column(String(16), default="IR")
    board: Mapped[str | None] = mapped_column(String(64))
    instrument_type: Mapped[str] = mapped_column(String(32), default="stock")
    sector_code: Mapped[str | None] = mapped_column(String(16), index=True)
    tags: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    listed_at: Mapped[dt.date | None] = mapped_column(Date)
    delisted_at: Mapped[dt.date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class MarketRule(Base):
    __tablename__ = "market_rules"
    __table_args__ = (Index("ix_market_rules_lookup", "market", "rule", "valid_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16))
    rule: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(JsonType)
    valid_from: Mapped[dt.date] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    market: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean)
    halt_reason: Mapped[str | None] = mapped_column(String(64))


class PriceDaily(Base, Provenance):
    """Raw (unadjusted) daily bar. TSETMC naming: ``close`` is the official final
    price (پایانی), ``last`` the last trade price (آخرین)."""

    __tablename__ = "prices_daily"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Rial)
    high: Mapped[float | None] = mapped_column(Rial)
    low: Mapped[float | None] = mapped_column(Rial)
    last: Mapped[float | None] = mapped_column(Rial)
    close: Mapped[float | None] = mapped_column(Rial)
    prev_close: Mapped[float | None] = mapped_column(Rial)
    volume: Mapped[float | None] = mapped_column(Rial)
    value: Mapped[float | None] = mapped_column(Rial)
    trades: Mapped[int | None] = mapped_column(Integer)
    base_volume: Mapped[float | None] = mapped_column(Rial)
    limit_up: Mapped[float | None] = mapped_column(Rial)
    limit_down: Mapped[float | None] = mapped_column(Rial)
    status: Mapped[str | None] = mapped_column(String(32))
    market_halt: Mapped[bool] = mapped_column(Boolean, default=False)


class PriceAdjustment(Base):
    """Adjustment event derived from ``prev_close`` != previous ``close``."""

    __tablename__ = "price_adjustments"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)  # first day at the new basis
    close_before: Mapped[float] = mapped_column(Rial)
    price_after: Mapped[float] = mapped_column(Rial)
    adj_factor: Mapped[float] = mapped_column(Float)  # price_after / close_before
    derived_from: Mapped[str] = mapped_column(String(32), default="prev_close_gap")


class ClientTypeDaily(Base, Provenance):
    """Real (I = حقیقی) vs legal (N = حقوقی) buy/sell breakdown."""

    __tablename__ = "client_types_daily"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    buy_count_i: Mapped[int | None] = mapped_column(Integer)
    buy_count_n: Mapped[int | None] = mapped_column(Integer)
    sell_count_i: Mapped[int | None] = mapped_column(Integer)
    sell_count_n: Mapped[int | None] = mapped_column(Integer)
    buy_volume_i: Mapped[float | None] = mapped_column(Rial)
    buy_volume_n: Mapped[float | None] = mapped_column(Rial)
    sell_volume_i: Mapped[float | None] = mapped_column(Rial)
    sell_volume_n: Mapped[float | None] = mapped_column(Rial)
    buy_value_i: Mapped[float | None] = mapped_column(Rial)
    buy_value_n: Mapped[float | None] = mapped_column(Rial)
    sell_value_i: Mapped[float | None] = mapped_column(Rial)
    sell_value_n: Mapped[float | None] = mapped_column(Rial)


class IntradaySnapshot(Base, Provenance):
    __tablename__ = "intraday_snapshots"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    last_price: Mapped[float | None] = mapped_column(Rial)
    cum_volume: Mapped[float | None] = mapped_column(Rial)
    cum_buy_volume_i: Mapped[float | None] = mapped_column(Rial)
    cum_sell_volume_i: Mapped[float | None] = mapped_column(Rial)
    cum_buy_volume_n: Mapped[float | None] = mapped_column(Rial)
    cum_sell_volume_n: Mapped[float | None] = mapped_column(Rial)


class OrderBookSnapshot(Base, Provenance):
    __tablename__ = "order_book_snapshots"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    # [{"row": 1, "bid_price": .., "bid_volume": .., "bid_count": .., "ask_price": ..}, ...]
    levels: Mapped[list[Any]] = mapped_column(JsonType)


class CorporateEvent(Base, Provenance):
    __tablename__ = "corporate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    announced_at: Mapped[dt.date | None] = mapped_column(Date)
    event_date: Mapped[dt.date | None] = mapped_column(Date)
    dps: Mapped[float | None] = mapped_column(Float)
    increase_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(32))
    payment_schedule: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Codal-derived events: the letter they came from and its stage (invitation, decisions, ...).
    tracing_no: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    stage: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(Text)


class CodalLetter(Base, Provenance):
    """One row of the Codal letter index (search.codal.ir), as published."""

    __tablename__ = "codal_letters"

    tracing_no: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    company_name: Mapped[str | None] = mapped_column(Text)
    letter_code: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    has_html: Mapped[bool] = mapped_column(Boolean, default=False)
    has_excel: Mapped[bool] = mapped_column(Boolean, default=False)
    has_pdf: Mapped[bool] = mapped_column(Boolean, default=False)
    under_supervision: Mapped[bool] = mapped_column(Boolean, default=False)


class RawPayload(Base):
    """Index of raw responses kept in MinIO before parsing."""

    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class FeatureRow(Base):
    __tablename__ = "features"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    feature_set_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    values: Mapped[dict[str, Any]] = mapped_column(JsonType)


class LabelRow(Base):
    __tablename__ = "labels"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    y: Mapped[int] = mapped_column(Integer)
    realized_return: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(String(24))
    exit_date: Mapped[dt.date | None] = mapped_column(Date)


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (UniqueConstraint("timeframe", "version", name="uq_model_runs_tf_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timeframe: Mapped[str] = mapped_column(String(4))
    version: Mapped[str] = mapped_column(String(64))
    train_window: Mapped[dict[str, Any]] = mapped_column(JsonType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    feature_set_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("date", "timeframe", "instrument_id", "model_version", name="uq_signal"),
        Index("ix_signals_date_tf", "date", "timeframe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[dt.date] = mapped_column(Date)
    timeframe: Mapped[str] = mapped_column(String(4))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    entry_price: Mapped[float] = mapped_column(Rial)
    entry_rule: Mapped[str] = mapped_column(String(64))
    take_profit: Mapped[float] = mapped_column(Rial)
    stop_loss: Mapped[float] = mapped_column(Rial)
    horizon_days: Mapped[int] = mapped_column(Integer)
    p_win: Mapped[float] = mapped_column(Float)
    ev: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    confidence_tier: Mapped[str] = mapped_column(String(1))
    position_pct: Mapped[float] = mapped_column(Float)
    top_reasons: Mapped[list[Any]] = mapped_column(JsonType)
    risks: Mapped[list[Any]] = mapped_column(JsonType)
    model_version: Mapped[str] = mapped_column(String(64))
    data_snapshot_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(12), default="pending")
    realized_return: Mapped[float | None] = mapped_column(Float)
    outcome_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    timeframe: Mapped[str] = mapped_column(String(4))
    config: Mapped[dict[str, Any]] = mapped_column(JsonType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType)
    report_uri: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class SignalNote(Base):
    """Free-form record for daily "no recommendation" days so the UI can say so."""

    __tablename__ = "signal_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[dt.date] = mapped_column(Date)
    timeframe: Mapped[str] = mapped_column(String(4))
    model_version: Mapped[str] = mapped_column(String(64))
    data_snapshot_id: Mapped[str] = mapped_column(String(64))
    n_candidates: Mapped[int] = mapped_column(BigInteger)
    n_recommended: Mapped[int] = mapped_column(Integer)
    defensive_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("date", "timeframe", "model_version", name="uq_signal_run"),)


class MarketIndexDaily(Base, Provenance):
    """Daily level of an official TSETMC index (TEDPIX, the equal-weight index, ...)."""

    __tablename__ = "market_index_daily"

    index_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)


class MacroSeries(Base, Provenance):
    """A macro or reference series point (risk-free rate, inflation, FX, ...). ``ref_period``
    is the day the value refers to; ``release_date`` is when it became public (point-in-time)."""

    __tablename__ = "macro_series"

    series: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    ref_period: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    release_date: Mapped[dt.date | None] = mapped_column(Date)
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
