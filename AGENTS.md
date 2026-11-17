# Tmon: guide for coding agents

Tmon analyses the Tehran Stock Exchange and Farabourse (TSETMC) for one owner. Every day it ranks
stocks and gives a one-month verdict per symbol, and it runs portfolios with live exit alerts.
UI text is Persian. Write code, comments and commit messages in English; write docs and UI in
plain Persian.

The PC computes everything. The VPS only serves pages and watches portfolios during market hours.

## Where things are

| Path | What |
| --- | --- |
| `backend/src/tmon/` | Python 3.13 package. Its packages and the allowed import direction are in [docs/11](docs/11-architecture-and-data-model.md) |
| `backend/src/tmon/engine/verdict.py` | `final_verdict`: the **only** place a per-symbol verdict is made (pure functions; routers and portfolio advice import it) |
| `backend/src/tmon/tools/v2_ranking.py` | Daily v2 ranking: four equal-weight signals, zones, basket |
| `backend/config/engine.yaml` | Every engine threshold. Change numbers here, not in code |
| `backend/tests/` | pytest; `-m network` needs a link that reaches TSETMC |
| `frontend/` | Next.js 16, React 19. API types are generated from `frontend/openapi.json` |
| `deploy/` | `release.sh` (code to the server), `sync-data.sh` (data to the server) |
| `docs/` | Start at [docs/README.md](docs/README.md). Reports are in [docs/reports](docs/reports/README.md) |
| `.claude/skills/verify-tmon/` | How to launch, drive and prove a change in the real app, with a feature map |

## Commands

```bash
# backend (from backend/)
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
# frontend (from frontend/)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm gen:api            # after any API schema change; CI fails if openapi.json is stale
# daily cycle on the PC (Windows), then send data to the server
powershell -File backend/scripts/run_collectors.ps1 -Eod
bash deploy/sync-data.sh
```

Live data env: `TMON_DATABASE_URL=sqlite:///D:/Data/Tmon/data/tmon-live.sqlite3`,
`TMON_OBJECT_STORE=file`, `TMON_OBJECT_STORE_DIR=D:/Data/Tmon/data/objects`. Only `python.exe`
reaches TSETMC and Codal (per-app VPN split tunnel); `curl` on this machine does not. Details are in
[docs/14](docs/14-local-run.md).

## Workflow the owner expects

1. After every change: run the checks above, commit, **push**, then `bash deploy/release.sh`.
   Do not commit `frontend/components/ZoneTables.tsx` or `frontend/next-env.d.ts`, or anyone
   else's work in progress.
2. Keep Python 3.13, Node 26 and the newest package versions.
3. If behaviour changes, update the doc that describes it in the same commit. Fix the doc rather
   than adding a new one. Nothing goes into `docs/` that the code does not do.
4. Prove a user-visible change in the running app with the `verify-tmon` skill, not only with tests.

## Rules enforced by tests

Read the test before working around it. Each one fails with an explanation.

| Rule | Test |
| --- | --- |
| No new import edges between packages | `backend/tests/test_layering.py` |
| No time-based caches; server fetches use `no-store`; memoization list frozen | `backend/tests/test_no_time_cache.py` |
| Doc links and `docs/...` paths in code resolve | `backend/tests/test_docs_links.py` |
| Every glossary term has a site entry | `frontend/tests/glossary.test.ts` |
| API types match the API | CI `gen:api` diff |
| Format, lint, types | ruff, ruff format, mypy, eslint, tsc in CI |

## Rules no test can check

- **No overclaiming.** Never say a model beats equal weights, or that the ranking is a
  recommendation, unless a gate in a report shows it. Today G4 and G6 fail, so pages say «رتبه‌بندی
  مدل، توصیه نیست». Abstaining («امروز پیشنهادی نیست») is a valid answer.
- **«صبر», not «نگهداری»**, for a stock the user does not hold. Use plain sentences, and never
  write a percent of a percent.
- **Thresholds come from data.** A new number either comes from a measured study, with a report in
  `docs/reports/`, or is labelled untested in the UI and in `OPEN_QUESTIONS`.
- **Out-of-sample or nothing.** Judge every method on both halves of time with costs included.
  The data mostly covers one bull regime; say so.
- **Security.** Never print, log or commit Mofid tokens or any credential. Never place orders.
  Never type the owner's passwords or one-time codes.
- **OPEN_QUESTIONS numbers are stable.** Code cites them. Close an item in place; never renumber.
