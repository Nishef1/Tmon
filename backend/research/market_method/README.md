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
| `income_model.py` | Same withdrawal test, but the 10 names come from the walk-forward v2 composite, the statements score, their mean and LightGBM (out of sample). Write-up: [income-model-2026-11](../../../docs/reports/income-model-2026-11.md) | `results_income_model.json` |
| `rally_cause.py` | Month-end indices, free dollar, Brent, the equal-weight index in dollars, and the 80-day closure: what moved together since the reopening. Write-up: [mega-winners-2026-11](../../../docs/reports/mega-winners-2026-11.md) | `results_rally_cause.json` |
| `mega_winners.py` | Stocks with +300% to +1000% in ~400 days: when were they bought, and which entry features (trend, high, flow, liquidity, sector) lifted the chance? Same write-up | `results_mega_winners.json` |
| `dividend_yield.py` | The "dividend-income" method from a Telegram educator (P/D 4-5, sound company, hold a year): no DPS in our data, so P/E <= 5 with a debt and profit-growth screen; 250 and 60 day holds against the same-day basket, both halves. Write-up: [dividend-yield-2026-11](../../../docs/reports/dividend-yield-2026-11.md) | `results_dividend_yield.json` |
| `dividend_pd.py` | Same method with the real dividend per share read from Codal decisions letters: P/D <= 5/4/3, payout > 60%, DPS growth > 50%, the full screen, a high-yield third, and the "floor in a correction" check; 250 and 60 day holds, both halves. Write-up: [dividend-yield-2026-11](../../../docs/reports/dividend-yield-2026-11.md) | `results_dividend_pd.json` |
| `drawdown_floor.py` | Staged buying at each stock's usual drawdown floor (median of its past episodes), steps at 0.75/1/1.15/1.3 x, with a "sound company" screen and a green-candle control; does the depth repeat? Write-up: [drawdown-floor-2026-11](../../../docs/reports/drawdown-floor-2026-11.md) | `results_drawdown_floor.json` |

Rules every script follows: both halves of time, entry at the close of the day after the signal,
excess return over the mean of the same universe, round trip cost 1.75% where a return is quoted.
The statements come from `python -m tmon.ingest.tsetmc.cli statements` and only reach back as far as
TSETMC lists them (the newest 15 filings per symbol), so the fundamentals study has few events.
