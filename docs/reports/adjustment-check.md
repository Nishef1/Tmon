# Price adjustment check against TSETMC's own adjusted series

Generated 2026-11-11 by `tmon.ingest.tsetmc.cli adjustment-check`. Reference: `Financial.aspx?t=ph&a=1` (adjusted, integer-rounded) vs our adjusted final price derived from the raw bars (`features/adjustment.py`, reference-price gaps).

Acceptance: max error ≤ 0.5% on every symbol. The source rounds prices to whole rials, so a row whose adjusted price is below 200 can differ by up to that rounding alone; the column "max error, price ≥ 200" excludes those rows and decides the verdict, the column "max error" shows everything.

| symbol | days compared | adjustment events (ours) | max error | on | max error, price ≥ 200 | median error | verdict |
|---|---|---|---|---|---|---|---|
| فملی | 1069 | 9 | 0.043% | 2022-09-24 | 0.043% | 0.008% | ok |
| فولاد | 1049 | 8 | 0.056% | 2022-10-26 | 0.056% | 0.012% | ok |
| وبملت | 1091 | 9 | 0.325% | 2022-01-18 | 0.234% | 0.051% | ok |
| فزر | 1028 | 6 | 0.007% | 2022-02-12 | 0.007% | 0.001% | ok |
| وتجارت | 1088 | 8 | 0.302% | 2022-10-24 | 0.245% | 0.073% | ok |
| شستا | 1077 | 6 | 0.113% | 2021-12-20 | 0.113% | 0.027% | ok |
| خودرو | 1026 | 1 | 0.225% | 2022-10-31 | 0.225% | 0.049% | ok |
| تاصیکو | 1102 | 7 | 0.030% | 2022-01-25 | 0.030% | 0.004% | ok |
| ومعادن | 1089 | 9 | 0.043% | 2021-12-11 | 0.043% | 0.015% | ok |
| ساحل | 986 | 1 | 0.251% | 2024-05-26 | 0.251% | 0.169% | ok |
| تاپیکو | 1104 | 5 | 0.009% | 2022-02-27 | 0.009% | 0.002% | ok |
| ستاره | 438 | 0 | 0.153% | 2025-01-21 | 0.153% | 0.147% | ok |
| شپدیس | 1056 | 7 | 0.028% | 2022-02-13 | 0.028% | 0.006% | ok |
| خساپا | 1043 | 1 | 0.251% | 2022-01-03 | 0.238% | 0.056% | ok |
| وبصادر | 1058 | 6 | 0.161% | 2022-10-31 | 0.161% | 0.035% | ok |
| کگل | 1046 | 13 | 0.035% | 2025-10-01 | 0.035% | 0.010% | ok |
| ذوب | 1072 | 3 | 0.236% | 2022-10-16 | 0.236% | 0.000% | ok |
| وغدیر | 1087 | 6 | 0.020% | 2022-02-09 | 0.020% | 0.004% | ok |
| ونوین | 1090 | 8 | 0.212% | 2022-10-29 | 0.212% | 0.035% | ok |
| صبا | 622 | 3 | 0.024% | 2024-08-26 | 0.024% | 0.008% | ok |

Symbols ok: 20, exceptions: 0, missing: 0.
