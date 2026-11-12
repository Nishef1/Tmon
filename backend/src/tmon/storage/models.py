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


class ShareChange(Base, Provenance):
    """A change in the number of shares (capital increase, split, merger), TSETMC
    ``InstrumentAndShare``: ``shares_old`` before and ``shares_new`` after ``date``."""

    __tablename__ = "share_changes"

    idn: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    ins_code: Mapped[str] = mapped_column(String(32), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shares_new: Mapped[int] = mapped_column(BigInteger)
    shares_old: Mapped[int] = mapped_column(BigInteger)


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


class CodalReport(Base, Provenance):
    """One parsed report body (a Codal letter's Excel export). Every letter is its own version:
    a correction («اصلاحیه») is a new letter for the same period, so the current figures for a
    period are those of the latest-published report with that ``letter_code`` and ``period_end``
    and no ``subsidiary``."""

    __tablename__ = "codal_reports"

    tracing_no: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("codal_letters.tracing_no"), primary_key=True, autoincrement=False
    )
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    letter_code: Mapped[str | None] = mapped_column(String(16), index=True)
    period_end: Mapped[str | None] = mapped_column(String(10), index=True)  # Jalali, 1405/07/30
    is_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    # a subsidiary's report filed under the parent's symbol; not a version of the parent's report
    subsidiary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    format_signature: Mapped[str] = mapped_column(String(16), index=True)
    n_tables: Mapped[int] = mapped_column(Integer)
    n_cells: Mapped[int] = mapped_column(Integer)
    raw_object_key: Mapped[str | None] = mapped_column(Text)


class CodalReportCell(Base):
    """A non-empty cell of a parsed report, with its section title, row label and header path."""

    __tablename__ = "codal_report_cells"

    tracing_no: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("codal_reports.tracing_no"), primary_key=True, autoincrement=False
    )
    table_index: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    row_index: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    col_index: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    table_title: Mapped[str | None] = mapped_column(Text)
    row_label: Mapped[str | None] = mapped_column(Text)
    col_header: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)


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


class FundNav(Base, Provenance):
    """Daily NAV of a mutual fund or ETF from fipiran (docs/06). ``cancel_nav`` is the
    redemption NAV used for the ETF bubble; ``instrument_id`` links listed (ETF) units."""

    __tablename__ = "fund_nav"

    reg_no: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    ins_code: Mapped[str | None] = mapped_column(String(32), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    fund_type: Mapped[int | None] = mapped_column(Integer)
    type_of_invest: Mapped[str | None] = mapped_column(String(32))
    cancel_nav: Mapped[float | None] = mapped_column(Float)
    issue_nav: Mapped[float | None] = mapped_column(Float)
    statistical_nav: Mapped[float | None] = mapped_column(Float)
    net_asset: Mapped[float | None] = mapped_column(Float)


class NewsRaw(Base, Provenance):
    """One news item as collected (docs/08 step 1), with its normalised title (step 2) and the
    first item of its duplicate cluster (step 3)."""

    __tablename__ = "news_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    title_norm: Mapped[str] = mapped_column(Text)
    cluster_id: Mapped[int | None] = mapped_column(Integer, index=True)


class NewsEvent(Base):
    """Structured event extracted from a news cluster by the LLM step (docs/08 step 4)."""

    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_raw.id"), unique=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    symbols: Mapped[list[str]] = mapped_column(JsonType, default=list)
    sectors: Mapped[list[str]] = mapped_column(JsonType, default=list)
    direction: Mapped[int] = mapped_column(Integer)
    magnitude: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[dt.date | None] = mapped_column(Date)
    horizon: Mapped[str | None] = mapped_column(String(8))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_fa: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
