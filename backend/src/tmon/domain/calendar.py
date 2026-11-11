"""Trading calendar derived from observed market activity plus the declared halt window.

A day is *open* when enough instruments traded; halt days are flagged with a reason and
never forward-filled (docs/01, hard constraint 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from tmon.domain.rules import RuleBook


@dataclass(frozen=True)
class HaltWindow:
    start: date
    end: date
    reason: str

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


def halt_windows(rules: RuleBook, *, market: str = "IR") -> list[HaltWindow]:
    out: list[HaltWindow] = []
    for rec in rules.all_for("market_halt", market=market):
        v = rec.value
        out.append(
            HaltWindow(
                start=date.fromisoformat(v["start"]),
                end=date.fromisoformat(v["end"]),
                reason=str(v.get("reason", "market_halt")),
            )
        )
    return out


def is_in_halt(d: date, windows: list[HaltWindow]) -> bool:
    return any(w.contains(d) for w in windows)


def build_calendar(
    traded_counts: pl.DataFrame,
    windows: list[HaltWindow],
    *,
    market: str = "IR",
    min_traded_fraction: float = 0.1,
    min_traded_abs: int = 5,
) -> pl.DataFrame:
    """``traded_counts``: columns ``date`` and ``n_traded`` (instruments with volume > 0).

    Returns ``market, date, is_open, halt_reason`` for every calendar day between the first
    and last observed day (extended to cover halt windows that fall inside that span).
    """
    if traded_counts.is_empty():
        return pl.DataFrame(
            schema={
                "market": pl.Utf8,
                "date": pl.Date,
                "is_open": pl.Boolean,
                "halt_reason": pl.Utf8,
            }
        )
    counts = traded_counts.sort("date")
    median = float(counts["n_traded"].median() or 0.0)  # type: ignore[arg-type]
    threshold = max(min_traded_abs, int(median * min_traded_fraction))
    first, last = counts["date"].min(), counts["date"].max()
    assert isinstance(first, date) and isinstance(last, date)

    all_days = pl.DataFrame({"date": pl.date_range(first, last, "1d", eager=True)})
    cal = all_days.join(counts, on="date", how="left").with_columns(
        is_open=(pl.col("n_traded").fill_null(0) >= threshold)
    )
    halt_reason = pl.lit(None, dtype=pl.Utf8)
    for w in windows:
        halt_reason = (
            pl.when(pl.col("date").is_between(w.start, w.end))
            .then(pl.lit(w.reason))
            .otherwise(halt_reason)
        )
    cal = cal.with_columns(halt_reason=halt_reason).with_columns(
        is_open=pl.col("is_open") & pl.col("halt_reason").is_null()
    )
    return cal.select(pl.lit(market).alias("market"), "date", "is_open", "halt_reason")


def trading_days_between(calendar: pl.DataFrame, start: date, end: date) -> list[date]:
    df = calendar.filter(pl.col("is_open") & pl.col("date").is_between(start, end)).sort("date")
    return df["date"].to_list()


def next_open_day(calendar: pl.DataFrame, after: date) -> date | None:
    df = calendar.filter(pl.col("is_open") & (pl.col("date") > after)).sort("date").head(1)
    return df["date"][0] if df.height else None
