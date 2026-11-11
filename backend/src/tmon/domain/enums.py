from __future__ import annotations

from enum import StrEnum


class Timeframe(StrEnum):
    D1 = "D1"
    W1 = "W1"
    M1 = "M1"


class InstrumentType(StrEnum):
    STOCK = "stock"
    RIGHT = "right"
    ETF_EQUITY = "etf_equity"
    ETF_FIXED_INCOME = "etf_fixed_income"
    ETF_MIXED = "etf_mixed"
    ETF_COMMODITY = "etf_commodity"
    ETF_LEVERAGED = "etf_leveraged"
    BOND = "bond"
    OPTION_CALL = "option_call"
    OPTION_PUT = "option_put"
    FUTURE = "future"
    COMMODITY_CERTIFICATE = "commodity_certificate"
    # housing-facility rights, forward (salaf) contracts, capacity certificates, real-estate,
    # venture, private and fund-of-fund units: kept, never recommended
    OTHER = "other"


class QueueState(StrEnum):
    BUY_QUEUE = "buy_queue"
    SELL_QUEUE = "sell_queue"
    NONE = "none"


class ExitReason(StrEnum):
    TAKE_PROFIT = "tp"
    STOP_LOSS = "sl"
    BOTH_SAME_DAY = "tp_sl_same_day"
    HORIZON = "horizon"


class ConfidenceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class SignalOutcome(StrEnum):
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    EXPIRED = "expired"


class InstrumentStatus(StrEnum):
    ALLOWED = "allowed"
    HALTED = "halted"
    ALLOWED_RESERVED = "allowed_reserved"
