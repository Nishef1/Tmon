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
- A buy lowered to a wait by the state veto (`vetoed`) shows a reason. A missing reason is a bug.
- The live quote is empty outside market hours. That is expected.
- `/entry` and `/book` need order-book history. Most illiquid symbols have none, and the page must
  say so instead of showing zeros.
