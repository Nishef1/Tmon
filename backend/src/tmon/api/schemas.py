"""API response models. Dates are ISO strings; the UI converts to Jalali for display."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from tmon.storage.models import Instrument


VerdictKey = Literal["buy", "candidate", "hold", "sell", "none"]

DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست"


class ApiModel(BaseModel):
    """Base of every response model.

    Fields with defaults are always serialised, so the OpenAPI schema marks them required;
    the frontend's generated types then have no spurious ``| undefined``.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class VerdictFields(ApiModel):
    """What every list that shows a per-symbol verdict also carries (ADR 0004 section 7): the code
    of the answer, the answer for an owner of the symbol, and the zone with its evidence grade."""

    code: str | None = (
        None  # buy, candidate, candidate_queue, wait, with_market, avoid, wait_market
    )
    holder_code: str | None = None  # hold, consider_sell
    holder_verdict: VerdictKey | None = None  # colour key of the owner's answer
    holder_label: str | None = None
    band: Literal["candidate", "middle", "avoid"] | None = None
    grade: Literal["proven", "probable", "unproven"] | None = None
    grade_label: str | None = None  # ثابت‌شده / احتمالی / ثابت‌نشده


class InstrumentOut(ApiModel):
    id: int
    symbol: str
    name: str | None = None
    sector_code: str | None = None
    instrument_type: str | None = None


def instrument_out(i: Instrument) -> InstrumentOut:
    return InstrumentOut(
        id=i.id,
        symbol=i.symbol_fa,
        name=i.name_fa,
        sector_code=i.sector_code,
        instrument_type=i.instrument_type,
    )


class InstrumentSlug(ApiModel):
    """The address of an instrument page: ``/instruments/<sector>/<symbol>``."""

    id: int
    sector: str
    symbol: str


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


class SymbolNewsOut(ApiModel):
    title: str
    source: str
    url: str | None = None
    published_at: dt.datetime | None = None


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
    events: list[CorporateEventOut] = []
    shareholders: list[ShareholderOut] = []  # major holders, largest first
    shareholders_at: dt.date | None = None  # when TSETMC's list was fetched
    letters: list[CodalLetterOut] = []  # latest Codal letters of any kind
    news: list[SymbolNewsOut] = []  # recent news whose title names the symbol or the company
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


class BookLevelOut(ApiModel):
    row: int
    bid_price: float
    bid_volume: float
    bid_count: int
    ask_price: float
    ask_volume: float
    ask_count: int


class LiveFlowOut(ApiModel):
    """Today's buying and selling by individuals (حقیقی) and institutions (حقوقی)."""

    buy_volume_person: float | None = None
    buy_volume_legal: float | None = None
    sell_volume_person: float | None = None
    sell_volume_legal: float | None = None
    buy_count_person: float | None = None
    sell_count_person: float | None = None


class ForecastHorizonOut(ApiModel):
    """One holding period of a symbol's price range (``portfolio/forecast.py``): the 80% range
    and the median as returns from ``price``, calibrated by the symbol's own backtest when it had
    enough windows, and the chance of ending above the price after one round trip of cost."""

    key: str
    label: str
    days: int
    low: float  # 10th percentile (calibrated when ``calibrated``)
    mid: float
    high: float  # 90th percentile
    p_gain_net: float
    calibrated: bool
    coverage80: float | None  # share of past windows that ended inside the raw 80% range
    windows: int  # independent past windows behind the backtest
    reliable: bool
    drift_weight: float


class SymbolForecastOut(ApiModel):
    available: bool
    reason: str | None = None
    as_of: str | None = None
    price: float | None = None  # rial, the price the ranges start from
    history_days: int = 0
    horizons: list[ForecastHorizonOut] = []


