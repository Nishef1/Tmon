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


class FunnelStage(ApiModel):
    key: str
    label: str
    count: int
    lost: int
    alone: int = 0


class NearMiss(ApiModel):
    instrument: InstrumentOut | None
    p_win: float
    p_min: float | None
    shortfall: float | None
    ev: float
    bucket_n: int
    failed: list[str]


class DiagnosisStats(ApiModel):
    p_win_max: float | None
    p_win_median: float | None
    p_min_median: float | None
    p_breakeven_median: float | None
    ev_max: float | None
    ev_median: float | None
    n_ev_positive: int
    n_distinct_p_win: int = 0


class DiagnosisOut(ApiModel):
    """Exact numbers behind a day with few or no recommendations."""

    universe: int
    stages: list[FunnelStage]
    binding: str | None
    nearest: list[NearMiss]
    dropped_by_portfolio: dict[str, int]
    stats: DiagnosisStats
    ev_min_abs: float
    min_bucket_samples: int
    margin: float
    p_floor: float


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
    diagnosis: DiagnosisOut | None = None
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


class CodalLetterOut(ApiModel):
    title: str
    letter_code: str | None = None
    published_at: dt.date | None = None
    url: str | None = None
    has_excel: bool = False
    has_pdf: bool = False


class ShareholderOut(ApiModel):
    name: str
    shares: int | None = None
    percent: float | None = None
    change_amount: int | None = None  # shares bought (+) or sold (-) since the previous list


class InstrumentDetail(ApiModel):
    instrument: InstrumentOut
    adjusted: bool
    candles: list[Candle]
    features_date: dt.date | None
    features: list[FeatureValue]
    signals: list[SignalOut]
    events: list[CorporateEventOut] = []
    shareholders: list[ShareholderOut] = []  # major holders, largest first
    shareholders_at: dt.date | None = None  # when TSETMC's list was fetched
    letters: list[CodalLetterOut] = []  # latest Codal letters of any kind
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
    volume_ratio_30: float | None = None
    per_capita_buy: float | None = None
    per_capita_sell: float | None = None
    power: float | None = None
    net_real_value: float | None = None
    verdict: Literal["buy", "hold", "sell", "none"] = "none"
    verdict_label: str = ""
    rank: int | None = None
    gauge: float | None = None
    gauge_note: str | None = None  # exact reason when there is no gauge
    sector_name: str | None = None
    sector_code: str | None = None
    eps: float | None = None
    pe: float | None = None
    sector_pe: float | None = None
    # returns on adjusted closes: week, month, three months, year; None = no honest value
    ret_week: float | None = None
    ret_month: float | None = None
    ret_3m: float | None = None
    ret_year: float | None = None
    from_year_high: float | None = None  # close / year high - 1 (<= 0)
    from_year_low: float | None = None  # close / year low - 1 (>= 0)
    volume: float | None = None
    market_cap: float | None = None
    shares: float | None = None
    base_volume: float | None = None
    meeting_date: dt.date | None = None
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
    verdict_counts: dict[str, int] = {}
    flow_date: dt.date | None = None
    ranking_date: dt.date | None = None
    total: int
    rows: list[ScreenerRow]


class RankingRow(ApiModel):
    rank: int
    symbol: str
    name: str | None = None
    sector_code: str | None = None
    score: float | None = None
    zone: Literal["buy", "hold", "avoid", "excluded", "no_data"]
    queue_state: str | None = None
    median_value: float | None = None
    signals: dict[str, float | None]
    instrument_id: int | None = None
    close: float | None = None
    change_pct: float | None = None


class RankingEvidence(ApiModel):
    horizon_days: int
    ic: float | None = None
    ic_t: float | None = None
    top_excess: float | None = None
    bottom_excess: float | None = None
    excess_t: float | None = None
    n_days: int


class RankingGate(ApiModel):
    key: str
    passed: bool | None = None
    text: str


class RankingCandidate(ApiModel):
    candidate: str
    first: str
    last: str
    days: int
    annual: float | None = None
    annual_bench: float | None = None
    max_drawdown: float | None = None
    max_drawdown_bench: float | None = None
    verdict: str
    gates: list[RankingGate]


class RankingExposure(ApiModel):
    trend: float | None = None
    abs_mom: float | None = None
    vol_cap: float | None = None
    stress: float | None = None
    exposure: float | None = None


class RankingBook(ApiModel):
    n_buys: int
    cancelled_buys: int
    postponed_sells: int
    avg_held: float


