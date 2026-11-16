---
name: verify-tmon
description: Launch Tmon (FastAPI + Next.js) on this PC against live or demo data, drive the changed pages in the built-in browser, and prove the change with what the page shows. Use after any change a user could see (API response, verdict, ranking, page, portfolio), and whenever asked to "check it in the app". Tests passing is not proof.
---

# Verify Tmon

Tests prove the code does what the test says. This skill proves the page says what the user
should see. Follow the five steps in order.

## 1. Launch

Use the configs in `.claude/launch.json` with `preview_start`. Never start servers with Bash.

| Need | Start |
| --- | --- |
| Real data (default) | `tmon-api-live` (API on 8000, `data/tmon-live.sqlite3` and `data/objects`), then `tmon-web-dev` (web on 3000) |
| No network, synthetic | `tmon-api-demo` then `tmon-web-dev`. Symbols are «نمونه N» and thresholds are loosened in `demo_db.py`, so no number means anything |
| Production-like build | `tmon-web` (`next start`) needs a fresh `pnpm build` first |

The web finds the API through `API_URL` or `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## 2. Doctor

Check these before judging any page. A wrong answer here explains most "bugs".

- `GET http://127.0.0.1:8000/health` answers.
- `GET /freshness` and `GET /data-health`: what day the data is from, and whether today is
  partial. A partial day makes the ranking look wrong while the code is fine.
- `GET /v2/ranking`: `as_of` matches the newest price day. If it is older, the cycle step
  `tmon.tools.v2_ranking` has not run, so this is not a page bug.
- The browser console on the first page has no errors (`read_console_messages`).

## 3. Drive

Open [references/features/README.md](references/features/README.md), find every feature area the
change touches, and follow that file. Read text with `get_page_text` or `find` rather than from
screenshots. Use the **real symbol the change is about**, not whatever is first in the list.

## 4. Prove

Give the user the evidence: the page, the exact text or number before and after, and one
screenshot of the changed area. If the change is in the API, add the JSON field and value too.
Check both a held symbol and an unheld one when the change touches verdict wording.

## 5. Clean up

Stop the servers you started (`preview_stop`), reset any viewport you changed, and delete any test
portfolio or pick you created. Never leave a pick created by testing in `/picks`.

## What usually lies

- **Wording:** an unheld stock showing «نگهداری» instead of «صبر», or a fund showing a verdict.
  Both are bugs.
- **Stale UI:** Next.js serves a cached page when a server `fetch` lacks `cache: "no-store"`.
  `test_no_time_cache.py` guards this. If a page looks stale anyway, reload once and compare the
  JSON before blaming the data.
- **Demo vs live:** a number that looks great on the demo database proves nothing.
- **Server vs PC:** the server has only the last 60 days of `features` and no snapshots. A study
  page that works on the PC can be empty there. That is expected (docs/15).
