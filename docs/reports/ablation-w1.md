# Feature-group ablation, W1 (T7)

Command: `python -m tmon.backtest.ablation --timeframe W1 --json docs/reports/ablation-w1.json`
on the live database (raw output: [ablation-w1.json](ablation-w1.json)). Each variant is the
LightGBM engine trained on a different column list with the same 45 walk-forward folds, labels and
round-trip cost (1.75%). Thresholds were not enforced, so every variant trades its top picks and the
trade numbers are comparable. Probabilistic numbers are over all 311,595 scored rows (base rate 17.2%).

| Variant | Features | AUC | Brier skill | Trades | Win rate | Net expectancy | Total return | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full (W1 v1) | 73 | 0.596 | −0.033 | 2,112 | 46.3% | +0.70% | +60.5% | −31.1% |
| minus_board | 61 | 0.563 | −0.061 | 1,931 | 40.5% | −0.56% | −15.8% | −54.0% |
| **minus_market** | 62 | **0.646** | **+0.021** | 2,271 | **52.0%** | **+1.75%** | **+235%** | **−25.5%** |
| plus_macro | 79 | 0.571 | −0.047 | 2,256 | 42.6% | +0.08% | +4.0% | −45.7% |

## Reading

- **Board group (client flows, queues, relative volume): keep.** Removing it lowers every metric
  and turns net expectancy negative.
- **Market group (index returns, breadth, market flows, relative-to-market): drop.** Without it
  AUC rises by 0.05 and Brier skill turns positive. Market-wide columns are the same for every
  symbol on a day, so the trees seem to learn regimes from past folds that do not carry forward.
  W1 now uses feature set `W1 v2` (technical and board) in `features/builder.py`.
- **Macro group (free-market USD and 18k gold, change over 5/20/60 releases, joined by
  `release_date`): do not add.** Coverage was 99.7% of rows, so missing data is not the cause.
- **News group: not testable.** The news pipeline has only run since 2026-11 and there is no
  history to build features from (OPEN_QUESTIONS 82).
- **Fundamental group:** already rejected for lack of report coverage (C4 step 5, OPEN_QUESTIONS 77).

## Limits

- This is one run with one seed. The variant was chosen by looking at the same out-of-sample window,
  so the minus_market numbers are optimistic. Brier skill of +0.021 is small.
- The portfolio Sharpe is negative for every variant except minus_market (+0.12) even where total
  return is positive. Sharpe is measured against the treasury yield, and a risk-free rate above 20%
  a year is hard to beat. None of these numbers clears the publish thresholds on its own.
- Only W1 was ablated. D1 and M1 keep their v1 sets until the same run is done for them.
- `m4-lgbm-w1-real.md` was produced with W1 v1. The live W1 model must be retrained before new W1
  signals use v2 (the training cycle does this on its next run).
