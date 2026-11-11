"""Vectorised transaction costs built from ``market_rules`` (never from constants in code)."""

from __future__ import annotations

import polars as pl

from tmon.domain.rules import MissingRuleError, RuleBook


def rule_value_expr(rules: RuleBook, rule: str, key: str, date_col: str) -> pl.Expr:
    """Value of ``rule[key]`` valid on ``date_col`` as an expression (later ``valid_from`` wins);
    null where no record covers the date."""
    expr = pl.lit(None, dtype=pl.Float64)
    for rec in rules.all_for(rule):  # ascending valid_from
        cond = pl.col(date_col) >= rec.valid_from
        if rec.valid_to is not None:
            cond = cond & (pl.col(date_col) <= rec.valid_to)
        expr = pl.when(cond).then(pl.lit(float(rec.value[key]))).otherwise(expr)
    return expr


def add_costs(
    df: pl.DataFrame,
    rules: RuleBook,
    slippage: float,
    *,
    gross: str = "realized_return",
    buy_date: str = "entry_date",
    sell_date: str = "exit_date",
    out: str = "net_return",
) -> pl.DataFrame:
    """Add ``buy_cost``, ``sell_cost``, ``round_trip_cost`` and ``net_return``.

    Mirrors :class:`tmon.domain.rules.CostModel`: buy side = commission + half the slippage
    allowance, sell side = commission + sales tax + the other half. Rules are looked up on the
    trade's own buy and sell dates.
    """
    d = df.with_columns(
        (rule_value_expr(rules, "commission_buy", "rate", buy_date) + slippage / 2).alias(
            "buy_cost"
        ),
        (
            rule_value_expr(rules, "commission_sell", "rate", sell_date)
            + rule_value_expr(rules, "sell_tax", "rate", sell_date)
            + slippage / 2
        ).alias("sell_cost"),
    )
    missing = d.filter(
        pl.col(gross).is_not_null() & (pl.col("buy_cost").is_null() | pl.col("sell_cost").is_null())
    )
    if missing.height:
        raise MissingRuleError(
            f"{missing.height} trades have no commission/tax rule valid on their dates"
        )
    return d.with_columns(
        (pl.col("buy_cost") + pl.col("sell_cost")).alias("round_trip_cost"),
        (((1 + pl.col(gross)) * (1 - pl.col("sell_cost"))) / (1 + pl.col("buy_cost")) - 1).alias(
            out
        ),
    )


def round_trip_expr(rules: RuleBook, slippage: float, date_col: str = "date") -> pl.Expr:
    """Round-trip cost fraction (buy + sell side) valid on ``date_col``, for sizing an expected
    value before the trade's own dates are known. Null where a rule is missing."""
    return (
        rule_value_expr(rules, "commission_buy", "rate", date_col)
        + rule_value_expr(rules, "commission_sell", "rate", date_col)
        + rule_value_expr(rules, "sell_tax", "rate", date_col)
        + slippage
    )
