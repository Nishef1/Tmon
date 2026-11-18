import pytest

from tmon.domain.bubbles import fund_kind, right_base_symbol, right_bubble


def test_fund_kind():
    assert fund_kind("6822", 5, "etf_commodity", None) == ("صندوق طلا", None)
    assert fund_kind("6811", 23, "etf_equity", None) == ("صندوق سهامی شاخصی", None)
    assert fund_kind(None, None, "etf_fixed_income", None) == ("صندوق درآمد ثابت", None)
    assert fund_kind("6819", 21, "etf_equity", "سهامی بخشی در صنعت سیمان، آهک و گچ") == (
        "صندوق سهامی بخشی",
        "سیمان، آهک و گچ",
    )
    assert fund_kind(None, None, None, None) == ("صندوق", None)


def test_right_symbol_and_bubble():
    assert right_base_symbol("فجهانح") == "فجهان"
    assert right_base_symbol("بارانح2") == "باران"
    assert right_base_symbol("فجهان") is None
    assert right_bubble(1800, 3000) == pytest.approx(-0.1)
    assert right_bubble(100, 1000) is None
