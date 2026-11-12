# Data sources and analysis methods: what exists, what we reuse, what we do not copy

Scope: the request to collect all market data once, check completeness, reuse public open-source work
where it exists, and learn how the Iranian apps (Signal / iSignal, Rahavard365 and others) analyse
and present data. This report records what was actually checked. Where a source could not be read,
it says so.

## 1. Open-source work checked

| Project | What it gives | Licence | Used how |
|---|---|---|---|
| [m-ahmadi/tse-client](https://github.com/m-ahmadi/tse-client) | The `TseClient2.aspx` service shapes: `t=Instrument` (complete instrument list), `t=InstrumentAndShare` (share-count events), `t=ClosingPrices` (batched history from 2001-03-21, 50 instruments per request) | MIT | Endpoint shapes only; re-verified against live replies and re-implemented in `ingest/tsetmc/endpoints.py` and `bulk.py`. No code copied. |
| [5j9/tsetmc](https://github.com/5j9/tsetmc) | Async Python client: price history with adjustment, intraday states, market watch, client types (`client_type_all`), instrument search, an offline instrument dataset | GPL-3.0 | Read as a reference only. GPL-3.0 would bind this project if its code were included, so none is. |
| [netecoder/codal_scraper](https://github.com/netecoder/codal_scraper) | Codal client: financial statements (audited filter), monthly reports, board changes (letter ن-45), async client at 2 requests/s by default, cache | MIT | Reference for letter codes and filters. The project already has its own Codal ingestion with a stricter 4-second interval. |
| mahs4d/tsetmc-api | Older synchronous TSETMC wrapper; its own README lists parts still to be migrated to 5j9/tsetmc | not checked | Not used. |
| `codal-tsetmc-datastore` (PyPI) | Described as storing Codal statements plus TSETMC data | not checked | Not used; source not verified. |

No single maintained project covers both TSETMC market data and Codal disclosures end to end, so the
project keeps its own pipeline and borrows endpoint knowledge from the MIT-licensed tse-client.

Finding that changed the plan: the official service answers the full instrument list in one request
and the full history of 50 instruments in one request. The search-prefix crawl built for R0
(`ingest/tsetmc/delisted.py`) was a workaround for not knowing this. The bulk loader
(`ingest/tsetmc/bulk.py`) replaces it for coverage; the crawl stays as a cross-check.

## 2. What the Iranian apps do (public descriptions only)

Only public pages and third-party reviews were read. Nothing was scraped from, or sent to, these
services, and nothing here is their code or data. The Rahavard365 and Signal front pages are
script-rendered, so their own wording could not be read; what follows comes from review articles and
store listings and is as reliable as those are.

- **Rahavard365**: per a review comparison, full-history candlestick charts for all bourse symbols,
  timeframes from 1 minute to monthly, 70+ indicators (RSI, MACD, Bollinger, Ichimoku), drawing
  tools (trendlines, channels, Fibonacci incl. log charts), an advanced filter/screener, fundamental
  fields (EPS, P/E, dividend yield), a market map available before the open, and filters for real and
  legal buying power. Free tier with limits; advanced features paid.
- **Signal (iSignal)**: per its store listing, real-time prices, technical charts, Codal
  announcements, analytical reports on the index and on symbols and funds, smart filters, watchlist,
  fund investment and brokerage onboarding. **No source found says how its buy/sell signals are
  produced.** We therefore make no claim about its method.
- **Other apps** (Mofid Trader, BourseView, EasyTrader, Enigma Codal Plus, TSETMC's own watch
  filter): screeners over fundamentals (net profit, margin, P/E, P/B, growth versus the previous
  quarter), over trading data (price band, volume, value, buyer/seller power, queue state) and over
  money flow (real/legal buying power, "smart money" inflow). Enigma's own article lists the limits of
  the official TSETMC screener: most variables cover the current day or at most 21 days, no backtest,
  no export.

## 3. Methods common across them that fit this project

These are public, textbook-level ideas, not anyone's proprietary model:

1. **Real/legal (حقیقی/حقوقی) money flow**: per-capita buy and sell, buyer-to-seller power, net
   real-person inflow. Needs the client-type history, which the project already stores for the
   original universe; coverage for the new instruments is part of this work.
2. **Queue state and limit moves**: buy/sell queue days. Already in the model (`QueueState`) and in
   the R3 simulator.
3. **Fundamentals from Codal**: EPS, P/E, P/B, growth versus the previous period, dividend yield.
   Needs the Codal letters and parsed statements for every issuer; coverage work is under way (see §5).
4. **Technical indicators**: momentum, volatility, trend, volume. Already the v2 baseline signals.
5. **Backtesting the screen**: the thing the official screener cannot do, and what ADR 0003 gates
   G1-G6 are for.

## 4. Presentation ideas worth keeping

Market map with a choice of colouring metric; one-screen symbol page with price chart, money-flow
strip and the latest Codal items; filters saved as named presets; mobile-first tables with sticky
first column. All of these stay subject to the standing rules: Persian RTL, numbers link to the
glossary, the "not investment advice" notice, and no v2 output shown as a recommendation until the
gates pass.

## 5. Data plan and status

| Layer | Source | Status |
|---|---|---|
| Instrument universe, listed and delisted | `t=Instrument` | loaded (4,356 listed) |
| Share-count events | `t=InstrumentAndShare` | loaded (4,110 rows) |
| Daily history from 2001 | `t=ClosingPrices`, 50 per request | see the completeness audit |
| Client-type history | per-instrument endpoint | to extend to new instruments |
| Codal letter index | `search.codal.ir`, quota-limited | resumable backfill `ingest/codal/backfill.py` |
| Codal statements | Excel export per letter | after the index |

Companion file: [data-completeness.md](data-completeness.md), produced by
`python -m tmon.tools.data_audit`.

ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست.