class LiveOut(ApiModel):
    """Price and 5-level order book of one instrument. ``source``: ``mofid`` (pushed live by
    Mofid's server, needs a linked account), ``tsetmc`` (fetched from TSETMC for this request) or
    ``stored`` (what the intraday poller last wrote)."""

    instrument_id: int
    available: bool
    source: str = "stored"
    high_allowed: float | None = None  # today's price limits
    low_allowed: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    trade_value: float | None = None
    trades: float | None = None
    flow: LiveFlowOut | None = None
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
    kind: str | None = None
    industry: str | None = None
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


class RightOut(ApiModel):
    instrument_id: int
    symbol: str
    name: str | None = None
    date: dt.date
    price: float
    base_id: int | None = None
    base_symbol: str | None = None
    base_date: dt.date | None = None
    base_close: float | None = None
    value: float | None = None
    bubble: float | None = None
    bubble_note: str | None = None


class SymbolValueOut(ApiModel):
    instrument_id: int
    symbol: str
    name: str | None = None
    kind: str
    industry: str | None = None
    close: float | None = None
    traded_value: float | None = None
    fair_value: float | None = None
    bubble: float | None = None
    bubble_note: str | None = None
    nominal_return: float | None = None
    real_return: float | None = None


class SymbolsValueOut(ApiModel):
    prices_date: dt.date | None = None
    months: int
    inflation_source: str
    inflation: float | None = None
    inflation_note: str | None = None
    rows: list[SymbolValueOut]
    disclaimer: str = DISCLAIMER


class RightsOut(ApiModel):
    as_of: dt.date | None = None
    nominal: float
    rights: list[RightOut]
    disclaimer: str = DISCLAIMER


class GoldRatioOut(ApiModel):
    value: float
    mean_52w: float | None = None
    deviation: float | None = None
    pct_rank_3y: float
    state: Literal["high", "normal", "low"] | None = None


class GoldOilOut(ApiModel):
    """Domestic gold against the ounce and the free dollar, and Brent against gold
    (docs/reports/gold-oil-2026-11.md)."""

    week: dt.date
    usd_free: float
    gold_18k: float
    coin_emami: float
    gold_usd: float
    brent_usd: float
    gold_18k_fair: float
    coin_fair: float
    usd_implied: float
    gold_prem: GoldRatioOut
    coin_bubble: GoldRatioOut
    oil_gold: GoldRatioOut
    coin_bahar: float | None = None
    coin_bahar_bubble: GoldRatioOut | None = None
    gold_prem_cuts: tuple[float, float]
    coin_bubble_cuts: tuple[float, float]
    disclaimer: str = DISCLAIMER


class ScreenerRow(VerdictFields):
    """One symbol on the latest trading day: market data, a few features and its verdict."""

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
    verdict: VerdictKey = "none"
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


class ScreenerOut(ApiModel):
    prices_date: dt.date | None = None
    verdict_counts: dict[str, int] = {}
    flow_date: dt.date | None = None
    ranking_date: dt.date | None = None
    total: int
    rows: list[ScreenerRow]


class RankingRow(VerdictFields):
    rank: int
    symbol: str
    name: str | None = None
    sector_code: str | None = None
    score: float | None = None
    zone: Literal["buy", "hold", "avoid", "excluded", "no_data"]
    verdict: Literal["buy", "candidate", "hold", "sell"] | None = None  # what the symbol page says
    basket_pct: float | None = None  # place among the liquid basket's scores, 0 = worst, 1 = best
    queue_state: str | None = None
    median_value: float | None = None
    in_basket: bool = True
    signals: dict[str, float | None]
    instrument_id: int | None = None
    close: float | None = None
    change_pct: float | None = None
    trade_state: Literal["active", "idle", "halted"] = "active"
    idle_days: int = 0
    last_trade_date: dt.date | None = None
    queue_ratio: float | None = None  # buy line at the close / usual daily volume; None = no line
    queue_level: Literal["weak", "medium", "heavy"] | None = None
    queue_orders: int | None = None  # orders in the line (level 1 bid count)
    queue_reach_pct: float | None = (
        None  # past share (0..1) of similar lines the next day's volume covered
    )
    queue_reach_cases: int | None = None  # how many past lines that share is based on


