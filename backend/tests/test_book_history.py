from __future__ import annotations

from typing import Any

import polars as pl

from tmon.features.book_signal import short_score
from tmon.ingest.tsetmc.book_history import reduce_day


def _row(
    h: int, ref: int, level: int, bv: float, bp: float, av: float, ap: float
) -> dict[str, Any]:
    return {
        "hEven": h, "refID": ref, "number": level,
        "qTitMeDem": bv, "zOrdMeDem": 1 if bv else 0, "pMeDem": bp,
        "qTitMeOf": av, "zOrdMeOf": 1 if av else 0, "pMeOf": ap,
    }  # fmt: skip


def test_empty_day_is_none() -> None:
    assert reduce_day([]) is None


def test_buy_queue_all_session() -> None:
    # bid volume, nothing offered, from before the open to the close
    rows = [_row(85900, 1, 1, 1_000_000, 1000, 0, 0)]
    out = reduce_day(rows)
    assert out is not None
    assert out["frac_buy_queue"] == 1.0 and out["frac_sell_queue"] == 0.0
    assert out["close_imbalance"] == 1.0 and out["tw_imbalance"] == 1.0
    assert out["peak_queue_volume"] == 1_000_000


def test_balanced_then_sell_queue() -> None:
    rows = [
        _row(90000, 1, 1, 100, 1000, 100, 1010),  # 09:00-10:45 balanced
        _row(104500, 2, 1, 0, 0, 500, 1000),  # 10:45-12:30 sell queue
    ]
    out = reduce_day(rows)
    assert out is not None
    assert abs(out["frac_sell_queue"] - 105 / 210) < 1e-9
    assert out["peak_queue_volume"] == -500
    assert out["close_imbalance"] == -1.0
    assert out["open_imbalance"] == 0.0


def test_levels_are_carried_forward() -> None:
    # level 2 appears later; level 1 keeps its last state
    rows = [_row(90000, 1, 1, 100, 1000, 50, 1010), _row(90100, 2, 2, 100, 990, 50, 1020)]
    out = reduce_day(rows)
    assert out is not None and out["close_bid_volume"] == 100 and out["close_ask_volume"] == 50


def test_short_score_ranks_within_day() -> None:
    cols = ("tw_imbalance", "close_imbalance", "tw_size_ratio", "open_imbalance", "last_close_gap")
    df = pl.DataFrame(
        {"instrument_id": [1, 2, 3], "date": ["2026-01-01"] * 3}
        | {c: [0.1, 0.5, 0.9] for c in cols}
    ).with_columns(pl.col("date").str.to_date())
    out = short_score(df)["book_score"].to_list()
    assert out[0] < out[1] < out[2]
