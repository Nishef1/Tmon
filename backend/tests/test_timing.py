"""Best time of day: the 15-minute slices of a change log and what many days say about them."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pytest
from sqlalchemy.orm import Session

from tmon.ingest.tsetmc.book_history import N_WINDOWS, reduce_profile
from tmon.portfolio import timing
from tmon.storage.models import Instrument, IntradayProfileDaily


def _row(h: int, ref: int, bp: float, ap: float, vol: float = 100) -> dict[str, Any]:
    return {
        "hEven": h, "refID": ref, "number": 1,
        "qTitMeDem": vol, "zOrdMeDem": 1, "pMeDem": bp,
        "qTitMeOf": vol, "zOrdMeOf": 1, "pMeOf": ap,
    }  # fmt: skip


@pytest.fixture(autouse=True)
def _fresh_memo() -> None:
    timing._memo.clear()


def test_the_session_is_fourteen_quarter_hours() -> None:
    assert N_WINDOWS == 14
    assert timing.window_label(0) == "09:00–09:15"
    assert timing.window_label(13) == "12:15–12:30"


def test_slices_carry_the_cheapest_ask_and_dearest_bid_of_each_quarter_hour() -> None:
    rows = [
        _row(90000, 1, 990, 1000),  # 09:00-09:20
        _row(92000, 2, 960, 970),  # 09:20-09:40: cheaper book
        _row(94000, 3, 1010, 1020),  # 09:40-12:30
    ]
    out = {w["window"]: w for w in reduce_profile(rows)}
    assert len(out) == N_WINDOWS
    assert out[0]["ask_min"] == 1000 and out[0]["bid_max"] == 990
    # slice 1 (09:15-09:30) saw both the first book (till 09:20) and the cheaper one
    assert out[1]["ask_min"] == 970 and out[1]["bid_max"] == 990
    assert out[2]["ask_min"] == 970 and out[2]["bid_max"] == 1010
    assert out[5]["ask_min"] == 1020 and out[5]["bid_max"] == 1010
    assert out[0]["mid"] == 995.0 and out[0]["secs"] == 900.0


def test_a_one_sided_book_has_no_price_on_the_missing_side() -> None:
    row = _row(90000, 1, 1000, 0) | {"qTitMeOf": 0, "pMeOf": 0, "zOrdMeOf": 0}
    rows = [row]
    out = reduce_profile(rows)
    assert out and out[0]["ask_min"] is None and out[0]["bid_max"] == 1000 and out[0]["mid"] is None


def _seed(
    session: Session,
    iid: int,
    days: int,
    mids: Any = None,
    ask_min_low_at_open: bool = False,
    seed: int = 7,
) -> None:
    """``mids(day_index, window)`` is the slice's mid against 1000 (default flat); 0.1 % noise."""
    rng = np.random.default_rng(seed + iid)
    session.add(
        Instrument(id=iid, ins_code=f"c{iid}", symbol_fa=f"S{iid}", instrument_type="stock")
    )
    start = dt.date(2026, 6, 1)
    for d in range(days):
        day = start + dt.timedelta(days=d)
        for k in range(N_WINDOWS):
            rel = (mids(d, k) if mids else 0.0) + float(rng.normal(0, 0.001))
            mid = 1000.0 * (1 + rel)
            session.add(
                IntradayProfileDaily(
                    instrument_id=iid,
                    date=day,
                    window=k,
                    mid=mid,
                    ask_min=mid * (0.97 if ask_min_low_at_open and k == 0 else 1.0),
                    bid_max=mid * (1.03 if ask_min_low_at_open and k == 0 else 1.0),
                    secs=900.0,
                )
            )
    session.commit()


def test_a_slice_that_is_cheaper_in_both_halves_is_confirmed_out_of_sample(
    session: Session,
) -> None:
    _seed(session, 1, 40, mids=lambda d, k: -0.006 if k == 4 else (0.006 if k == 9 else 0.0))
    r = timing.time_of_day(session, 1)
    assert r["available"] and r["basis"] == "own" and r["basis_days"] == 40
    assert r["buy"]["window"] == 4 and r["buy"]["label"] == "10:00–10:15"
    assert r["buy"]["confirmed"] and r["buy"]["vs_day"] < -0.005 and r["buy"]["t"] < -2
    assert r["sell"]["window"] == 9 and r["sell"]["confirmed"] and r["sell"]["vs_day"] > 0.005
    assert r["out_of_sample"] is True and any("آزموده نشده" in n for n in r["notes"])
    assert any("سفارشِ قطعی نگیرید" in n for n in r["notes"])


def test_flat_prices_give_no_reliable_hour_and_say_how_little_slices_differ(
    session: Session,
) -> None:
    _seed(session, 2, 40)
    r = timing.time_of_day(session, 2)
    assert r["available"]
    assert not r["buy"]["confirmed"] and not r["sell"]["confirmed"]
    assert "معتبر بهتر نبوده" in r["headline"] and r["spread"] < 0.01


def test_extreme_quotes_at_the_open_do_not_make_the_open_a_cheap_hour(session: Session) -> None:
    """The first version ranked the lowest best-ask and highest best-bid per slice and named
    09:00 the best hour to buy and to sell for every stock: the open's quotes are simply wild."""
    _seed(session, 3, 40, ask_min_low_at_open=True)
    r = timing.time_of_day(session, 3)
    assert not r["buy"]["confirmed"] and not r["sell"]["confirmed"]


def test_a_pattern_that_flips_between_halves_is_not_confirmed(session: Session) -> None:
    _seed(session, 4, 40, mids=lambda d, k: -0.006 if k == (0 if d < 20 else 10) else 0.0)
    r = timing.time_of_day(session, 4)
    assert r["available"] and not r["buy"]["confirmed"]
    assert r["buy"]["window"] == 0  # picked on the old half, then rejected on the new one


def test_the_day_low_is_compared_with_what_a_random_price_would_give_each_slice() -> None:
    lo, hi = timing.chance()
    assert lo.sum() == pytest.approx(1.0) and hi.sum() == pytest.approx(1.0)
    assert lo[0] > 2 * lo[6] and lo[13] > 2 * lo[6]  # the edges hold the extremes far more often
    assert lo[0] > 1 / N_WINDOWS


def test_too_few_days_says_so_instead_of_guessing(session: Session) -> None:
    _seed(session, 5, 8)
    r = timing.time_of_day(session, 5)
    assert not r["available"] and "دادهٔ کافی" in r["message"]


def test_a_stock_with_few_days_falls_back_to_the_pool_and_says_so(session: Session) -> None:
    for iid in range(10, 22):
        _seed(session, iid, 20, mids=lambda d, k: -0.006 if k == 3 else 0.0)
    _seed(session, 99, 3)
    r = timing.time_of_day(session, 99)
    assert r["available"] and r["basis"] == "market"
    assert r["buy"]["window"] == 3 and r["buy"]["confirmed"]
    assert any("همهٔ نمادها" in n for n in r["notes"])


def test_no_table_rows_is_not_an_error(session: Session) -> None:
    r = timing.time_of_day(session, 1)
    assert not r["available"]
