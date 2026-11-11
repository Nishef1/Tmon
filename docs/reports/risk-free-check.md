# Risk-free rate from treasury bills (اخزا): data check

Generated 2026-11-11 from live TSETMC data (`tmon.ingest.tsetmc.cli risk-free`). Method: ADR 0002 §6. Each day the listed bill whose remaining life is nearest to 365 days (and at least 30 days) gives the effective annual yield `(face / price)^(365/days) − 1` from its final price (`<CLOSE>`), stored in `macro_series` as `rf_1y_ytm`, source `tsetmc:treasury-bills`, with `source_url`, `fetched_at` and the chosen bill and days left in `meta`.

## What was verified

| Fact | Evidence |
| --- | --- |
| Maturity date of each bill | The Jalali `yymmdd` suffix of the Persian name and the Gregorian `TreasuryBillYYMMDD` ticker in the price export agree for all 18 bills (0 disagreements, table below). |
| Face value = 1,000,000 rial | The feed does not publish it. It is derived from data: the reference price on the first trading day of 16 of 18 bills is exactly 1,000,000, and the five bills with 27 to 83 days left all price at the same simple annual yield (31.8% to 32.4%) under that face value, which a wrong face value would not produce. Configured in `config/engine.yaml` (`benchmarks.treasury_bill_face_value`); owner may confirm against the Treasury / SEO prospectus (OPEN_QUESTIONS). |
| Prices | `<CLOSE>` (final price), days with no trades are skipped. |

| symbol | maturity (Jalali name) | Latin ticker | agree | first-day reference price | last close | days left | simple yield p.a. |
|---|---|---|---|---|---|---|---|
| اخزا202 | 2026-12-14 | TreasuryBill261214 | yes | 1000000.00 | 970,940 | 34 | 32.1% |
| اخزا204 | 2027-01-11 | TreasuryBill270111 | yes | 1000000.00 | 948,350 | 62 | 32.1% |
| اخزا210 | 2027-02-01 | TreasuryBill270201 | yes | 1000000.00 | 931,430 | 83 | 32.4% |
| اخزا212 | 2026-12-07 | TreasuryBill261207 | yes | 1000000.00 | 977,040 | 27 | 31.8% |
| اخزا213 | 2027-01-11 | TreasuryBill270111 | yes | 1000000.00 | 948,070 | 62 | 32.2% |
| اخزا301 | 2027-09-06 | TreasuryBill270906 | yes | 1000000.00 | 751,670 | 300 | 40.2% |
| اخزا401 | 2028-08-28 | TreasuryBill280828 | yes | 1000000.00 | 520,150 | 657 | 51.3% |
| اخزا402 | 2028-09-04 | TreasuryBill280904 | yes | 1000000.00 | 529,920 | 664 | 48.8% |
| اخزا403 | 2028-10-09 | TreasuryBill281009 | yes | 1000000.00 | 514,890 | 699 | 49.2% |
| اخزا404 | 2028-11-06 | TreasuryBill281106 | yes | 426800.00 | 498,180 | 727 | 50.6% |
| اخزا405 | 2028-07-10 | TreasuryBill280710 | yes | 1000000.00 | 554,770 | 608 | 48.2% |
| اخزا406 | 2029-01-08 | TreasuryBill290108 | yes | 1000000.00 | 455,980 | 790 | 55.1% |
| اخزا407 | 2029-01-29 | TreasuryBill290129 | yes | 1000000.00 | 444,480 | 811 | 56.2% |
| اخزا501 | 2029-05-14 | TreasuryBill290514 | yes | 1000000.00 | 399,480 | 916 | 59.9% |
| اخزا5012 | 2029-05-14 | TreasuryBill290514 | yes | 1000000.00 | 399,700 | 916 | 59.8% |
| اخزا502 | 2029-05-28 | TreasuryBill290528 | yes | 1000000.00 | 393,140 | 930 | 60.6% |
| اخزا504 | 2029-07-30 | TreasuryBill290730 | yes | 1000000.00 | 369,050 | 993 | 62.8% |
| اخزا5042 | 2029-07-30 | TreasuryBill290730 | yes | 355740.00 | 368,420 | 993 | 63.0% |

The two bills whose first row is not 1,000,000 (اخزا404, اخزا5042) are series whose earliest stored row is not the listing day; they do not affect the face-value inference.

## The series

690 daily values, 2023-12-09 to 2026-11-10.

| Year | Days | Min | Median | Max |
| --- | --- | --- | --- | --- |
| 2023 | 16 | 26.9% | 27.2% | 27.5% |
| 2024 | 238 | 27.5% | 31.5% | 37.0% |
| 2025 | 237 | 33.0% | 34.9% | 37.7% |
| 2026 | 199 | 34.9% | 39.3% | 44.0% |

Latest value 2026-11-10: 41.5% (bill اخزا301, 300 days left).

## Limits (read before using the series)

- **Only bills still listed can be read.** Matured bills drop out of TSETMC's watch, so before roughly 2026 the nearest-to-one-year bill is often a longer one (the first value, 2023-12-09, comes from a bill with 1,101 days left). Early values therefore describe a 3-year yield, not a 1-year yield; the chosen bill and days left are in each row's `meta`. A true 1-year series needs the history of matured bills from another source (owner decision, OPEN_QUESTIONS).
- No value exists before 2023-12-09; reports that need a rate earlier than that print "not available" and Sharpe uses 0 for those days.
- Thin trading: a bill can have few trades on a given day; the closest-to-365-days bill is chosen first, the one with the largest volume breaks ties.
