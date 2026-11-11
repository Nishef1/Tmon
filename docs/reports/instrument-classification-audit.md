# Instrument classification and price-data audit (C2)

Generated 2026-11-11 from the full TSETMC backfill (3,768 instruments, stored GetInstrumentInfo payloads for 3,227 of them). This audit came out of the first real D1 backtest, whose results were not usable until both defects below were fixed.

## 1. Misclassified instruments in the recommendation universe

The keyword classifier (group title and name, `config/instrument_types.yaml`) let non-equity instruments into the ADR 0002 universe. Fund names rarely say "درآمد ثابت" or "کالا", and the `etf_equity` catch-all ("صندوق") took the rest. Options, rights ("ح." prefix), forward contracts and housing-facility certificates fell to the default `stock`.

**Fix.** TSETMC's own type code, `yVal` in GetInstrumentInfo, now decides the type. The mapping was read off the stored payloads (names and group titles per code; script output kept with the session, not in the repo):

| `yVal` | What the names show | Type |
| --- | --- | --- |
| 300, 303, 309 | Exchange, Fara Bourse and Fara Bourse base-market shares | `stock` |
| 313 | Fara Bourse نوآفرین market (group titles "بازار نوآفرین - رشد" / "دانش بنیان") | `stock`, excluded from the universe by group title (owner decision, OPEN_QUESTIONS 62) |
| 305 | All exchange-traded funds | subtype from `faraDesc`, then the name (below) |
| 380 | Commodity and gold funds (e.g. "صندوق طلای عیار مفید") | `etf_commodity` |
| 315 | Project and commodity-based funds | `other` |
| 306, 206 | Treasury bills, sukuk, murabaha; گام paper | `bond` |
| 307 | Housing-facility rights ("امتیاز تسهیلات مسکن") | `other` |
| 308, 200 | Forward (salaf) contracts | `other` |
| 201 | Capacity certificates | `other` |
| 311, 320 / 312, 321 | Call / put options | `option_call` / `option_put` |
| 400, 403, 404 | Subscription rights | `right` |
| 701 | Commodity-exchange certificates | `commodity_certificate` |
| 801–804 | Energy exchange | `other` |

Fund subtype (`yVal` 305). The `faraDesc` text has the form "نوع صندوق : …", and it was seen in these variants: "در اوراق بهادار با درآمد ثابت" (also misspelled "اوارق"), "سهامی", "سهامي", "سهامی شاخصی", "سهامی بخشی در صنعت …", "در سهام-با ساختار قابل معامله", "سهامی اهرمی", "مختلط", "املاک و مستغلات", "جسورانه", "خصوصی" and "صندوق در صندوق". 47 funds have an empty `faraDesc`. For those, the name decides: "درآمد ثابت" / "درآمدثابت", "بخشی", "املاک", then the unit suffix "-د" (fixed income) or "-س" / "-ب" (equity). A fund nothing matches becomes `other` with tag `unclassified`; none did in this backfill. Real-estate, venture, private and fund-of-fund units are `other`. None of them is in ADR 0002's universe.

`other` is a new `instrument_type` value. It is neither tradable nor recommendable.

**Effect on the live DB** (`tmon.ingest.tsetmc.cli reclassify`, 798 instruments changed). Liquid bars are days with traded value of at least 20 bn rial.

| From → to | Instruments | Liquid bars |
| --- | ---: | ---: |
| etf_equity → etf_fixed_income | 104 | 51,600 |
| etf_equity → etf_commodity | 64 | 20,204 |
| etf_equity → other | 12 | 2,668 |
| etf_equity → etf_mixed | 3 | 638 |
| etf_equity → stock (وصندوق, a listed company) | 1 | 929 |
| stock → option_call / option_put | 413 | 1,426 |
| stock → other (salaf, تسه, project funds) | 106 | 3,117 |
| stock → bond | 63 | 3,138 |
| stock → commodity_certificate | 10 | 953 |
| stock → etf_fixed_income | 9 | 1,965 |
| stock → right | 10 | 188 |
| stock → etf_equity | 2 | 450 |
| bond → other (capacity certificate) | 1 | 433 |

About 80,000 liquid bars of fixed-income and commodity funds had been in the universe. Their barriers sit inside the round-trip cost: the median TP distance of the old `etf_equity` group was 0.6% against a 1.75% cost. They inflated the TP-hit rate and taught the model to pick near-cash instruments.

Options were already out of the universe through the derivatives board, so their move changes labels only. 541 instruments have no info payload (504 bonds, 27 futures, 10 stocks) and keep the keyword classification.

## 2. One-rial placeholder bars

The daily history export contains 32,395 bars with open = high = low = close = 1 rial and value = volume, while `prev_close` is the real price (about 10,000 rial). Almost all belong to second fund lines (symbols ending in "2", e.g. پتروداریوش2: 180 of 180 bars) and a few other days. They are not trades at a market price.

Kept, they produced infinite returns and adjustment factors. Because `mkt_ret_ew` was a plain mean, they made the equal-weight market return NaN on 1,126 of 1,198 dates, so `rel_ret_market` was non-finite on 90% of rows. In practice the market features had been dead.

**Fix.** `features.store.drop_placeholder_bars` drops bars with `high ≤ 1` at load time. `add_market_features` treats a non-finite `ret_1` as missing. After the fix: 0 non-finite returns, 0 dates with a non-finite market return.

## 3. Still open

- Survivorship. The instrument list is today's market watch, so names delisted before 2026-11 are missing from history. Every universe-wide equal-weight figure is biased upward.
- The `limit_up` / `limit_down` columns are empty for all history. The ±3% limit rule (`verified: false`) is applied to all dates and all instruments, including ETFs.
- Costs before 2024-08-26 and ETF cost rates are unverified (OPEN_QUESTIONS 63).
