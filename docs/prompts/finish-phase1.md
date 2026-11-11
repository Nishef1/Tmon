# پرامپت تکمیل فاز ۱ (رساندن به ۱۰۰٪) برای Claude Code

متن زیر را کامل به Claude Code بدهید (داخل همین ریپو، روی سیستمی که به tsetmc.com و codal.ir دسترسی دارد و Docker دارد).

---

You are finishing phase 1 of **Tmon**. M0–M5 are built and green (158 backend tests, 25 Vitest, 24 Playwright; CI green). One real run on 150 instruments produced "no recommendation today". Your job is to take phase 1 to 100% as defined in `docs/adr/0002-engine-and-data-decisions.md` §7 — nothing more.

## Read first

`docs/adr/0001-tech-stack.md`, `docs/adr/0002-engine-and-data-decisions.md` (new, binding), `docs/10-recommendation-engine.md`, `docs/12-roadmap.md`, `docs/OPEN_QUESTIONS.md`, `docs/CHANGELOG.md`. ADR 0002 overrides docs/10 where they differ; update docs/10 to match it in your first commit.

## Stay on track (hard rules)

- Work **only** on the tasks below, in order. Do not start a task until the previous one meets its acceptance check, unless it is blocked on the owner (then record it and move on).
- No dependency upgrades, no new frameworks, no refactors, no UI redesign, no phase-2 work, no new docs files except reports in `docs/reports/`. Update only `CHANGELOG.md` (short) and `OPEN_QUESTIONS.md` (close items with a link to evidence).
- Never invent numbers, endpoints, fees or results. If a fact cannot be verified, stop that sub-step, add it to `OPEN_QUESTIONS.md` as **"owner decision needed"**, and continue with the next independent item.
- Keep the root of the repo free of any product description. Docs stay in `docs/`.
- Every task ends with: tests green (`ruff`, `ruff format --check`, `mypy src`, `pytest`, `pnpm lint typecheck test`), one focused commit, CHANGELOG line.
- A model that does not beat the baseline is an acceptable outcome. A hidden or flattering result is not.

## Tasks (in this order)

**T1 — Complete real data.**
1. Full backfill of every instrument in the ADR 0002 §1 universe plus excluded fund types (needed for the comparison page), since 2021-01-01. Must be resumable.
2. Ingest TEDPIX (شاخص کل) and the official equal-weight index daily history.
3. Compute daily 1-year YTM from اخزا prices; store in `macro_series` with source.
4. During market hours, run `probe` cross-check of market-watch columns vs history; fix the mapping if it disagrees (closes OPEN_QUESTIONS 49).
5. Verify price adjustment for 20 named liquid symbols against TSETMC's own adjusted series; write the comparison table to `docs/reports/adjustment-check.md`.
Acceptance: row counts per type in CHANGELOG; adjustment max error ≤ 0.5% on all 20 or each exception explained.

**T2 — Verified costs.** Find the official commission and sell-tax schedule (SEO directive or a licensed broker's fee table), record values with URL and date in `market_rules` with `verified: true`. Slippage per ADR 0002 §2. If no official source is reachable: owner decision needed, keep `verified: false`, continue.

**T3 — Engine per ADR 0002.** Universe filter (§1), breakeven-based thresholds and tiers (§3), nested barrier grid (§4), split calibration (§5), real benchmarks and risk-free rate (§6). Add unit tests for: breakeven formula, threshold selection, grid selection never touching the test fold, calibration split.

**T4 — Real reports.** Run the walk-forward backtest for baseline and LightGBM D1 on real data. Commit `docs/reports/m3-baseline-d1-real.md` and `docs/reports/m4-lgbm-d1-real.md`: net metrics, per-regime results, reliability table, all grid combos tried, comparison to baseline, TEDPIX, equal-weight index and the اخزا rate. State plainly whether Tier A opens.

**T5 — Production path.** `docker compose up` on this machine: all services healthy, migrations applied, Celery beat runs EOD ingest → features → publish → outcome resolution on schedule (Tehran time, from `market_rules` trading calendar). Add a runbook section to `docs/14-local-run.md` (replace its outdated "not verified" notes). Acceptance: one full scheduled cycle observed in logs.

**T6 — M6: fundamentals and W1/M1.** Codal ingestion (statements with versions, monthly activity, AGM/capital-increase events), ratios per `docs/03`, AGM decision formula per `docs/05`, then W1 and M1 models using the same engine and ADR 0002 rules. Real reports for W1 and M1.

**T7 — M7: macro, funds, comparison.** Inflation series (SCI and CBI, by `release_date`), free-market USD and gold, fund NAV/bubble per `docs/06`, commodity certificates and futures basis per `docs/07`, and the "comparison with inflation" page. News pipeline per `docs/08` with the LLM step behind an env var (`TMON_LLM_API_KEY`); without the key the step is skipped and the rest still runs. Ablation report: does each feature group improve out-of-sample metrics? Drop groups that do not.

**T8 — M8: academy and monitoring.** Every glossary term from `docs/glossary.md` reachable in the UI; live accuracy dashboard; Brier drift kill switch per `docs/10 §9`; defensive mode per §10.

## Finish

When T1–T8 pass, update the status table at the top of `docs/12-roadmap.md` with evidence links for every milestone, list remaining owner decisions in OPEN_QUESTIONS, and stop.