class OutsideRow(ApiModel):
    """A high-scored stock that is not in the liquid basket the model was tested on."""

    instrument_id: int
    symbol: str
    name: str | None = None
    score: float
    median_value: float | None = None  # median daily traded value, rial


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
    annual_bench: float | None = None  # the basket's own costed index (what the gate uses)
    annual_official: float | None = None  # official equal-weight index, same days
    annual_buy_hold: float | None = None  # the basket held without trading cost, same days
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


class RankingVerdictRule(ApiModel):
    """The fixed numbers of the per-symbol verdict (ADR 0004 section 5), from ``engine.yaml``."""

    horizon_days: int
    candidate_top_frac: float
    avoid_bottom_frac: float
    candidate_grade: Literal["proven", "probable", "unproven"]
    avoid_grade: Literal["proven", "probable", "unproven"]


class ZoneStat(ApiModel):
    """The past record of one zone, net of the round trip, in the whole period and each half."""

    deciles: list[int]
    net: float | None = None
    net_h1: float | None = None
    net_h2: float | None = None
    t: float | None = None
    grade: str  # ثابت‌شده / احتمالی / ثابت‌نشده


class ZoneProfile(ApiModel):
    days: int
    candidate: ZoneStat
    avoid: ZoneStat


class InvestedReference(ApiModel):
    """What buying and holding the liquid basket (S0) and the official index returned in the
    Phase 2 report's window, to show beside any annual return."""

    report: str
    first: str
    last: str
    s0_annual: float
    official_annual: float
    bill_annual: float


class MarketFund(ApiModel):
    """An equity fund of the market card: no verdict, never tested (ADR 0004 section 7)."""

    instrument_id: int
    symbol: str
    name: str | None = None
    value: float  # traded value on the last day, rial
    close: float | None = None
    nav: float | None = None  # redemption NAV, None when the fund's NAV is not stored
    nav_date: dt.date | None = None
    premium: float | None = None  # last price over NAV, minus one


class MarketCard(ApiModel):
    """The share of capital the model keeps in equities today, why, and the funds to hold it."""

    exposure: float
    date: str | None = None
    positive: bool
    reasons: list[str] = []
    funds: list[MarketFund] = []
    funds_note: str = ""


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
    outside: list[OutsideRow] = []  # best scores outside the basket, with why they are not listed
    universe_size: int | None = None
    weights: dict[str, float] = {}  # weights of the four signals in today's score
    weights_champion: str = "equal"  # which method set them ("equal" = the plain mean)
    weights_note: str | None = None
    verdict: RankingVerdictRule | None = None
    zones: dict[str, ZoneProfile] = {}  # by horizon in days: the record of both zones
    invested_reference: InvestedReference | None = None
    market_card: MarketCard | None = None


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
    verdict: VerdictKey
    verdict_label: str
    weak: bool = False  # hold only because the past does not back a sell; the score itself is low
    vetoed: bool = False  # a buy-zone score lowered to a wait by the symbol's own state
    headline: str
    reasons: list[str] = []
    top_excess: float | None = None  # past gross excess return of the top group over the market
    cost: float | None = None  # round-trip trading cost as a fraction
    net_excess: float | None = None  # top_excess - cost
    ic: float | None = None
    ic_t: float | None = None


class ZoneHorizon(ApiModel):
    """The past record of the stock's zone (candidate or avoid) at one holding period, net of
    the round trip, so the reader sees why the verdict is read at one horizon only."""

    days: int  # trading days held
    label: str  # e.g. "سه ماه"
    net: float  # mean excess over the 100 liquid names after the round trip
    net_h1: float  # the same in the first half of time
    net_h2: float  # ... and in the second half
    windows: int  # non-overlapping periods of this length in the sample
    status: Literal["loss", "proven", "probable", "unproven"]  # loss: negative in both halves
    verdict_horizon: bool = False  # the horizon the verdict above is read at


