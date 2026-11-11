"""One-year risk-free yield from treasury bills (ADR 0002 section 6). Instrument names and the
price levels mirror the live TSETMC payloads of 2026-11-11."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from tmon.ingest.tsetmc.classify import load_classifier
from tmon.ingest.tsetmc.risk_free import (
    SERIES,
    compute_risk_free,
    maturity_from_name,
    treasury_bills,
)
from tmon.storage.models import Instrument, MacroSeries, PriceDaily


def test_maturity_from_jalali_suffix_matches_the_latin_ticker():
    # Latin tickers from the same payloads: TreasuryBill261207 and TreasuryBill270906.
    assert maturity_from_name("اسناد خزانه-م12بودجه02-050916") == date(2026, 12, 7)
    assert maturity_from_name("اسناد خزانه-م1-س.قوا03-060615") == date(2027, 9, 6)
    assert maturity_from_name("شرکت نمونه") is None


def test_bill_names_classify_as_bonds():
    c = load_classifier()
    itype, matched = c.classify(group_title=None, name_fa="اسنادخزانه-م1بودجه04-070607")
    assert itype.value == "bond" and matched


def _bill(session, code: str, symbol: str, name: str) -> Instrument:
    ins = Instrument(ins_code=code, symbol_fa=symbol, name_fa=name, instrument_type="bond")
    session.add(ins)
    session.flush()
    return ins


def _bar(ins: Instrument, day: date, close: float, volume: float = 1000) -> PriceDaily:
    return PriceDaily(
        instrument_id=ins.id,
        date=day,
        open=close,
        high=close,
        low=close,
        last=close,
        close=close,
        prev_close=close,
        volume=volume,
        value=close * volume,
        trades=10,
        source_url="https://example.test/bill",
        fetched_at=datetime(2026, 11, 11, 12, 0),
    )


def test_picks_the_bill_nearest_to_one_year_and_computes_the_yield(session):
    near = _bill(session, "1", "اخزا212", "اسناد خزانه-م12بودجه02-050916")  # 2026-12-07
    far = _bill(session, "2", "اخزا301", "اسناد خزانه-م1-س.قوا03-060615")  # 2027-09-06
    _bill(session, "3", "ABC", "شرکت نمونه")
    day = date(2026, 11, 10)
    session.add_all([_bar(near, day, 977040.0), _bar(far, day, 754040.0)])
    session.flush()
    assert {b.symbol_fa for b in treasury_bills(session)} == {"اخزا212", "اخزا301"}

    assert compute_risk_free(session) == 1
    row = session.scalars(select(MacroSeries).where(MacroSeries.series == SERIES)).one()
    days = (date(2027, 9, 6) - day).days  # 300: nearer to 365 than the 27-day bill
    assert row.meta["bill"] == "اخزا301" and row.meta["days_to_maturity"] == days
    assert row.value == pytest.approx((1_000_000 / 754040.0) ** (365 / days) - 1)
    assert row.ref_period == day and row.source == "tsetmc:treasury-bills" and row.source_url


def test_short_remaining_life_and_untraded_days_are_ignored(session):
    b = _bill(session, "1", "اخزا212", "اسناد خزانه-م12بودجه02-050916")  # matures 2026-12-07
    session.add_all(
        [
            _bar(b, date(2026, 11, 10), 977040.0),  # 27 days left: below the 30-day minimum
            _bar(b, date(2026, 10, 1), 950000.0, volume=0),  # no trades
        ]
    )
    session.flush()
    assert compute_risk_free(session) == 0
    assert session.scalars(select(MacroSeries)).all() == []
