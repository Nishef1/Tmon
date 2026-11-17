"""Which stocks a study may use on each day (docs/reports/survivorship-basket-2026-11.md).

Two universes:
  basket  the 100 symbols of data/liquid-basket.json, picked from the traded value of the last day
          of data and applied to every past day. It carries survivorship and hindsight: on a past day
          only 36 to 46 of them were among the 100 most traded.
  pit     point in time: on each day, the 100 stocks with the highest 20-day median traded value
          up to the day before. Nothing from that day or later is used to pick.

Studies read TMON_UNIVERSE (default "basket", so earlier reports reproduce) and add ``suffix()`` to
their output file names, so a pit run writes results_<name>_pit.json next to the basket run.
"""

from __future__ import annotations

import os
import sqlite3

import polars as pl

C = pl.col
G = "instrument_id"
TOP = 100
WINDOW = 20


def mode() -> str:
    m = os.environ.get("TMON_UNIVERSE", "basket")
    if m not in ("basket", "pit"):
        raise ValueError(f"TMON_UNIVERSE must be basket or pit, not {m!r}")
    return m


def suffix() -> str:
    return "" if mode() == "basket" else "_pit"


def stock_ids(db: str) -> dict[int, str]:
    """Every stock in the database, one id per symbol (the lowest id wins, as for the basket)."""
    ids: dict[int, str] = {}
    seen: set[str] = set()
    for iid, sym in sqlite3.connect(db, uri=True).execute(
        "select id, symbol_fa from instruments where instrument_type='stock' order by id"
    ):
        if sym not in seen:
            ids[iid] = sym
            seen.add(sym)
    return ids


def pit_members(prices: pl.DataFrame, ids: dict[int, str], top: int = TOP) -> pl.DataFrame:
    """(date, instrument_id) of the day's ``top`` stocks by 20-day median traded value as known at the
    previous close. A stock with no row on a day is not a member that day."""
    v = (
        prices.filter(C(G).is_in(list(ids)) & (C("close") > 0))
        .select(G, C("date").cast(pl.Date), C("value").cast(pl.Float64))
        .sort(G, "date")
        .with_columns(med=C("value").rolling_median(WINDOW).shift(1).over(G))
        .drop_nulls("med")
    )
    v = v.with_columns(r=C("med").rank("ordinal", descending=True).over("date"))
    return v.filter(C("r") <= top).select("date", G)
