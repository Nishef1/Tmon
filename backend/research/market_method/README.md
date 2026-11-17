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
| `fundamental_model.py` | Walk-forward: do the statements, added to the four v2 signals (simple mean or LightGBM), improve the top 10 over 20 days? Write-up: [fundamental-model-2026-11](../../../docs/reports/fundamental-model-2026-11.md) | `results_model.json`, `today_ranking.json` |
| `small_target.py` | Buy a dip signal, sell a limit at +3% (stop −5%, 10 days): is it a profit after the 1.75% cost? Write-up: [small-target-2026-11](../../../docs/reports/small-target-2026-11.md) | `results_small_target.json` |
| `regime_plan.py [start_year]` | Market trend filter, staged entry, rank-based selection and switching, and the pieces together (default start 2009). Write-up: [regime-plan-2026-11](../../../docs/reports/regime-plan-2026-11.md) | `results_regime_plan_2009.json`, `results_regime_plan_2001.json` |
| `income_3y.py` | 100 million in an equal-weight basket of the 10 or 20 most liquid names, a fixed monthly withdrawal, last three years only: how long does the capital last? Write-up: [income-3y-2026-11](../../../docs/reports/income-3y-2026-11.md) | `results_income_3y.json` |

Rules every script follows: both halves of time, entry at the close of the day after the signal,
excess return over the mean of the same universe, round trip cost 1.75% where a return is quoted.
The statements come from `python -m tmon.ingest.tsetmc.cli statements` and only reach back as far as
TSETMC lists them (the newest 15 filings per symbol), so the fundamentals study has few events.
