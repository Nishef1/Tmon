# Portfolios and picks

**What exists:**
- `/portfolios`: create a portfolio. Its key is shown once and kept in `localStorage`; the server
  stores only the key's hash.
- `/portfolios/[id]`: the trade ledger, holdings with profit after fees and tax, advice (sell,
  replace, wait, buy with free cash), alerts with the exit question, the pre-open briefing, return
  ranges as candles for 1 week to 1 year, history against the index, and the Mofid connection.
  In the advice card, each holding with a buy date has an `inflation-badge` («جلوتر از تورم» or
  «عقب از تورم») and a reason with inflation since the buy and the gain after it; compare
  `real_pnl_pct` in `/portfolios/{id}/advice`. A holding without a buy date says to enter one.
  Each holding in the advice card has a `position` block («وضع این دارایی برای شما»): profit or
  loss in toman if sold today, the breakeven price, the stop (own or the default 10%) and the
  buyer's verdict. Check its numbers against `position` in `/portfolios/{id}/advice`.
  Buy candidates show `gap-guard` («در بازگشایی نخرید…») only during the session, when the
  symbol opened at least 0.5% above yesterday's close and still trades near the open; compare
  `guard.gap_rule` in `/instruments/{id}/entry`. Outside market hours it is absent by design.
- `/portfolios` has `owner-login` («ورود مالک»): the owner password saves every portfolio in
  this browser with an owner token. It answers 503 where `TMON_OWNER_PASSWORD_HASH` is unset (the
  PC by default). Never type the owner's password yourself; test with a password set in a test.
- `/picks`: symbols the owner is tracking live, with return since the pick.

API: `/portfolios/*` with the `X-Portfolio-Key` header (proxied by `frontend/app/api/portfolios`),
and `/picks`.

**How a user reaches it:** the navigation.

**How to drive:**
- Create a throwaway portfolio, add one buy without a price (it should use that day's close) and
  check the holding and fee. Delete it at the end.
- Never connect Mofid during verification. It opens the owner's real brokerage login. Use the
  owner's existing portfolio read-only, or a test one.
- For alerts, `python -m tmon.portfolio.monitor --once --force` runs the detectors once.

**What usually lies:**
- A holding marked «برآوردی» (estimated) is expected when price or quantity was missing.
- A Mofid line dated the sync day, or a unit count that grew after a bonus issue, is a bug: the
  line takes Mofid's period date, moved past any later share-count change. Compare
  `GET /portfolios/{id}/trades` with `last_result.items[].date` in `GET /portfolios/{id}/mofid`.
- A Mofid link that cannot sync (`stale: true` in `GET /portfolios/{id}/mofid`) must show
  `mofid-stale` («اتصال به مفید قطع است») at the top of the portfolio page with the last sync in
  Tehran time. Missing it, or showing it while `stale` is false, is a bug.
- No notification channel set: the page must say so, rather than staying silent.
- Advice says «تأییدنشده» while `recommendation_allowed` is false (today it is). Missing that
  label is a bug.
- A pick created while testing pollutes the owner's live test. Remove it.
- With no picks, /picks shows a three-step how-to (`picks-empty`) and a link to the home page.
