# پرامپت ادامهٔ فاز ۱ برای Claude Code (پس از بازبینی ۲۰ آبان ۱۴۰۵)

متن زیر را کامل به Claude Code بدهید، روی سیستم خودتان (دسترسی به tsetmc.com و codal.ir).

---

You are continuing phase 1 of **Tmon**. `docs/prompts/finish-phase1.md` is still the binding task list and rule set; this prompt only tells you where things stand now and what to do next, in order. ADR 0001 and ADR 0002 remain binding.

## Before anything

1. `git remote set-url origin https://github.com/Nishef1/Tmon.git`, then `git fetch origin` and `git checkout main && git pull`.
2. Windows: use `backend/.venv/Scripts/python.exe` or `python -m uv`; no bash heredocs.
3. Run `uv sync` and `pnpm install` first: the dependencies changed (see below).

## What changed since your last commit (`70bbd3b`)

A review session made these commits on `main`. Read their diffs before you start; they are not to be reverted.

- `e369e32`: the HTTP retry loop in `ingest/http.py` now uses **tenacity** and honours `Retry-After`. Brier scores now come from `sklearn.metrics.brier_score_loss`.
- `407e57c`: `tests/test_indicators_talib.py` cross-checks every indicator against **TA-Lib**, which is a dev-only dependency. All 17 checks match within rtol 1e-6, so **do not rewrite the Polars indicators**; TA-Lib must never become a runtime dependency.
- `3bebe77`: the frontend API types are now **generated** from the backend's OpenAPI schema with `openapi-typescript`:
  - `backend/scripts/export_openapi.py` writes `frontend/openapi.json`.
  - `pnpm gen:api` writes `frontend/lib/api-schema.ts`.
  - CI fails if either generated file is stale.
  - After any change to `api/schemas.py`, run both commands and commit the results.
  - Response models inherit `ApiModel`, which marks fields that have defaults as required in the schema.

One more branch exists: **`wip/w1-m1-timeframes`** (`76ebbdf`), which is unfinished. It contains:
- W1 and M1 feature sets (v1 uses price and money-flow features only; M1 drops same-day board columns).
- `publish_timeframes: [D1, W1, M1]` in `engine.yaml`.
- One publish step per timeframe in `tasks/cycle.py`; D1 is required and W1/M1 are optional.
- API support for W1 and M1.
- Updated tests.

On that branch, 206 backend tests passed. The new end-to-end test `test_weekly_and_monthly_models_train_and_publish_on_their_own_horizon` was **not** run to completion.

## Tasks, in order

**C1 — Finish and merge the W1/M1 branch.**
1. Check out `wip/w1-m1-timeframes`, rebase it on `main`, and regenerate `openapi.json` and `api-schema.ts`.
2. Run the new end-to-end test. If it is too slow (more than about 3 minutes), shrink the synthetic market (fewer instruments, not fewer days) rather than weakening the asserts.
3. Make the timeframe selector in the UI show all three timeframes. W1 and M1 must show the same honest "no recommendation" state as D1 when nothing passes.
4. Run all checks (`ruff`, `ruff format --check`, `mypy src`, `pytest`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, Playwright), then merge into `main` and delete the branch.

**C2 — T4 real reports, now for all three timeframes.** On real data after the full backfill, write:
- `docs/reports/m3-baseline-d1-real.md`
- `docs/reports/m4-lgbm-d1-real.md`
- `docs/reports/m4-lgbm-w1-real.md`
- `docs/reports/m4-lgbm-m1-real.md`

Each report must use the content rules in finish-phase1 T4 and state plainly whether Tier A opens.

**C3 — T5 production path.** Follow finish-phase1 T5 unchanged. Its runbook must now describe three publish steps.

**C4 — T6 Codal, evidence first.** Do not write statement parsers from guesses. Work in this order:
1. A Codal letter-index client (search API) that stores the raw JSON, with tests built on **real responses** you capture into `backend/tests/fixtures/codal/`.
2. Extract AGM and capital-increase events from that index into `corporate_events`.
3. Implement the AGM hold-or-sell formula from `docs/05` as a pure, tested function, and show it on the instrument page.
4. Capture real samples of monthly-activity and financial-statement reports, then parse them into versioned rows. Record each format variant you find in OPEN_QUESTIONS.
5. Only then add fundamental columns as **v2** feature sets for W1 and M1. Keep a new set only if the ablation in the real report shows it helps.

**C5 — T7 and T8,** as in finish-phase1, with these library choices:
- Use `hazm` for Persian text normalization (add it only when the news step is built).
- The news LLM step stays behind `TMON_LLM_API_KEY`.
- The comparison page must read from `macro_series`. When an official inflation source is unreachable, a CSV import path, with the source URL and release date stored for each row, is acceptable.

**C6 — Doc hygiene** (one commit at the end):
- In `docs/OPEN_QUESTIONS.md`, strike through every item the CHANGELOG says is closed and link the evidence. At minimum these are items 4, 5, 13, 17, 22–24 and 31–34, plus any that W1/M1 close.
- Remove the outdated "not verified" notes from `docs/14-local-run.md`.
- Update the status table in `docs/12-roadmap.md`.

## Rules (unchanged, repeated because they matter)

- Work only on C1–C6, in order. No dependency upgrades or refactors beyond what a task needs, no UI redesign, no phase-2 work.
- Never invent numbers, endpoints, formats or results. Anything unverifiable goes into OPEN_QUESTIONS as "owner decision needed", and you move to the next independent item.
- Every task ends with all checks green, one focused commit with a CHANGELOG line, and a push to `main`.
- Keep the repository root free of any product description.
- A model that does not beat the baseline is an acceptable outcome; a flattering report is not.
