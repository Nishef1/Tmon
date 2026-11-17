# market_method

Tests of the rules taught by one Telegram/YouTube educator (Rose group), done on our own data. The
write-up and the numbers are in [docs/reports/market-method-2026-11.md](../../../docs/reports/market-method-2026-11.md).

Run each script from `backend/` with the live data env (see AGENTS.md). Nothing here is imported by
the app.

| Script | Question | Output |
| --- | --- | --- |
| `study.py` | Does a record of traded value plus real-money outflow mark a market top? Does a dollar-priced index help? | `results.json` |
| `stock_study.py` | Does the biggest stock of a sector, the sectors with the best 60-day return, or a stock near its own dollar high keep winning? | `results_stock.json` |
| `fundamentals_study.py` | Do cheap P/E, growth, margin expansion and low leverage (from the filed statements) predict the next 20 and 60 days? | `results_fundamentals.json`, `symbols_latest.csv` |

Rules every script follows: both halves of time, entry at the close of the day after the signal,
excess return over the mean of the same universe, round trip cost 1.75% where a return is quoted.
The statements come from `python -m tmon.ingest.tsetmc.cli statements` and only reach back as far as
TSETMC lists them (the newest 15 filings per symbol), so the fundamentals study has few events.