class RankingOut(ApiModel):
    """The v2 model ranking of the liquid basket. ``recommendation_allowed`` is true only when
    every gate of ADR 0003 section 7 passed; until then the list is a ranking, not advice."""

    available: bool
    disclaimer: str = DISCLAIMER
    as_of: str | None = None
    basket_size: int | None = None
    recommendation_allowed: bool = False
    buy_top_frac: float | None = None
    hold_top_frac: float | None = None
    exposure: RankingExposure | None = None
    exposure_date: str | None = None
    rows: list[RankingRow] = []
    evidence: list[RankingEvidence] = []
    gates: list[RankingCandidate] = []
    book: RankingBook | None = None


class MarketIndexPoint(ApiModel):
    code: str
    close: float
    change: float | None = None
    date: str


class MarketBand(ApiModel):
    label: str
    count: int


class MarketMover(ApiModel):
    instrument_id: int
    symbol: str
    name: str | None = None
    sector_name: str | None = None
    close: float | None = None
    change: float | None = None
    value: float | None = None
    net_real_flow: float | None = None


class MarketSector(ApiModel):
    sector_code: str
    name: str | None = None
    n: int
    avg_change: float | None = None
    value: float
    net_real_flow: float | None = None


class MarketFlow(ApiModel):
    date: str
    n_symbols: int
    real_buy_value: float
    real_sell_value: float
    legal_buy_value: float
    legal_sell_value: float
    real_net: float
    per_capita_buy: float | None = None
    per_capita_sell: float | None = None
    power: float | None = None


class MarketOverviewOut(ApiModel):
    """End-of-day market overview from the daily tables (no intraday data)."""

    available: bool
    price_date: str | None = None
    n_stocks: int = 0
    up: int = 0
    down: int = 0
    flat: int = 0
    at_limit_up: int = 0
    at_limit_down: int = 0
    n_outliers: int = 0
    limits_exact: bool = False
    total_value: float = 0.0
    median_change: float | None = None
    indices: list[MarketIndexPoint] = []
    bands: list[MarketBand] = []
    flow: MarketFlow | None = None
    gainers: list[MarketMover] = []
    losers: list[MarketMover] = []
    by_value: list[MarketMover] = []
    inflow: list[MarketMover] = []
    outflow: list[MarketMover] = []
    sectors: list[MarketSector] = []


class DashPrice(ApiModel):
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    last: float | None = None
    close: float | None = None
    prev_close: float | None = None
    last_change: float | None = None
    close_change: float | None = None
    limit_up: float | None = None
    limit_down: float | None = None
    trades: int | None = None
    volume: float | None = None
    value: float | None = None
    base_volume: float | None = None
    avg_volume_10: float | None = None
    avg_volume_22: float | None = None
    volume_ratio_30: float | None = None


class DashFlow(ApiModel):
    date: str
    buy_volume_i: float | None = None
    buy_volume_n: float | None = None
    sell_volume_i: float | None = None
    sell_volume_n: float | None = None
    buy_count_i: int | None = None
    buy_count_n: int | None = None
    sell_count_i: int | None = None
    sell_count_n: int | None = None
    per_capita_buy: float | None = None
    per_capita_sell: float | None = None
    power: float | None = None
    net_real_value: float | None = None
    net_real_volume: float | None = None
    avg10_per_capita_buy: float | None = None
    avg10_per_capita_sell: float | None = None
    avg10_power: float | None = None


class DashFund(ApiModel):
    nav_date: str
    nav: float
    bubble: float | None = None


class DashSignal(ApiModel):
    """One of the model's four signals in plain words: where the symbol stands among all scored
    stocks (``pct`` 0-100, higher is better for every signal)."""

    key: str
    name: str
    pct: float
    text: str


class DashHolding(ApiModel):
    """How long the model's call is meant to be held, in plain words, with the measured edge."""

    horizon_days: int
    expected_excess: float | None = None  # mean excess return of the top group over the market
    lines: list[str] = []


class DashMeeting(ApiModel):
    """The next general assembly announced on Codal, with the day read from the invitation."""

    date: dt.date
    clock: str | None = None
    kind: str
    days_left: int
    title: str


class DashEvent(ApiModel):
    date: dt.date | None = None
    label: str
    title: str | None = None


class DashShareChange(ApiModel):
    date: dt.date
    shares_old: int
    shares_new: int
    change_pct: float | None = None


class DashRanges(ApiModel):
    week_min: float | None = None
    week_max: float | None = None
    year_min: float | None = None
    year_max: float | None = None


