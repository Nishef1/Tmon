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
- No notification channel set: the page must say so, rather than staying silent.
- Advice says «تأییدنشده» while `recommendation_allowed` is false (today it is). Missing that
  label is a bug.
- A pick created while testing pollutes the owner's live test. Remove it.
- With no picks, /picks shows a three-step how-to (`picks-empty`) and a link to the home page.
