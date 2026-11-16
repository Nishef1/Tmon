# Market, industries, compare

**What exists:**
- `/market`: indices, breadth, movers, real-money flow and all 47 groups, each expandable
  (`/market/overview`).
- `/industries`: industry heatmap ranked by real traded value (not base volume), with filters,
  19 selectable columns and search (`/screener`, `/search`).
- `/compare`: symbols against inflation, the dollar and gold (`/compare`).
- Fund NAV and bubble come from `/funds`.

**How a user reaches it:** the top navigation.

**How to drive:** set one filter on `/industries` and confirm the row count and one row's numbers
against `GET /screener` with the same parameters. On `/compare`, pick a symbol with
`SymbolPicker` and check that the period return matches the API.

**What usually lies:**
- A symbol under one year old must show no yearly return, not 0.
- A daily return over 50% for a new listing is filtered out by design.
- Fund NAV only updates from the PC (fipiran is not reachable from the server).
