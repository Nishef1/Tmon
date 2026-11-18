# Model and accuracy (`/model`)

**What exists:** one page with these anchors:
- the live algorithm `#adapt` (champion per horizon, weights against equal, replay);
- autopilot;
- TA signals and entry odds;
- order-book research.

Sources are the `v2/*.json` documents written by `tools/*`, served by `/research/*`. The v1
sections (calibration, live accuracy, signal history) and their API (`/recommendations`,
`/metrics/*`, `/signals/history`) were removed on 2026-11-18; those URLs now answer 404.

**How a user reaches it:** the navigation, or the old `/accuracy`, `/calibration` and `/history`
URLs.

**How to drive:** for the section you changed, compare the JSON from its `/research/...` endpoint
with the text on the page, especially dates and the gate verdict.

**What usually lies:**
- Any wording that says a model "beats" equal weights. Today none passes the gate, except GBM at
  horizon 5 over the full period, which fails in the recent window. Wording beyond the report is
  a bug.
- Any v1 wording (p_win, tier A, D1/W1/M1 signals) on a page is a regression: v1 failed its
  acceptance criteria and is no longer shown.