class DashDecision(VerdictFields):
    """The single final answer per symbol: buy, hold, sell or none, with the reasons."""

    verdict: VerdictKey
    label: str
    weak: bool = False  # low score, but not backed by the tested past enough to say sell
    advice_allowed: bool = False
    headline: str
    reasons: list[str] = []
    as_of: str | None = None
    rank: int | None = None
    basket_size: int | None = None
    score: float | None = None
    gauge: float | None = None  # score on 0-100 for the semicircle gauge; None = not scored
    in_basket: bool = False  # inside the validated liquid basket; False = unvalidated score
    zone_hold_from: float | None = None  # gauge value (0-100) where the hold zone starts
    zone_buy_from: float | None = None  # gauge value (0-100) where the buy zone starts
    queue_state: str | None = None  # buy_queue / sell_queue / none on the ranking day
    holder_headline: str = ""  # the headline for an owner of the symbol
    market_warning: bool = False  # exposure is zero today: the market itself says stay out
    summary: str = ""  # one plain sentence on what the verdict means for the reader
    signals: list[DashSignal] = []
    holding: DashHolding | None = None
    horizons: list[DashHorizon] = []  # one decision per holding period
    by_horizon: list[ZoneHorizon] = []  # the zone's record at each measured holding period


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


class RideBlock(ApiModel):
    n: int
    open: int = 0  # rides still running, valued at the last close
    net_mean: float
    net_median: float
    excess_mean: float  # over the liquid mean of the same days, after the round trip
    win: float
    hold_median: float


class RideHistory(RideBlock):
    """Rides of the rule from liquid signal days over the last ``history_years`` years."""

    first: dt.date
    last: dt.date
    split_date: dt.date
    halves: list[RideBlock]


class PastRide(ApiModel):
    """One finished or running ride of the symbol, for the marks on the chart."""

    entry_date: dt.date
    exit_date: dt.date | None = None  # None while the ride is open or the sale is still next
    gain: float  # from the buy to the sale, or to the last close while open


class Swing(ApiModel):
    """A past low or high that only hindsight shows: the price then moved ``trail`` or more the
    other way (``tmon.backtest.trend_ride.swings``). Not a signal."""

    date: dt.date
    kind: Literal["low", "high"]
    close: float


class RideLinePoint(ApiModel):
    """One step of a chart line; a null value ends the run (a gap until the next point)."""

    date: dt.date
    value: float | None = None


class DashRide(ApiModel):
    """The trend-ride hint (docs/reports/trend-ride-2026-11.md): the symbol's latest entry signal,
    the trailing exit line while the ride is open, and the rule's past rides. Prices are adjusted
    to today's share count."""

    rides: list[PastRide] = []  # every ride the rule made on this symbol, oldest first
    swings: list[Swing] = []  # past lows and highs, oldest first
    status: Literal["buy_next", "open", "sell_next", "closed"]
    signal_date: dt.date
    signal_close: float
    entry_date: dt.date | None = None
    entry_close: float | None = None
    peak_date: dt.date | None = None
    peak_close: float | None = None
    stop: float | None = None  # sell when a close falls below this
    # with no ride open: the lowest close for the next day that would be an entry signal
    buy_trigger: float | None = None
    day_rise_max: float | None = None  # largest close-to-close rise in the last 250 days
    exit_signal_date: dt.date | None = None
    exit_date: dt.date | None = None
    exit_close: float | None = None
    last_date: dt.date
    last_close: float
    # the newest market day of the document: a later day than last_date means the symbol has not
    # traded since (halted or delisted), so the ride is as of its last trade, not today
    market_date: dt.date | None = None
    gain: float | None = None  # from the buy to the sale, or to the last close while open
    days_since_exit: int | None = None
    # chart lines, as steps on the day whose close is compared with them: the sell line while a
    # ride was held, and the entry trigger on free days it was within 10% of the close
    sell_line: list[RideLinePoint] = []
    buy_line: list[RideLinePoint] = []
    near_high: float
    trail: float
    max_hold_days: int  # a ride ends after this many days unless the trend still holds
    same_day: bool = False  # buy and sell at the close of the day the line is crossed
    warn_band: float | None = None  # a buy or a sale is "near" within this move of its line
    grade: Literal["proven", "probable", "unproven"]
    history_years: int
    history: RideHistory | None = None


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
    ride: DashRide | None = None