class DashFundamental(ApiModel):
    eps: float | None = None
    pe: float | None = None
    sector_pe: float | None = None
    vs_sector: float | None = None
    verdict: Literal["cheap", "fair", "expensive", "loss", "unknown"] = "unknown"
    text: str = ""


class DashHorizon(ApiModel):
    """The decision for one holding period, with the past evidence it rests on."""

    key: str  # D1, W1, M1, Q1
    label: str  # e.g. "یک ماه"
    days: int  # trading days
    verdict: Literal["buy", "hold", "sell", "none"]
    verdict_label: str
    headline: str
    reasons: list[str] = []
    top_excess: float | None = None  # past gross excess return of the top group over the market
    cost: float | None = None  # round-trip trading cost as a fraction
    net_excess: float | None = None  # top_excess - cost
    ic: float | None = None
    ic_t: float | None = None


class DashDecision(ApiModel):
    """The single final answer per symbol: buy, hold, sell or none, with the reasons."""

    verdict: Literal["buy", "hold", "sell", "none"]
    label: str
    advice_allowed: bool = False
    headline: str
    reasons: list[str] = []
    as_of: str | None = None
    rank: int | None = None
    basket_size: int | None = None
    score: float | None = None
    gauge: float | None = None  # score on 0-100 for the semicircle gauge; None = not scored
    in_basket: bool = False  # inside the validated liquid basket; False = unvalidated score
    summary: str = ""  # one plain sentence on what the verdict means for the reader
    signals: list[DashSignal] = []
    holding: DashHolding | None = None
    horizons: list[DashHorizon] = []  # one decision per holding period


class TurningHorizon(ApiModel):
    horizon_days: int
    n: int
    excess_mean: float  # forward return minus the same-day mean of the liquid universe
    excess_median: float
    beat: float  # share of cases that beat that mean
    raw_median: float
    p_up50: float  # share with a +50% return over the horizon
    p_dn20: float  # share with a -20% return over the horizon


class TurningState(ApiModel):
    """One state of the turning-point history (tmon.backtest.turning)."""

    key: str
    title: str
    meaning: str
    tone: Literal["up", "down", "none"]  # an edge both halves of the history agree on, or none
    skewed: bool = False  # positive mean carried by a few large winners
    n: int
    symbols: int | None = None
    episodes: int | None = None
    horizons: list[TurningHorizon] = []
    mae60_median: float | None = None  # worst close in the 60 days after entry
    mae60_p10: float | None = None
    halves_excess_120: list[float | None] = []


class TurningTrigger(ApiModel):
    when: str
    state: TurningState


class TurningWarning(ApiModel):
    """The one tested sell warning (high volume, a down day, individuals selling) when it fired
    in the symbol's last few weeks, with its history on all liquid symbols."""

    title: str
    meaning: str
    date: dt.date  # last day it fired
    days_ago: int  # trading days since then
    recent_days: int
    n: int
    symbols: int | None = None
    horizons: list[TurningHorizon] = []
    halves_excess_60: list[float | None] = []


class DashTurning(ApiModel):
    """Where the symbol stands in its fall or run-up and what history says about that place."""

    as_of: dt.date
    state: TurningState
    base: TurningState  # all liquid symbols, for comparison
    triggers: list[TurningTrigger] = []
    dd: float | None = None  # below the 52-week high
    ret20: float | None = None
    ret60: float | None = None
    rsi: float | None = None
    net5: float | None = None
    power5: float | None = None
    above_sma20: bool | None = None
    liquid: bool = False
    market_bull: bool | None = None
    market_drawdown: float | None = None
    round_trip_cost: float
    history_first: dt.date
    history_last: dt.date
    split_date: dt.date
    warning: TurningWarning | None = None


class DashPeer(ApiModel):
    """One stock of the same industry group, for picking the best of the group."""

    id: int
    symbol: str
    name: str | None = None
    score: float | None = None  # composite score 0-100 (v2 ranking), None when not scored
    verdict: Literal["buy", "hold", "sell", "none"] = "none"
    in_basket: bool = False  # inside the validated liquid basket
    pe: float | None = None
    ret60: float | None = None
    dd: float | None = None  # below the 52-week high
    turning_key: str | None = None
    turning_title: str | None = None
    turning_tone: Literal["up", "down", "none"] | None = None
    is_self: bool = False


class DashPeers(ApiModel):
    """The symbol among the stocks of its industry group, best composite score first."""

    sector_name: str | None = None
    position: int | None = None  # the symbol's place among the scored stocks of the group
    scored: int = 0
    total: int = 0
    items: list[DashPeer] = []


