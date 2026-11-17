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


class SectorName(Base, Provenance):
    """Exchange industry-group code -> Persian name (TSETMC static data)."""

    __tablename__ = "sector_names"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


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
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
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
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
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
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
    feature_set_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    values: Mapped[dict[str, Any]] = mapped_column(JsonType)


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
    # the label's own y at resolution; null on signals resolved before it existed (then a hit
    # is outcome == "tp", the barrier target those models were trained on)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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


class Shareholder(Base, Provenance):
    """A major shareholder (about 1% or more) of an instrument, as TSETMC lists it. The table holds
    the latest list only; a refresh replaces the rows of the instruments it fetched."""

    __tablename__ = "shareholders"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    holder_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    percent: Mapped[float | None] = mapped_column(Float)
    change_amount: Mapped[int | None] = mapped_column(BigInteger)  # shares bought (+) or sold (-)


class FinancialStatement(Base, Provenance):
    """One financial statement filed under a symbol, as TSETMC lists it (balance sheet and income
    statement tables, million rial; EPS in rial). ``published_at`` is when it became public, so a
    study can use it point in time. Rows are ``[label, value, value, ...]`` with the columns of the
    filing: current period, same period last year, last year end (balance sheet: previous year
    end)."""

    __tablename__ = "financial_statements"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # consolidated | separate
    title: Mapped[str] = mapped_column(Text)
    period_end: Mapped[dt.date | None] = mapped_column(Date)
    fiscal_year_end: Mapped[dt.date | None] = mapped_column(Date)
    period_months: Mapped[int | None] = mapped_column(Integer)
    audited: Mapped[bool | None] = mapped_column(Boolean)
    balance: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    income: Mapped[list[Any]] = mapped_column(JsonType, default=list)


class TrackedPick(Base):
    """A symbol the user marked as bought (or about to buy), with the model forecast frozen on
    that day so it can be compared with what the candles actually did."""

    __tablename__ = "tracked_picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    entered_on: Mapped[dt.date] = mapped_column(Date)  # the day the user bought
    paid_price: Mapped[float | None] = mapped_column(Float)  # what the user paid, if given
    note: Mapped[str | None] = mapped_column(String(300))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JsonType)  # the frozen forecast
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class OrderBookDaily(Base, Provenance):
    """One day of the 5-level order book of one instrument, reduced from TSETMC's intraday
    ``BestLimits/{ins}/{date}`` change log: the book at the close of the session, time-weighted
    averages over the continuous session and the share of the session spent in a buy/sell queue."""

    __tablename__ = "order_book_daily"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
    n_events: Mapped[int] = mapped_column(Integer)
    close_bid_price: Mapped[float | None] = mapped_column(Float)
    close_ask_price: Mapped[float | None] = mapped_column(Float)
    close_bid_volume: Mapped[float | None] = mapped_column(Float)  # level 1
    close_ask_volume: Mapped[float | None] = mapped_column(Float)
    close_bid_count: Mapped[int | None] = mapped_column(Integer)
    close_ask_count: Mapped[int | None] = mapped_column(Integer)
    close_imbalance: Mapped[float | None] = mapped_column(Float)  # 5 levels, (bid-ask)/(bid+ask)
    open_imbalance: Mapped[float | None] = mapped_column(Float)  # book at the start of trading
    early_imbalance: Mapped[float | None] = mapped_column(Float)  # time-weighted first 30 minutes
    tw_imbalance: Mapped[float | None] = mapped_column(Float)  # whole continuous session
    tw_spread: Mapped[float | None] = mapped_column(Float)  # (ask1-bid1)/mid, two-sided books
    tw_depth_value: Mapped[float | None] = mapped_column(Float)  # rial, both sides, 5 levels
    tw_size_ratio: Mapped[float | None] = mapped_column(
        Float
    )  # bid per-order size / ask's, level 1
    frac_buy_queue: Mapped[float | None] = mapped_column(Float)  # share of session, ask side empty
    frac_sell_queue: Mapped[float | None] = mapped_column(Float)  # share of session, bid side empty
    peak_queue_volume: Mapped[float | None] = mapped_column(Float)  # largest one-sided queue


