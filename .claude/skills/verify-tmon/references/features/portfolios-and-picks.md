# Portfolios and picks

**What exists:**
- `/portfolios`: create a portfolio. Its key is shown once and kept in `localStorage`; the server
  stores only the key's hash.
- `/portfolios/[id]`: the trade ledger, holdings with profit after fees and tax, advice (sell,
  replace, wait, buy with free cash), alerts with the exit question, the pre-open briefing, return
  ranges as candles for 1 week to 1 year, history against the index, and the Mofid connection.
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
