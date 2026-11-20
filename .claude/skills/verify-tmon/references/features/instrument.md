# One symbol (`/instruments/[industry]/[symbol]`)

**What exists:** from the top, the header (close, change, queue, whether this browser holds the
stock, freshness of each source), the live quote, the **verdict** with its summary (one-month
verdict, the six-month record of the current state, the queue, the exit level), the chart with a
percent ruler and Heikin-Ashi, the news and Codal timeline, the current state, drivers and group.
Collapsed sections: entry lab, technical and risk, buyer behaviour, valuation, shareholders
and the AGM calculator.

**How a user reaches it:** clicking a symbol anywhere, or search.

**How to drive:**
- Get the id from `GET /search?q=<symbol>`. Then compare `GET /instruments/{id}/dashboard`
  (`verdict`, and `vetoed` when the state veto lowered a buy) with the verdict text.
- Expand each section the change touches. Collapsed content is not rendered until it is opened.
- To check «صبر» against «نگهداری», look at the same symbol once with no portfolio and once held
  in a test portfolio. Delete the test portfolio afterwards.

**What usually lies:**
- One exit level: with an open trend ride, the checklist's «از کجا بفهمم اشتباه بوده‌ام؟» row, the
  trend card and the chart's «خط فروش فردا» must show the same number. A tested sell sign in the
  technical section («جواب داده») must also appear as a ! row in the checklist.
- «بازهٔ یک هفته» and «بازهٔ یک سال» must include today's price; a top below today's close is stale.
- The price axis never shows negative prices (the volume bars push the scale below zero).
- A buy lowered to a wait by the state veto (`vetoed`) shows a reason. A missing reason is a bug.
- The live quote is empty outside market hours. That is expected.
- `/entry` and `/book` need order-book history. Most illiquid symbols have none, and the page must
  say so instead of showing zeros.
- Chart marks: «روند خرید» and «روند فروش» are the rule's own days (`turning.ride.rides`); grey
  «کف» and «سقف» circles are hindsight swings (`turning.ride.swings`), a move of the trail's size
  after each. A «روند فروش» in the middle of a rising trend after 250 days is the old cap bug
  (docs/reports/trend-marks-2026-11.md). Check شکام: one open ride bought on 2025-05-24.
- The trend card trades at the close of the crossing day (`same_day`), not the next close. With no
  ride open it shows «قیمت نشانهٔ ورود بعدی» (`buy_trigger`), or says tomorrow cannot signal when
  the trigger is further than the stock's largest one-day rise (`day_rise_max`). A trigger many
  times today's price shown as reachable is a bug (docs/reports/trend-timing-2026-11.md).
- Within `warn_band` (3%) of tomorrow's entry price or sell line the card shows `ride-warn`
  (`data-side` buy or sell) with the measured hit rate. The chart draws the history of «خط فروش»
  (red) and «قیمت ورود» (green) as dashed steps with a dotted band edge, broken where no ride or no
  near trigger applies; they come from `v2/ride_lines/{iid}.json` and only when its `as_of` matches
  turning.json. A step line running across a gap is a bug (docs/reports/trend-warn-2026-11.md).
  Check کوثر for a buy warning.
- A halted or delisted symbol (`ride.last_date` before `ride.market_date`) shows `ride-stale` and
  no `ride-warn` or buy trigger. Check بتک (id 4058, last trade 2011). A ride shown as open «today» for it is a bug.
- The chart's «اندازهٔ هر شمع» buttons (`chart-tf`) switch to weekly, monthly, 3-month and 6-month
  candles (Persian calendar, `lib/timeframe.ts`) and show `chart-tf-note`. The trend marks must
  stay on the candle of their period, and the sell line must step once per candle. A mark missing
  after a switch, or a candle whose high is under its close, is a bug
  (docs/reports/trend-audit-2026-11.md).
- The «اگر این مدت نگه دارید» card (`data-testid="outlook"`, `?p=day|days3|week|month|quarter|half`,
  default quarter) comes from `GET /instruments/{id}/forecast`. Compare `low`, `mid`, `high` times
  `price` with the card. Every period must end with the page's one
  three-month verdict; a short period claiming its own buy is a bug
  (docs/reports/verdict-parts-2026-11.md). Check شکام (quarter, calibrated) and کوثر (week, trend
  entry inside the range). A period with too few separate windows says «بازه آزموده نیست».
- The «پیش‌بینی کندل‌های بعد» section (`data-testid="next-candles"`, `#forecast`, under the price
  chart, `components/stock/NextCandles.tsx`) draws the last 30 closes as a line, then from today a
  fan: the median line through one point per period (`nc-point-<key>`, `data-up="1"` exactly when
  `mid >= 0`) and the `low`..`high` band, on a log price axis. The fan stops at 20 trading days
  (day to month); a chip (`nc-chip-<key>`) for quarter or half stretches it to that period. A period
  with `reliable=false` is a dashed median segment with a note under the chart. `nc-summary` repeats
  the chosen period; clicking a point or chip goes to `?p=<key>#forecast` and the outlook card
  follows. The «سابقهٔ خود سهم» toggle (`nc-own`) switches to `entry.windows[].odds` of the
  dashboard (q10/q50/q90 after 1 to 20 candles, «X بار از ۱۰ بالاتر بسته شد»). The price chart
  itself draws no forecast range. No hydration warning in the console (coordinates are rounded).
- A tradable fund (type `etf_*`, e.g. پیشران id 1419, a leveraged fund) has every section of a stock
  page: gauge and month verdict (`final_verdict`, grade always «ثابت‌نشده», never «بخر»), trend ride
  (`ride_only`, `fund_rides` in turning.json), ranges and the checklist. Each carries its fund test
  line (`fund-test`, `fund-ride-note`, `fund-ranges-note`, `fund-checks-note`, from `api/fund_notes.py`
  and docs/reports/fund-verdict-2026-11.md). Missing test lines, a «بخر»/«بفروش» on a fund, or the
  stock study's numbers on the fund's ride card are bugs. A fund in a sell queue or with under a year
  of history still says «امروز تصمیمی نیست» with the reason; an unheld fund waits with «صبر».
