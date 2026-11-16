# Model and accuracy (`/model`)

**What exists:** one page with these anchors:
- the live algorithm `#adapt` (champion per horizon, weights against equal, replay);
- autopilot;
- TA signals and entry odds;
- order-book research;
- live accuracy `#accuracy`, calibration `#calibration`, and signal history `#history` (v1).

Sources are the `v2/*.json` documents written by `tools/*`, served by `/research/*`,
`/metrics/*` and `/signals/history`.

**How a user reaches it:** the navigation, or the old `/accuracy`, `/calibration` and `/history`
URLs.

**How to drive:** for the section you changed, compare the JSON from its `/research/...` endpoint
with the text on the page, especially dates and the gate verdict.

**What usually lies:**
- Any wording that says a model "beats" equal weights. Today none passes the gate, except GBM at
  horizon 5 over the full period, which fails in the recent window. Wording beyond the report is
  a bug.
- v1 sections reflect a path that failed its acceptance criteria. They must not read like advice.