class DriverMove(ApiModel):
    """The stock against the index in the 20 trading days after one dated shock."""

    date: dt.date
    kind: Literal["war", "sanction", "unrest", "deal", "politics", "market", "other"]
    title: str
    source: str
    stock: float
    index: float


class DashDrivers(ApiModel):
    """What moves the stock besides its own chart: index, dollar, copper, Brent and shocks.
    A description of the past; none of it feeds the verdict."""

    as_of: dt.date
    weeks: int | None = None  # weeks behind the betas (up to three years)
    beta_index: float | None = None  # move for a 1% index move
    beta_usd: float | None = None  # extra move for a 1% dollar move, on top of the index
    r2: float | None = None  # share of the weekly swing the index and dollar explain
    corr_copper: float | None = None  # 4-week correlations
    corr_brent: float | None = None
    usd_pctl: float | None = None  # share of the last years' days its dollar price was lower
    usd_from_peak: float | None = None
    usd_years: float | None = None
    div_date: dt.date | None = None
    dps: float | None = None  # rial per share, read off the price gap
    div_yield: float | None = None
    event_days: int
    moves: list[DriverMove] = []
    lines: list[str] = []


TaLabel = Literal["works", "backfires", "direction_only", "reverse_small", "no_edge", "too_few"]


class TaHorizon(ApiModel):
    """One horizon of a tested reading: candles after the entry at the next day's close."""

    h: int
    n: int
    excess_mean: float  # against the liquid symbols one could also trade that day
    excess_median: float
    up: float  # share of cases that went up
    up_all: float  # the same share for all those symbols on the same days
    halves: list[float | None] = []  # mean excess in the first and second half of the history
    years_pos: float | None = None  # share of calendar years with a positive mean excess


class TaSignal(ApiModel):
    """A classic reading of a glossary term, tested on the whole TSETMC history."""

    key: str
    term: str  # glossary key
    side: Literal["buy", "sell"]  # what the textbooks teach
    title: str
    label: TaLabel
    verdict: str  # one plain sentence
    n: int
    symbols: int
    locked_share: float | None = None  # entries dropped because the day was probably locked
    x20_with_locked: float | None = None  # 20-candle excess with those days left in
    profit_horizon: int | None = None
    direction_horizons: list[int] = []
    horizons: list[TaHorizon] = []


class TaSignalsOut(ApiModel):
    available: bool
    as_of: dt.date | None = None
    round_trip_cost: float | None = None
    dir_edge: float | None = None
    history_first: dt.date | None = None
    history_last: dt.date | None = None
    split_date: dt.date | None = None
    signals: list[TaSignal] = []


class DashTaValue(ApiModel):
    """Today's value of one indicator with its textbook reading."""

    key: str
    term: str  # glossary key
    name: str
    value: float | None = None
    unit: Literal["num", "pct", "price", "x"] = "num"
    reading: str
    tone: Literal["buy", "sell", "neutral"] = "neutral"


class DashTaFired(ApiModel):
    """A reading the symbol fired in its last trading days, with what it did in the past."""

    key: str
    term: str
    title: str
    side: Literal["buy", "sell"]
    date: dt.date
    ago: int  # trading days ago (0 = the last day)
    label: TaLabel
    verdict: str


class DashRisk(ApiModel):
    """The last 250 trading days of the symbol (longer than a year when it was halted)."""

    from_date: dt.date
    days: int
    ret_1y: float
    vol_ann: float  # annualised standard deviation of daily returns
    var95: float  # daily loss exceeded on one day in twenty
    max_dd: float
    sharpe: float | None = None
    sortino: float | None = None
    rf_annual: float | None = None  # one-year treasury yield used as the risk-free rate
    beta_index: float | None = None  # from the drivers document


class DashTechnical(ApiModel):
    """Every chart indicator of the glossary for this symbol, read the textbook way, and what
    those readings did on the whole exchange. Describes the past; none of it feeds the verdict."""

    as_of: dt.date
    recent_days: int
    round_trip_cost: float
    values: list[DashTaValue] = []
    fired: list[DashTaFired] = []
    risk: DashRisk | None = None
    lines: list[str] = []


EntryLabel = Literal["better", "worse", "same", "mixed", "too_few"]


class EntryHorizon(ApiModel):
    """``h`` candles after buying at the close of the day after the setup."""

    h: int
    n: int
    up: float  # share of entries above the entry price
    up_all: float  # the same share for every liquid symbol one could buy on the same days
    edge: float  # up - up_all
    halves_edge: list[float | None] = []  # the edge in the first and second half of the history
    excess_mean: float | None = None  # mean return over those symbols
    median: float | None = None  # median return of the entries


