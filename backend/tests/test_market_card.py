"""The market card: the equity share, why, and the most traded equity funds (ADR 0004 section 3)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from tmon.api.market_card import FUNDS_NOTE, FUNDS_SHOWN, market_card, market_reasons
from tmon.storage.models import FundNav, Instrument, PriceDaily

DAY = dt.date(2026, 11, 10)


def _doc(exposure: float) -> dict[str, Any]:
    return {
        "exposure_date": DAY.isoformat(),
        "exposure": {"exposure": exposure, "trend": 1.0, "abs_mom": 0.0, "stress": 0.9},
    }


def _fund(session: Session, code: str, symbol: str, value: float, close: float) -> Instrument:
    ins = Instrument(ins_code=code, symbol_fa=symbol, name_fa=f"صندوق {symbol}")
    ins.instrument_type = "etf_equity"
    session.add(ins)
    session.flush()
    session.add(PriceDaily(instrument_id=ins.id, date=DAY, close=close, value=value))
    return ins


def test_reasons_name_the_three_factors_in_plain_words() -> None:
    text = " ".join(market_reasons(_doc(0.4)["exposure"]))
    assert "بالای" in text and "کمتر از" in text and "10.0٪" in text
    assert market_reasons({}) == [] and market_reasons({"exposure": None}) == []


def test_no_exposure_means_no_card(session: Session) -> None:
    assert market_card(session, {}) is None


def test_zero_exposure_shows_no_funds(session: Session) -> None:
    _fund(session, "f1", "صندوقی", 5e9, 1000)
    session.commit()
    card = market_card(session, _doc(0.0))
    assert card is not None and not card.positive and card.funds == [] and card.funds_note == ""


def test_positive_exposure_lists_the_most_traded_funds_with_premium_and_the_untested_note(
    session: Session,
) -> None:
    a = _fund(session, "f1", "اول", 9e9, 1100)
    _fund(session, "f2", "دوم", 5e9, 1000)
    for k in range(FUNDS_SHOWN + 2):
        _fund(session, f"g{k}", f"کم{k}", 1e6 + k, 100)
    session.add(FundNav(reg_no=1, instrument_id=a.id, date=DAY, cancel_nav=1000.0))
    session.commit()
    card = market_card(session, _doc(0.6))
    assert card is not None and card.positive and card.exposure == 0.6
    assert len(card.funds) == FUNDS_SHOWN
    assert [f.symbol for f in card.funds[:2]] == ["اول", "دوم"]
    assert card.funds[0].premium is not None and abs(card.funds[0].premium - 0.1) < 1e-9
    assert card.funds[1].premium is None  # no stored NAV: no premium, not a guess
    assert card.funds_note == FUNDS_NOTE and "آزموده نشده" in card.funds_note
