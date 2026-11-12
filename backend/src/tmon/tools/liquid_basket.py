"""The liquid basket: the stocks that matter for the portfolio, chosen only from traded value.

``python -m tmon.tools.liquid_basket --top 100 --days 30`` prints how many distinct stocks were
among the ``top`` by 20-day median traded value on any day of the last ``days`` days (and, for
context, of the last 1, 2 and 5 years), and writes the symbols of the ``--days`` window (most
liquid first) to ``--out``. The Codal backfill reads that file, so
disclosures are collected only for names the portfolio can actually hold.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.core.db import session_scope
from tmon.domain.enums import InstrumentType
from tmon.storage.models import Instrument, PriceDaily


def basket(top: int, days: int) -> tuple[list[str], dict[str, int]]:
    """Symbols that were in the top ``top`` by 20-day median value on some day of the window,
    ordered by their latest rolling median value, plus the size of the basket per window."""
    with session_scope() as s:
        meta = pl.DataFrame(
            s.execute(
                select(Instrument.id, Instrument.symbol_fa).where(
                    Instrument.instrument_type == InstrumentType.STOCK.value
                )
            ).all(),
            schema=["instrument_id", "symbol"],
            orient="row",
        )
        px = pl.DataFrame(
            s.execute(select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.value)).all(),
            schema=["instrument_id", "date", "value"],
            orient="row",
        )
    px = px.join(meta.select("instrument_id"), on="instrument_id").sort("instrument_id", "date")
    px = px.with_columns(
        pl.col("value").cast(pl.Float64).rolling_median(20).over("instrument_id").alias("med")
    ).drop_nulls("med")
    last = cast("date", px["date"].max())
    sizes: dict[str, int] = {}
    chosen: set[int] = set()
    for label, span in (("window", days), ("1y", 365), ("2y", 730), ("5y", 1825)):
        win = px.filter(pl.col("date") > last - timedelta(days=span))
        top_ids = (
            win.with_columns(pl.col("med").rank("ordinal", descending=True).over("date").alias("r"))
            .filter(pl.col("r") <= top)["instrument_id"]
            .unique()
        )
        sizes[label] = top_ids.len()
        if label == "window":
            chosen = set(top_ids.to_list())
    latest = px.filter(pl.col("date") == last).sort("med", descending=True)
    order = [i for i in latest["instrument_id"].to_list() if i in chosen]
    rest = [i for i in chosen if i not in set(order)]
    sym = dict(zip(meta["instrument_id"].to_list(), meta["symbol"].to_list(), strict=True))
    symbols = list(dict.fromkeys(sym[i] for i in [*order, *np.sort(np.array(rest, dtype=int))]))
    return symbols, sizes


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-liquid-basket")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--out", default="data/liquid-basket.json")
    a = ap.parse_args()
    symbols, sizes = basket(a.top, a.days)
    Path(a.out).write_text(
        json.dumps({"top": a.top, "days": a.days, "symbols": symbols}, ensure_ascii=False),
        "utf-8",
    )
    print(f"distinct names in the top {a.top} on some day, per window: {sizes}")
    print(f"basket written: {len(symbols)} symbols -> {a.out}")


if __name__ == "__main__":
    main()
