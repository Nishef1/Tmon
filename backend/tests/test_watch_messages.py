"""Supervisor messages: a holding is named as a word, not as a piece of another word."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tmon.core.timeutil import TEHRAN
from tmon.portfolio.watch import HoldingView, WatchState, detect_message, names_symbol


def _holding(symbol: str) -> HoldingView:
    return HoldingView(1, 7, 3, "1", symbol, 100, 1000, None, None)


NOW = datetime(2026, 11, 16, 10, 0, tzinfo=TEHRAN)


def _msg(title: str, text: str, hhmmss: int = 95000, day: int = 20261116) -> dict:
    return {"tseTitle": title, "tseDesc": text, "dEven": day, "hEven": hhmmss}


def test_gold_fund_is_not_found_inside_the_word_notice() -> None:
    # «اطلاعیه» (notice) contains «طلا»: the old substring test raised an urgent alert for every
    # general announcement of the exchange
    assert not names_symbol("طلا", "اطلاعیه مهم: توقف نماد")
    assert (
        detect_message(_holding("طلا"), _msg("اطلاعیه مهم", "توقف دسترسی"), WatchState(), NOW)
        is None
    )


@pytest.mark.parametrize(
    ("symbol", "text"),
    [
        ("خمحور", "نماد معاملاتي شركت توليد محور خودرو (خمحور) باز شد"),
        ("حفارس", "توقف نماد (حفارس1) به علت افشاي اطلاعات"),  # trailing series digit
        ("طلا", "قیمت صندوق طلا امروز"),
        ("کگل", "توقف نماد كگل"),  # Arabic kaf in the feed, Persian in our table
    ],
)
def test_the_symbol_as_a_word_is_found(symbol: str, text: str) -> None:
    assert names_symbol(symbol, text)


def test_a_symbol_inside_another_symbol_is_not_found() -> None:
    assert not names_symbol("فولاد", "توقف نماد (فولادي)")
    assert not names_symbol("خودرو", "نماد خودروسازی توقف")


def test_negative_notice_about_the_holding_is_urgent_and_asks_to_exit_once() -> None:
    state = WatchState()
    m = _msg("توقف نماد (خمحور)", "معاملات متوقف شد")
    f = detect_message(_holding("خمحور"), m, state, NOW)
    assert f is not None and f.severity == 3 and f.ask_exit
    assert detect_message(_holding("خمحور"), m, state, NOW) is None  # same notice, no second alarm


def test_a_notice_older_than_a_session_is_history() -> None:
    old = _msg("توقف نماد (خمحور)", "x", day=20261114)
    assert detect_message(_holding("خمحور"), old, WatchState(), NOW + timedelta(hours=1)) is None