class IntradayProfileDaily(Base, Provenance):
    """One 15-minute slice of one instrument's session, reduced from TSETMC's ``BestLimits`` change
    log: the time-weighted mid price, the cheapest price a buyer could hit (best ask) and the
    dearest a seller could hit (best bid) inside the slice. ``window`` 0 is 09:00-09:15 and 13 is
    12:15-12:30. Prices are rial; what the slices say about the time of day is derived from many
    days at read time (:mod:`tmon.portfolio.timing`)."""

    __tablename__ = "intraday_profile_daily"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id"), primary_key=True, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    mid: Mapped[float | None] = mapped_column(Float)
    ask_min: Mapped[float | None] = mapped_column(Float)
    bid_max: Mapped[float | None] = mapped_column(Float)
    secs: Mapped[float | None] = mapped_column(Float)  # seconds of the slice with a two-sided book


class Portfolio(Base):
    """One user's portfolio. Each portfolio is separate: its own holdings, alert thresholds,
    notification channels and access key (only the SHA-256 of the key is stored)."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    owner: Mapped[str | None] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0)  # rial available for new buys
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)  # alert thresholds
    channels: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)  # notify targets
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Holding(Base):
    """A position of a portfolio: shares at an average price, with an optional stop."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "instrument_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    shares: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)  # rial per share
    bought_on: Mapped[dt.date | None] = mapped_column(Date)
    stop_price: Mapped[float | None] = mapped_column(Float)  # stop at today's price basis, rial
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    # The stop as the owner typed it and the day they typed it: a capital increase or a dividend
    # after that day lowers the price basis, and ``stop_price`` is moved down with it.
    stop_raw: Mapped[float | None] = mapped_column(Float)
    stop_set_on: Mapped[dt.date | None] = mapped_column(Date)


class PortfolioTrade(Base):
    """One line of a portfolio's ledger. Holdings are rebuilt from these lines plus the market's
    capital increases and dividends, so a sale has a realized profit and the cash moves with it.

    ``shares`` or ``price`` may be missing: the price is then the close of ``date`` and the size
    is ``amount / price`` (or an equal share of the portfolio), and the holding is flagged as
    estimated. ``fee`` is None when the standard rate for the instrument type applies."""

    __tablename__ = "portfolio_trades"
    __table_args__ = (Index("ix_portfolio_trades_portfolio_date", "portfolio_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    date: Mapped[dt.date] = mapped_column(Date)
    shares: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)  # rial per share
    amount: Mapped[float | None] = mapped_column(Float)  # rial, when only the money is known
    fee: Mapped[float | None] = mapped_column(Float)  # rial, actual fee when known
    cash_delta: Mapped[float] = mapped_column(Float, default=0.0)  # what it did to ``cash``
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|import|mofid|legacy
    external_id: Mapped[str | None] = mapped_column(String(80), index=True)  # import dedupe
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class BrokerLink(Base):
    """A portfolio linked to a broker account (Mofid's EasyTrader). ``token`` is the bearer token
    the broker's own site issued after the owner logged in there; it is never returned by the
    API. ``last_result`` is the last sync's summary."""

    __tablename__ = "broker_links"

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    broker: Mapped[str] = mapped_column(String(16), default="mofid")
    token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="new")  # new|login|linked|error
    message: Mapped[str | None] = mapped_column(String(300))
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)


class PortfolioAlert(Base):
    """An alert sent to one portfolio. ``dedupe_key`` makes one condition alert once until it gets
    worse; ``answer`` is the owner's reply (exit / hold / reduce) from the page or the messenger."""

    __tablename__ = "portfolio_alerts"
    __table_args__ = (Index("ix_portfolio_alerts_portfolio_created", "portfolio_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[int] = mapped_column(Integer)  # 1 info, 2 warning, 3 urgent
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    delivered: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    answer: Mapped[str | None] = mapped_column(String(16))
    answered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioBriefing(Base):
    """The pre-open (and hourly in-session) review of one portfolio: news, Codal, supervisor
    messages, overnight macro and the model's readings, with a final verdict per holding."""

    __tablename__ = "portfolio_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # preopen | hourly | manual
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    method: Mapped[str] = mapped_column(String(64))  # LLM model name, or "rules"
    doc: Mapped[dict[str, Any]] = mapped_column(JsonType)
