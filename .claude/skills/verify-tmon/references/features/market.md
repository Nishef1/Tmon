# Market, industries, compare

**What exists:**
- `/market`: indices, breadth, movers, real-money flow and all 47 groups, each expandable
  (`/market/overview`).
- `/market`, card «طلا، دلار و نفت» (`GET /macro/gold-oil`, computed per request from
  `macro_series`): 18k gold premium and coin bubble against ounce x free dollar with a gauge and a
  high/normal/low pill, and Brent in ounces of gold. Compare `gold_prem.value` with the big number.
  The Bahar Azadi card (`coin-bahar-bubble`) shows `coin_bahar`, its gold value and the ounce, with
  no gauge or pill (only Emami was studied).
- `/` top card (`GET /market/index`): TEDPIX and equal-weight index with candles, today's range,
  year high/low, week-to-year returns and 30-day breadth. Check the big close and change against the
  JSON `close` / `change`; volume bars are traded value in toman.
- `/industries`, «نبض صنایع» (`GET /industries/overview`): one card per industry, sortable. A card
  opens `/industries/<code>` (`GET /industries/<code>/detail`): consensus candles (equal / value
  weight toggle), returns against the market, breadth, 30-day real-money flow and one row per symbol
  (sortable; a click opens the symbol's own chart). Check `day` equals the mean of the members'
  `day` and that the members' `contrib` sum to it.
- `/industries`, top section «صادرات‌محور یا داخلی؟» (`GET /industries/map`, artifact
  `v2/industry_map.json`): three group cards that filter, one row per industry (axis bar, dollar
  badge, beta, cohesion, 3-month return; a click opens symbols and both halves' dollar link) and a
  residual correlation heatmap. Compare one row with the JSON.
- `/industries`: industry heatmap ranked by real traded value (not base volume), with filters,
  19 selectable columns and search (`/screener`, `/search`).
- `/compare`: symbols against inflation, the dollar and gold (`/compare`).
- `/compare#funds`: stocks, funds and rights in one list from `/compare/symbols` (kind, close,
  value, bubble where one exists, adjusted return and return ahead of inflation for holding 1, 3 or
  12 months). Check a stock such as شکام shows «سهم NAV ندارد» and a real return; group filter,
  search and sortable headers; clean bubbles first, then by real return.
- `/compare#leveraged`: the leveraged funds against the market, from `GET /funds/leveraged` (the
  artifact `v2/leveraged_funds.json` made by `tmon.tools.leveraged_funds`; empty before the first
  cycle run). Check beta near 1.8, every row names its history length (a short-history fund is not
  compared silently with a multi-year one), «قیمت ÷ NAV» is not called a bubble, and the fund-type
  table has the leveraged row in bold.
- `/compare#rights`: right issues traded in the last 30 days against base close minus 1000 rials
  (`/rights`), most below value first.

**How a user reaches it:** the top navigation.

**How to drive:** set one filter on `/industries` and confirm the row count and one row's numbers
against `GET /screener` with the same parameters. On `/compare`, pick a symbol with
`SymbolPicker` and check that the period return matches the API.

**What usually lies:**
- A symbol under one year old must show no yearly return, not 0.
- A daily return over 50% for a new listing is filtered out by design.
- Fund NAV only updates from the PC (fipiran is not reachable from the server).