class DashPeer(VerdictFields):
    """One stock of the same industry group, for picking the best of the group."""

    id: int
    symbol: str
    name: str | None = None
    score: float | None = None  # composite score 0-100 (v2 ranking), None when not scored
    verdict: VerdictKey = "none"
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


class EntryYear(ApiModel):
    """One Iranian year (Nowruz to Nowruz) of a setup: its edge over every other liquid symbol
    on the same days, 1, 5 and 20 candles after buying."""

    year: int  # the Iranian year, e.g. 1404
    n: int
    e1: float | None = None
    e5: float | None = None
    e20: float | None = None


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
    years: list[EntryYear] = []
    years_better: int = (
        0  # counted years (50+ entries) 3 points or more above the rest at 5 candles
    )
    years_worse: int = 0
    years_counted: int = 0


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
    trade_state: Literal["active", "idle", "halted"] = "active"
    last_trade_date: dt.date | None = None
    idle_days: int = 0
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


class SearchHit(VerdictFields):
    instrument: InstrumentOut
    sector_name: str | None = None
    kind: str
    close: float | None = None
    change_pct: float | None = None
    verdict: VerdictKey = "none"
    verdict_label: str = ""
    gauge: float | None = None
    eps: float | None = None
    pe: float | None = None
    sector_pe: float | None = None
    trade_state: Literal["active", "idle", "halted"] = "active"
    last_trade_date: dt.date | None = None
    idle_days: int = 0


class SearchOut(ApiModel):
    query: str
    total: int
    hits: list[SearchHit]


class BookPoint(ApiModel):
    """One simulated portfolio: annual excess over the median stock after costs and its t value."""

    excess: float
    t: float
    cagr: float | None = None
    cagr_benchmark: float | None = None
    early: float | None = None
    late: float | None = None
    turnover: float | None = None
    n: int | None = None


class BookLadderRow(ApiModel):
    universe: Literal["all", "liquid100"]
    review: int
    ideal: BookPoint
    locks: BookPoint
    missed_buys: float | None = None


class BookCapacityRow(ApiModel):
    notional_rial: float
    cells: dict[str, BookPoint]


class BookRandom(ApiModel):
    r5_zero_cost: float
    r5_with_cost: float
    r20_zero_cost: float
    r20_with_cost: float
    turnover: float


class BookIc(ApiModel):
    ic: float
    t: float


class BookFeature(ApiModel):
    key: str
    label: str
    meaning: str
    status: Literal["kept", "redundant", "dropped"]
    alone_ic5: float
    d1: float
    t1: float
    d5: float
    t5: float
    d20: float
    t20: float
    early5: float
    late5: float


class BookSelection(ApiModel):
    chosen: list[str]
    d1: float
    d5: float
    t5: float
    d20: float
    t20: float


class BookScoreSim(ApiModel):
    label: str
    base: BookPoint
    book: BookPoint


class BookAssumptions(ApiModel):
    cost_per_side: float
    max_wait_buy: int
    max_wait_sell: int
    participation: float


class OrderbookResearchOut(ApiModel):
    available: bool
    generated: dt.date | None = None
    book_days: int | None = None
    book_rows: int | None = None
    split: dt.date | None = None
    assumptions: BookAssumptions | None = None
    ladder: list[BookLadderRow] = []
    capacity: list[BookCapacityRow] = []
    random: BookRandom | None = None
    base_ic: dict[str, BookIc] = {}
    features: list[BookFeature] = []
    selection: dict[str, BookSelection] = {}
    score_sim: list[BookScoreSim] = []
    limits: list[str] = []
    disclaimer: str = DISCLAIMER


