# Today and ranking (`/`)

**What exists:** the daily v2 ranking of the basket (top 100 by 20-day median value, plus liquid
buy-zone names), split into buy, hold and avoid zones. Rows show score, rank, buy-queue size
(«صف خرید سنگین (۲٫۴)») and the verdict. The page also has the market state card, defensive mode
and the autopilot card. Source: `tools/v2_ranking.py` writes `v2/ranking.json`, and
`api/routers/ranking.py` serves it. Verdicts come from `final_verdict` in `engine/verdict.py`.

**How a user reaches it:** home page.

**How to drive:**
- Compare `GET /v2/ranking` (`as_of`, `zone`, `queue_ratio`) with the table text for two or three
  rows.
- A row's verdict must equal the verdict on that symbol's own page. Open one buy-zone row and
  check.
- Symbols in a sell queue are in zone `excluded`.

**What usually lies:**
- `as_of` older than the price day: the cycle has not run, so this is not a UI bug.
- An unheld row saying «نگهداری»: a bug. It must say «صبر».
- A fund row with a verdict: a bug. Funds get a rank but no verdict.
- Weights: the page must say equal weights unless the adapt champion passed its gate on the same
  day (`weights_note`).
