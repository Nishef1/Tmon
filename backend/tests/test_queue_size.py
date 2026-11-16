from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from tmon.api.queue_size import level_of, queue_ratio, queue_readings
from tmon.storage.models import Instrument, OrderBookDaily, PriceDaily

LAST = dt.date(2026, 11, 15)


def test_levels_follow_the_two_thresholds() -> None:
    assert level_of(0.1) == "weak"
    assert level_of(0.3) == "medium"
    assert level_of(1.0) == "medium"
    assert level_of(1.01) == "heavy"


def test_only_a_one_sided_book_is_a_line_and_needs_a_usual_volume() -> None:
    got = queue_ratio(36_000_000, 0, 12_000_000)
    assert got is not None and got[0] == 3.0 and got[1] == "heavy"
    assert queue_ratio(36_000_000, 10_000_000, 12_000_000) is None  # real sellers on the other side
    assert queue_ratio(36_000_000, 0, None) is None
    assert queue_ratio(36_000_000, 0, 0) is None
    assert queue_ratio(0, 0, 5) is None


def _stock(session: Session, code: str, volumes: list[float]) -> Instrument:
    ins = Instrument(ins_code=code, symbol_fa=f"س{code}")
    session.add(ins)
    session.flush()
    for i, v in enumerate(volumes):
        session.add(
            PriceDaily(instrument_id=ins.id, date=LAST - dt.timedelta(days=i), close=1.0, volume=v)
        )
    return ins


def test_reading_uses_the_median_volume_and_only_the_latest_book_day(session: Session) -> None:
    line = _stock(session, "1", [10.0] * 10 + [1000.0])  # one huge day must not move the median
    stale = _stock(session, "2", [10.0] * 10)
    thin = _stock(session, "3", [10.0, 10.0])  # too little history for a usual volume
    for ins, day in ((line, LAST), (stale, LAST - dt.timedelta(days=1)), (thin, LAST)):
        session.add(
            OrderBookDaily(
                instrument_id=ins.id, date=day, n_events=5,
                close_bid_volume=25.0, close_ask_volume=0.0, close_bid_count=7,
            )
        )  # fmt: skip
    session.commit()
    out = queue_readings(session, [line.id, stale.id, thin.id], LAST)
    assert list(out) == [line.id]
    ratio, level, orders = out[line.id]
    assert ratio == 2.5 and level == "heavy" and orders == 7
    assert queue_readings(session, [], LAST) == {}


def test_history_odds_counts_the_next_day_covering_the_whole_queue(session: Session) -> None:
    from tmon.api.queue_size import history_odds, odds_for

    light = _stock(session, "11", [10.0] * 14)
    heavy = _stock(session, "12", [10.0] * 14)
    for ins, bid in ((light, 5.0), (heavy, 80.0)):
        for back in (4, 3):  # two consecutive book days; the second one is the "next day"
            session.add(
                OrderBookDaily(
                    instrument_id=ins.id, date=LAST - dt.timedelta(days=back), n_events=5,
                    close_bid_volume=bid, close_ask_volume=0.0, close_bid_count=3,
                )
            )  # fmt: skip
    session.commit()
    table = history_odds(session)
    assert odds_for(0.5, table) == (1.0, 1)  # 5 shares of a 10-share day: covered next day
    assert odds_for(8.0, table) == (0.0, 1)  # 80 shares: next day's 10 cannot clear it
    assert odds_for(1.0, []) is None
