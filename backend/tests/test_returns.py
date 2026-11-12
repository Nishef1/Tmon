"""Period returns, year range and the one-day move rule behind the industries table."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from tmon.api import returns
from tmon.api.returns import day_change, period_table
from tmon.storage.models import Instrument, PriceDaily

LAST = dt.date(2026, 11, 10)


def test_day_change_ignores_first_day_and_stale_references() -> None:
    assert day_change(102, 100) == pytest.approx(0.02)
    assert day_change(196400, 1000) is None  # first listing day: base price 1000
    assert day_change(100, 0) is None and day_change(None, 100) is None
    assert day_change(50, 100) == pytest.approx(-0.5)  # exactly the limit is still a move


def _bars(session: Session, iid: int, days: int, price_of: callable) -> None:  # type: ignore[valid-type]
    session.add(
        Instrument(id=iid, ins_code=f"c{iid}", symbol_fa=f"س{iid}", instrument_type="stock")
    )
    prev = None
    for k in range(days, -1, -1):
        close = price_of(k)
        session.add(
            PriceDaily(
                instrument_id=iid,
                date=LAST - dt.timedelta(days=k),
                close=close,
                prev_close=prev if prev is not None else close,
                market_halt=False,
            )
        )
        prev = close
    session.commit()


def test_returns_and_year_range_use_calendar_horizons(session: Session) -> None:
    returns._cache.clear()
    # price rises 1 % of 1000 per day going forward: k days before LAST it was 1000 + 10 * (400 - k)
    _bars(session, 1, 400, lambda k: 1000 + 10 * (400 - k))
    p = period_table(session, LAST)[1]
    now = 1000 + 10 * 400
    assert p.ret_week == pytest.approx(now / (now - 70) - 1)
    assert p.ret_month == pytest.approx(now / (now - 300) - 1)
    assert p.ret_3m == pytest.approx(now / (now - 900) - 1)
    assert (
        p.ret_year == pytest.approx(now / (now - 3650) - 1)
        if now > 3650
        else p.ret_year is not None
    )
    assert p.year_high == pytest.approx(now)
    assert p.year_low == pytest.approx(now - 3650)


def test_symbol_listed_within_the_year_has_no_year_return_or_range(session: Session) -> None:
    returns._cache.clear()
    _bars(session, 2, 120, lambda k: 2000 - k)
    p = period_table(session, LAST)[2]
    assert p.ret_week is not None and p.ret_month is not None and p.ret_3m is not None
    assert p.ret_year is None and p.year_high is None and p.year_low is None
