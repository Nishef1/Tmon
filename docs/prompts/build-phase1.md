# پرامپت نهایی برای Claude Code — ساخت فاز ۱ (M0 تا M5)

متن زیر را کامل به Claude Code بدهید (داخل همین ریپو اجرا شود).

---

You are building **Tmon**, a private analysis platform for the Tehran Stock Exchange (TSE) and Iran Fara Bourse. Its single current goal: for a user-selected timeframe (D1 = 1–3 trading days, W1 = 5–10, M1 = 20–60), output a ranked list of instruments to buy with the highest expected net return at the highest *calibrated* probability of success — or explicitly output "no recommendation today" when nothing passes the thresholds.

## Read first (source of truth)

Read every file in `docs/` before writing code, in this order: `docs/README.md`, `00-overview.md`, `adr/0001-tech-stack.md`, `10-recommendation-engine.md`, `11-architecture-and-data-model.md`, `12-roadmap.md`, then the rest. The docs are in Persian; formulas and column names are in English. If code and docs disagree, the docs win. If the docs are ambiguous or wrong, stop and write the question in `docs/OPEN_QUESTIONS.md` instead of guessing silently.

## Hard constraints

1. **Do not describe the product anywhere in the repository root.** No root `README.md` explaining what this is (the repo is currently public). If a root README is unavoidable for tooling, it must contain only the single word `Tmon`. All documentation goes in `docs/`.
2. **Tech stack is fixed by `docs/adr/0001-tech-stack.md`**: Python 3.12 + uv, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, Polars, LightGBM, scikit-learn, SHAP, Celery + Redis, httpx, PostgreSQL 16 + TimescaleDB, MinIO, Next.js (App Router) + TypeScript + Tailwind + `lightweight-charts`, pnpm, pytest, Vitest, Playwright, ruff, mypy, Docker Compose, GitHub Actions. Do not add or swap major components without a new ADR in `docs/adr/`.
3. **Repository layout is fixed** by `docs/11-architecture-and-data-model.md`.
4. **No market rule is hard-coded** (price limits, trading hours, base volume, fees, tax, thresholds). Rules live in the `market_rules` table with validity dates; engine parameters live in `backend/config/engine.yaml`.
5. **Point-in-time correctness is mandatory.** Every feature at date `t` uses only data published by end of `t` (`published_at`, `release_date`, `fetched_at`). Write a dedicated test that fails on look-ahead leakage.
6. **Prices must be adjusted** for dividends and capital increases before any indicator is computed. Market-halt periods (e.g. 1404-12-09 to 1405-02-29) are flagged, not forward-filled, and excluded from training.
7. **No row-wise Python loops over market data**; use vectorized Polars/NumPy.
8. **Data ingestion etiquette:** per-domain rate limiting, exponential backoff, raw payload stored in MinIO before parsing, `source_url` and `fetched_at` on every record. The TSETMC and Codal endpoints in the docs come from general knowledge — verify each one against the live site with an integration test (marked `@pytest.mark.network`, skipped in CI) before relying on it. Libraries `pytse-client` and `finpy-tse` may be read as references for endpoint shapes.
9. **Time:** store UTC; display Asia/Tehran and Jalali dates (`jdatetime`).
10. **UI:** Persian, RTL, mobile-first, font Vazirmatn. Every number shown links to its glossary entry (`docs/glossary.md`). Show the disclaimer "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست" on every recommendation page. Never display promised or guaranteed returns.
11. Never commit secrets; use `.env.example`.

## Scope for this run: milestones M0 → M5 from `docs/12-roadmap.md`

- **M0** skeleton, Docker Compose (postgres+timescale, redis, minio, backend, worker, beat, frontend), CI (ruff, mypy, pytest, eslint, vitest).
- **M1** TSETMC ingestion: instrument list, ≥5 years daily history, client types (real/legal), adjustment events; trading calendar; seed `market_rules` with the values in `docs/01-market-structure-and-rules.md`.
- **M2** technical and order-book features exactly as specified in `docs/04-technical-and-orderbook.md`, each with a unit test against a reference value.
- **M3** triple-barrier labeling and walk-forward backtester with purging + embargo and full transaction costs, queue-aware execution (cannot buy into a buy queue or sell into a sell queue); rule-based D1 baseline; HTML backtest report.
- **M4** LightGBM D1 model + isotonic calibration, EV ranking, thresholds, confidence tiers, position sizing and correlation filter, SHAP top reasons, per `docs/10-recommendation-engine.md`. Models are versioned in `model_runs`; every signal stores `model_version` and `data_snapshot_id`.
- **M5** FastAPI endpoints (`/recommendations?timeframe=D1&date=`, `/instruments/{id}`, `/signals/history`, `/metrics/calibration`) and Next.js pages: today's recommendations with timeframe selector, instrument page with chart, signal history with realized outcome, calibration/accuracy page.

W1/M1 models, Codal fundamentals, news, funds and commodities (M6+) are **out of scope** for this run, but design interfaces so they plug in without refactoring (feature sets are versioned and composable per timeframe).

## Definition of done for each milestone

- Code, tests and migrations committed with a clear message, one milestone per commit series.
- All CI checks green.
- `docs/CHANGELOG.md` updated (Persian, short) with what was built and any deviation.
- For M3/M4: commit the backtest report summary (metrics table only, no raw data) to `docs/reports/`, comparing the model to the baseline, equal-weight index buy-and-hold, and the fixed-income fund rate. Report results by regime. If the model does not beat the baseline out-of-sample after costs, say so plainly and do not ship tier A signals.

## Working style

Plan before each milestone, then implement in small verified steps. Run the tests you write. Prefer simple, readable code over cleverness. Do not invent data, endpoints or results; when something cannot be verified, record it in `docs/OPEN_QUESTIONS.md`.