class BookDay(ApiModel):
    date: dt.date
    close_imbalance: float | None = None
    open_imbalance: float | None = None
    tw_imbalance: float | None = None
    tw_size_ratio: float | None = None
    frac_buy_queue: float | None = None
    frac_sell_queue: float | None = None
    peak_queue_volume: float | None = None
    close_bid_volume: float | None = None
    close_ask_volume: float | None = None
    tw_spread: float | None = None
    tw_depth_value: float | None = None
    last_close_gap: float | None = None


class BookFeatureRank(ApiModel):
    """Where this symbol stood among the stocks with a stored book on the latest day."""

    key: str
    label: str
    value: float | None = None
    percentile: float | None = None  # 0..1, 1 = most buyer-leaning of the day


class InstrumentBookOut(ApiModel):
    instrument_id: int
    available: bool
    message: str | None = None
    as_of: dt.date | None = None
    universe_size: int | None = None
    score_percentile: float | None = None  # mean percentile of the five features; 0..1
    ranks: list[BookFeatureRank] = []
    days: list[BookDay] = []
    disclaimer: str = DISCLAIMER


class AdaptCandidate(ApiModel):
    """One candidate method against equal weights on the latest window."""

    passed: bool
    reasons: list[str] = []
    n: int
    ic: float | None = None
    d_ic: float | None = None  # IC gain over equal weights
    t: float | None = None  # t of that gain (overlap-corrected)
    early: float | None = None  # gain in the first half of the window
    late: float | None = None  # gain in the second half
    top_excess: float | None = None  # top-decile excess return of the candidate
    d_top_excess: float | None = None  # ... minus the same for equal weights


class AdaptHorizon(ApiModel):
    horizon_days: int
    window_from: dt.date
    window_to: dt.date
    window_dates: int
    champion: str
    why: str
    production_expressible: bool  # weights are on the four production signals
    weights: dict[str, float]  # the champion's weights (equal when nobody passed)
    reference_weights: dict[str, float]  # what the reference ridge says now, for drift context
    candidates: dict[str, AdaptCandidate]


class AdaptDrift(ApiModel):
    dates: list[dt.date]
    series: dict[str, list[float]]  # signal -> the reference weight at each date


class AdaptHistoryRow(ApiModel):
    as_of: dt.date
    champions: dict[str, str]  # horizon (days) -> champion


class AdaptStat(ApiModel):
    n: int
    mean: float | None = None
    t: float | None = None
    pos: float | None = None  # share of dates with a positive value


class AdaptTimelinePoint(ApiModel):
    date: dt.date
    champion: str


class AdaptReplayHorizon(ApiModel):
    """What the gate would have chosen on each past cycle and how the choices scored."""

    horizon_days: int
    first_cycle: dt.date
    n_cycles: int
    share_equal: float  # share of cycles where equal weights stayed champion
    meta_ic: AdaptStat  # IC of the living choice
    equal_ic: AdaptStat
    d_ic: AdaptStat  # living minus equal
    d_ic_early: AdaptStat
    d_ic_late: AdaptStat
    d_top_excess: AdaptStat
    split_date: dt.date
    timeline: list[AdaptTimelinePoint]
    candidate_counts: dict[str, int]


class AdaptReplay(ApiModel):
    every: int
    as_of: dt.date | None = None
    horizons: dict[str, AdaptReplayHorizon]


class AdaptConfigOut(ApiModel):
    window_dates: int
    min_half_dates: int
    min_t: float
    switch_margin_t: float
    history_keep: int
    replay_every_dates: int
    candidates: list[str]


class AdaptOut(ApiModel):
    available: bool
    as_of: dt.date | None = None
    round_trip_cost: float | None = None
    config: AdaptConfigOut | None = None
    horizons: list[AdaptHorizon] = []
    drift: dict[str, AdaptDrift] = {}
    history: list[AdaptHistoryRow] = []
    replay: AdaptReplay | None = None
    disclaimer: str = DISCLAIMER


