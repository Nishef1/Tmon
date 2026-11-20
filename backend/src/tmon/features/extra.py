"""Training versions of the derived Mofid-style columns, point in time.

``features/columns.py`` computes the same ideas for the last day only, for display. Here every
column is built for every (instrument, date) from rows known at that day's close, so a model can be
trained on them. A column at date ``t`` uses only bars, flows and order books of dates ``<= t``, a
statement published before ``t``, and the share count in force at ``t``. Nothing is looked up from
the present. ``tests/test_extra_columns.py`` proves it by truncation.

What is left out on purpose, because it cannot be known at ``t`` from stored history: the float
percent (the shareholder list has no dated history), the first trading day and IPO price (static,
no information about the future), and the display scores. Fundamental ratios are null for symbols
without statements, and valuation multiples are null where the trailing figure is not positive.

Nothing here changes the production feature set (``features/builder.py``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

import polars as pl

from tmon.domain.rules import RuleBook
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import KEYS, limit_pct_expr
from tmon.features.fundamentals import Stmt, ratios

G = "instrument_id"

BETA_WINDOWS = {"beta_90d": 90, "beta_60w": 300, "beta_36m": 750}
LONG_RETURNS = {"ret_3m": 60, "ret_6m": 120, "ret_1y": 250, "ret_3y": 750, "ret_5y": 1250}

PRICE_COLUMNS: tuple[str, ...] = (
    *BETA_WINDOWS,
    *LONG_RETURNS,
    "vol_vs_30", "vol_vs_200", "val_vs_30", "val_vs_200", "avgvol_90_vs_200",
    "to_high_3m", "ceil_gap", "floor_gap",
    "val_to_mcap", "vol_to_shares", "log_mcap", "idx_weight", "ind_share", "idx_impact",
)  # fmt: skip
FLOW_COLUMNS: tuple[str, ...] = (
    "real_net_pct", "legal_net_pct", "real_net_vs_avg", "legal_buy_power",
)  # fmt: skip
BOOK_COLUMNS: tuple[str, ...] = ("bid_value_pct", "ask_value_pct", "net_order_pct")
FUND_COLUMNS: tuple[str, ...] = (
    "rev_yoy", "net_yoy", "rev_qoq", "net_qoq", "gross_margin", "op_margin", "net_margin",
    "roe", "roa", "debt_to_assets", "fin_debt_to_equity", "current_ratio",
    "pe_ttm", "ps_ttm", "pb",
)  # fmt: skip
GROUPS: dict[str, tuple[str, ...]] = {
    "price": PRICE_COLUMNS,
    "flow": FLOW_COLUMNS,
    "book": BOOK_COLUMNS,
    "fund": FUND_COLUMNS,
}
EXTRA_COLUMNS: tuple[str, ...] = tuple(c for g in GROUPS.values() for c in g)

# the day after a filing is the first day its figures count as known
STATEMENT_LAG_DAYS = 1
UNIT = 1e6  # statements are in million rial


def _roll_beta(r: pl.Expr, m: pl.Expr, n: int) -> pl.Expr:
    """Rolling beta of ``r`` on ``m`` over ``n`` observations: cov / var from rolling means."""
    need = max(n * 2 // 3, 20)
    mean_r, mean_m = r.rolling_mean(n, min_samples=need), m.rolling_mean(n, min_samples=need)
    cov = (r * m).rolling_mean(n, min_samples=need) - mean_r * mean_m
    var = (m * m).rolling_mean(n, min_samples=need) - mean_m * mean_m
    return pl.when(var > 0).then(cov / var).otherwise(None)


def shares_frame(
    changes: Sequence[tuple[int, dt.date, float | None, float | None]],
    tag_shares: Mapping[int, float],
    dated: Sequence[tuple[int, dt.date, float | None]] = (),
) -> pl.DataFrame:
    """Share count in force from each date, per instrument. ``changes`` are ``(instrument_id,
    date, shares_old, shares_new)``; ``dated`` are ``(instrument_id, date, shares)`` read from
    TSETMC's page of that day (``shares_history``, sampled monthly). Both are observations of the
    count in force from their date on. Before the earliest observation the earliest known count is
    used (the old count of the first change, or the first dated sample, whichever is earlier); an
    instrument with neither keeps its current count (today's count applied to the past)."""
    schema = {G: pl.Int64, "date": pl.Date, "shares": pl.Float64}
    rows: list[tuple[int, dt.date, float]] = []
    first: dict[int, tuple[dt.date, float]] = {}
    for iid, d, old, new in sorted(changes, key=lambda x: (x[0], x[1])):
        rows.append((iid, d, float(new)) if new else (iid, d, float(old or 0) or float("nan")))
        if iid not in first and old:
            first[iid] = (d, float(old))
    for iid, d, n in sorted(dated, key=lambda x: (x[0], x[1])):
        if not n or n <= 0:
            continue
        rows.append((iid, d, float(n)))
        if iid not in first or d < first[iid][0]:
            first[iid] = (d, float(n))
    out = pl.DataFrame(rows, schema=schema, orient="row").filter(
        pl.col("shares").is_not_nan() & (pl.col("shares") > 0)
    )
    base = [
        (iid, dt.date(1990, 1, 1), s) for iid, s in tag_shares.items() if s and iid not in first
    ] + [(iid, dt.date(1990, 1, 1), old) for iid, (_d, old) in first.items()]
    base_df = pl.DataFrame(base, schema=schema, orient="row")
    # a dated sample and a change on the same day: keep one row (the later one in the list)
    return pl.concat([base_df, out]).unique([G, "date"], keep="last").sort(G, "date")


def fundamentals_frame(stmts: Mapping[int, list[Stmt]]) -> pl.DataFrame:
    """For every filing date, the ratios of what was public after it. ``earn_inv`` and friends are
    the inverse trailing figures, so a multiple on any later day is mcap times that inverse."""
    rows: list[dict[str, object]] = []
    for iid, lst in stmts.items():
        for eff in sorted({s.published_at.date() for s in lst}):
            known = [s for s in lst if s.published_at.date() <= eff]
            r = ratios(known, 1e6 * UNIT)  # mcap of 1e6 million: the multiples come out as inverses
            if not r:
                continue
            rows.append(
                {
                    G: iid,
                    "date": eff + dt.timedelta(days=STATEMENT_LAG_DAYS),
                    **{c: r.get(c) for c in FUND_COLUMNS if c not in ("pe_ttm", "ps_ttm", "pb")},
                    "_pe_per_mcap": r.get("pe_ttm"),
                    "_ps_per_mcap": r.get("ps_ttm"),
                    "_pb_per_mcap": r.get("pb"),
                }
            )
    cols = [c for c in FUND_COLUMNS if c not in ("pe_ttm", "ps_ttm", "pb")] + [
        "_pe_per_mcap",
        "_ps_per_mcap",
        "_pb_per_mcap",
    ]
    schema: dict[str, pl.DataType | type[pl.DataType]] = {G: pl.Int64, "date": pl.Date}
    schema.update(dict.fromkeys(cols, pl.Float64))
    if not rows:
        return pl.DataFrame(schema=schema)
    df = pl.DataFrame(rows, schema=schema).sort(G, "date")
    return df.unique(subset=[G, "date"], keep="last", maintain_order=True)


def build_extra(
    prices: pl.DataFrame,
    client_types: pl.DataFrame | None,
    rules: RuleBook,
    *,
    sectors: pl.DataFrame | None = None,
    index_close: pl.DataFrame | None = None,
    shares: pl.DataFrame | None = None,
    stmts: Mapping[int, list[Stmt]] | None = None,
    order_book: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Every extra column for every (instrument, date); ``KEYS`` plus ``EXTRA_COLUMNS``.

    ``index_close``: ``date, close`` of the benchmark index. ``shares``: from ``shares_frame``.
    ``order_book``: ``instrument_id, date, close_bid_price, close_ask_price, close_bid_volume,
    close_ask_volume``. Any input left out turns its columns to null."""
    d = apply_adjustments(prices.sort(KEYS))
    d = d.with_columns(limit_pct_expr(rules).alias("_lim"))
    c, v, val = pl.col("adj_close"), pl.col("adj_volume"), pl.col("value")
    d = d.with_columns((c / c.shift(1).over(G) - 1.0).alias("_r"))

    if index_close is not None and not index_close.is_empty():
        ix = index_close.sort("date").with_columns(
            (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("_m")
        )
        d = d.join(ix.select("date", "_m"), on="date", how="left")
    else:
        d = d.with_columns(pl.lit(None, dtype=pl.Float64).alias("_m"))

    exprs: list[pl.Expr] = [
        _roll_beta(pl.col("_r"), pl.col("_m"), n).over(G).alias(k) for k, n in BETA_WINDOWS.items()
    ]
    exprs += [(c / c.shift(n).over(G) - 1.0).alias(k) for k, n in LONG_RETURNS.items()]
    for n in (30, 200):  # the average of the days before today, so today is not in its own base
        exprs.append(
            (v / v.shift(1).rolling_mean(n, min_samples=n // 2).over(G)).alias(f"vol_vs_{n}")
        )
        exprs.append(
            (val / val.shift(1).rolling_mean(n, min_samples=n // 2).over(G)).alias(f"val_vs_{n}")
        )
    exprs.append(
        (
            v.rolling_mean(90, min_samples=60).over(G)
            / v.rolling_mean(200, min_samples=120).over(G)
        ).alias("avgvol_90_vs_200")
    )
    exprs.append(
        (c / pl.col("adj_high").rolling_max(63, min_samples=40).over(G) - 1.0).alias("to_high_3m")
    )
    exprs.append(
        (pl.col("prev_close") * (1 + pl.col("_lim")) / pl.col("close") - 1.0).alias("ceil_gap")
    )
    exprs.append(
        (pl.col("prev_close") * (1 - pl.col("_lim")) / pl.col("close") - 1.0).alias("floor_gap")
    )
    d = d.with_columns(exprs)

    if shares is not None and not shares.is_empty():
        d = (
            d.sort("date")
            .join_asof(shares.sort("date"), on="date", by=G, check_sortedness=False)
            .sort(KEYS)
        )
    else:
        d = d.with_columns(pl.lit(None, dtype=pl.Float64).alias("shares"))
    mcap = pl.col("close") * pl.col("shares")
    d = d.with_columns(
        mcap.alias("_mcap"),
        (val / mcap).alias("val_to_mcap"),
        (pl.col("volume") / pl.col("shares")).alias("vol_to_shares"),
        mcap.log().alias("log_mcap"),
    )
    d = d.with_columns((pl.col("_mcap") / pl.col("_mcap").sum().over("date")).alias("idx_weight"))
    d = d.with_columns((pl.col("idx_weight") * pl.col("_r") * 100.0).alias("idx_impact"))
    if sectors is not None and "sector_code" in sectors.columns:
        d = d.join(sectors.select(G, "sector_code"), on=G, how="left")
        d = d.with_columns(
            (pl.col("_mcap") / pl.col("_mcap").sum().over("date", "sector_code")).alias("ind_share")
        )
    else:
        d = d.with_columns(pl.lit(None, dtype=pl.Float64).alias("ind_share"))

    flow_cols = ("real_net_pct", "legal_net_pct", "real_net_vs_avg", "legal_buy_power")
    if client_types is not None and not client_types.is_empty():
        need = [
            "buy_value_i", "sell_value_i", "buy_value_n", "sell_value_n",
            "buy_count_n", "sell_count_n",
        ]  # fmt: skip
        d = d.join(client_types.select(*KEYS, *need), on=list(KEYS), how="left")
        real_net = pl.col("buy_value_i") - pl.col("sell_value_i")
        legal_net = pl.col("buy_value_n") - pl.col("sell_value_n")
        d = d.with_columns(
            (real_net / val).alias("real_net_pct"),
            (legal_net / val).alias("legal_net_pct"),
            (real_net / val.shift(1).rolling_mean(30, min_samples=15).over(G)).alias(
                "real_net_vs_avg"
            ),
            (
                (pl.col("buy_value_n") / pl.col("buy_count_n"))
                / (pl.col("sell_value_n") / pl.col("sell_count_n"))
            ).alias("legal_buy_power"),
        )
    else:
        d = d.with_columns([pl.lit(None, dtype=pl.Float64).alias(k) for k in flow_cols])

    if order_book is not None and not order_book.is_empty():
        ob = order_book.select(
            G,
            "date",
            (pl.col("close_bid_price") * pl.col("close_bid_volume")).alias("_bid"),
            (pl.col("close_ask_price") * pl.col("close_ask_volume")).alias("_ask"),
        )
        d = d.join(ob, on=[G, "date"], how="left")
        d = d.with_columns(
            (pl.col("_bid") / val).alias("bid_value_pct"),
            (pl.col("_ask") / val).alias("ask_value_pct"),
            ((pl.col("_bid") - pl.col("_ask")) / val).alias("net_order_pct"),
        )
    else:
        d = d.with_columns([pl.lit(None, dtype=pl.Float64).alias(k) for k in BOOK_COLUMNS])

    fund_cols = [c_ for c_ in FUND_COLUMNS if c_ not in ("pe_ttm", "ps_ttm", "pb")]
    fund = fundamentals_frame(stmts) if stmts else None
    if fund is not None and not fund.is_empty():
        d = (
            d.sort("date")
            .join_asof(fund.sort("date"), on="date", by=G, check_sortedness=False)
            .sort(KEYS)
        )
        mc_m = pl.col("_mcap") / UNIT
        # the frame holds multiples for a market cap of 1e6 million; scale to the real one
        d = d.with_columns(
            (pl.col("_pe_per_mcap") * mc_m / 1e6).alias("pe_ttm"),
            (pl.col("_ps_per_mcap") * mc_m / 1e6).alias("ps_ttm"),
            (pl.col("_pb_per_mcap") * mc_m / 1e6).alias("pb"),
        )
    else:
        d = d.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias(k)
                for k in (*fund_cols, "pe_ttm", "ps_ttm", "pb")
            ]
        )
    return d.select(*KEYS, *EXTRA_COLUMNS).sort(KEYS)