class EntrySetup(ApiModel):
    """A fixed entry condition and how the candles after it went on the whole exchange."""

    key: str
    group: Literal["all", "streak", "base", "uptrend"]
    title: str
    event: bool  # counted on the first day only (an entry candle) or on every day (a state)
    label: EntryLabel
    best_h: int | None = None
    verdict: str
    n: int
    symbols: int
    locked_share: float | None = None  # dropped: the entry day was probably locked at the limit
    horizons: list[EntryHorizon] = []
    dip_hit: float | None = None  # a close DIP below entry within DIP_WITHIN candles
    dip_hit_all: float | None = None
    dip_median: float | None = None  # median worst close in those candles
    win: float | None = None  # +WIN reached before LOSS within PATH candles
    win_all: float | None = None
    loss: float | None = None  # LOSS reached first
    loss_all: float | None = None


class EntryOddsOut(ApiModel):
    available: bool
    as_of: dt.date | None = None
    round_trip_cost: float | None = None
    dir_edge: float | None = None
    dip: float | None = None
    dip_within: int | None = None
    win: float | None = None
    loss: float | None = None
    path: int | None = None
    base_dd: float | None = None
    base_range: float | None = None
    base_days: int | None = None
    history_first: dt.date | None = None
    history_last: dt.date | None = None
    split_date: dt.date | None = None
    groups: dict[str, str] = {}
    setups: list[EntrySetup] = []


class DashEntryMark(ApiModel):
    """An entry candle of the symbol's last year, for the chart."""

    key: str
    title: str
    date: dt.date
    ago: int
    label: EntryLabel


class OwnOdds(ApiModel):
    """The symbol's own record ``h`` candles after any tradable day since this year's spring."""

    h: int
    n: int
    eff: int = 0  # separate tries behind the interval: one per h days, as the windows overlap
    up: float  # share of days the close h candles later was above the price paid
    lo: float  # 95% interval of that share
    hi: float
    up_all: float | None = None  # every liquid symbol on the same days
    q10: float | None = None  # 8 in 10 outcomes fell between q10 and q90
    q50: float | None = None
    q90: float | None = None


class OwnWindow(ApiModel):
    """The symbol's own record over one window: this year, the last 1/3/5 years or all."""

    key: str
    label: str
    since: dt.date
    odds: list[OwnOdds] = []
    forecast: list[str] = []


class DashEntry(ApiModel):
    """Where the symbol stands for a buyer now: its streak, whether it sits in a months-long base
    or an uptrend, and the tested odds of every setup it is in. Describes the past, not advice."""

    as_of: dt.date
    green: int  # green candles in a row up to the last day (0 when the last one was not green)
    red: int
    in_base: bool
    in_up: bool
    dd: float | None = None  # from the 52-week high
    rng60: float | None = None  # band of the last 60 closes
    now: list[EntrySetup] = []
    marks: list[DashEntryMark] = []
    lines: list[str] = []
    own_since: dt.date | None = None
    own_close: float | None = None  # last adjusted close: the price the ranges are drawn from
    own: list[OwnOdds] = []
    forecast: list[str] = []  # the plain answer: what the next candles usually did
    windows: list[OwnWindow] = []  # the same over every window the symbol has data for


class InstrumentDashboard(ApiModel):
    instrument: InstrumentOut
    isin: str | None = None
    sector_name: str | None = None
    board: str | None = None
    shares: int | None = None
    market_cap: float | None = None
    price: DashPrice | None = None
    flow: DashFlow | None = None
    fund: DashFund | None = None
    fundamental: DashFundamental | None = None
    base_volume: float | None = None
    ranges: DashRanges | None = None
    meeting: DashMeeting | None = None
    events: list[DashEvent] = []
    share_changes: list[DashShareChange] = []
    decision: DashDecision
    turning: DashTurning | None = None
    peers: DashPeers | None = None
    drivers: DashDrivers | None = None
    technical: DashTechnical | None = None
    entry: DashEntry | None = None


class SearchHit(ApiModel):
    instrument: InstrumentOut
    sector_name: str | None = None
    kind: str
    close: float | None = None
    change_pct: float | None = None
    verdict: Literal["buy", "hold", "sell", "none"] = "none"
    verdict_label: str = ""
    gauge: float | None = None
    eps: float | None = None
    pe: float | None = None
    sector_pe: float | None = None


class SearchOut(ApiModel):
    query: str
    total: int
    hits: list[SearchHit]