class AutopilotRegime(ApiModel):
    """The regime reading of the official index (``tmon.engine.regime``)."""

    as_of: dt.date
    drawdown: float  # fall from the peak, 0.2 = 20%
    return_recent: float  # index return over ``recent_days`` trading days
    recent_days: int
    windows: list[float]  # last non-overlapping 250-day returns, newest first
    bear_windows: int  # how many of them ended at -10% or worse
    bullish_only: bool  # none did: the data has not seen a nominal bear market
    stress: bool
    stress_drawdown: float


class AutopilotEvent(ApiModel):
    at: dt.date
    kind: str  # champion | regime
    horizon: int | None = None
    before: str | None = None
    after: str | None = None


class RegimeDecision(ApiModel):
    """One decision of the market-state plan: taken at ``date``'s close, filled at the next."""

    date: dt.date
    state: str  # falling | flat | rising
    breadth: float  # share of the basket above its 60-day mean
    action: str  # cash | trend (dust before 2026-11-18) | under_ma20 for a sale
    kind: str  # enter | exit | switch | wait | sell
    ranked: list[str] = []  # the shortlist in order; the first names not locked up are bought
    filled_on: dt.date | None = None
    names: list[str] | None = None  # what was actually bought on ``filled_on``
    sold: list[str] | None = None  # a "sell": held names that closed under their mean


class RegimePoint(ApiModel):
    date: dt.date
    plan: float  # toman
    basket: float
    cash: float


class RegimePaperOut(ApiModel):
    """The market-state plan run forward on paper from ``start`` (``tmon.tools.regime_paper``)."""

    available: bool
    checked_at: str | None = None
    as_of: dt.date | None = None
    start: dt.date | None = None
    capital: float | None = None
    edges: list[float] = []  # breadth at or below [0]: falling; above [1]: rising
    confirm_days: int | None = None
    renew_days: int | None = None
    plan: dict[str, str] = {}
    exit_ma: int | None = None  # a held name closing under its mean of this many days is sold
    breadth: float | None = None
    raw_state: str | None = None  # today's reading before confirmation
    run_days: int | None = None  # closes in a row the reading has held
    state: str | None = None  # the confirmed state the plan acts on
    action: str | None = None
    holding: list[str] = []
    pending: RegimeDecision | None = None  # decided at the last close, filled at the next
    days_to_renew: int | None = None
    bond_yield: float | None = None
    path: list[RegimePoint] = []
    log: list[RegimeDecision] = []
    disclaimer: str = DISCLAIMER


class AutopilotOut(ApiModel):
    """What the system saw when it last checked itself, and what changed since the checks before."""

    available: bool
    checked_at: str | None = None
    as_of: dt.date | None = None
    regime: AutopilotRegime | None = None
    events: list[AutopilotEvent] = []
    disclaimer: str = DISCLAIMER


class IndustryPeer(ApiModel):
    sector: str
    corr: float


class IndustryMapRow(ApiModel):
    sector: str
    group: Literal["export", "middle", "domestic"]
    n_stocks: int
    symbols: list[str]
    beta: float | None
    cohesion: float | None
    axis: float | None
    usd_corr: float | None
    usd_corr_h1: float | None
    usd_corr_h2: float | None
    dollar_tie: Literal["up_steady", "up_unsteady", "none", "down_unsteady", "down_steady"]
    ret_4w: float | None
    ret_13w: float | None
    ret_52w: float | None
    vs_market_13w: float | None
    closest: list[IndustryPeer]


class IndustryMarketReturns(ApiModel):
    ret_4w: float | None
    ret_13w: float | None
    ret_52w: float | None


class IndustryCorr(ApiModel):
    order: list[str]
    values: list[list[float | None]]


class IndustryMapOut(ApiModel):
    """Descriptive industry map from the PC cycle (``tmon.tools.industry_map``)."""

    as_of: str
    start: str
    mid: str
    n_weeks: int
    n_stocks: int
    dollar_tie_cut: float
    group_cut: float
    axis_share: float
    market: IndustryMarketReturns
    sectors: list[IndustryMapRow]
    corr: IndustryCorr
