"""AGM hold-or-sell formula (docs/05)."""

from __future__ import annotations

import pytest

from tmon.domain.agm import AgmInputs, hold_or_sell, monthly_from_annual


def _inputs(**kw: float) -> AgmInputs:
    base = {
        "dps": 1000.0,
        "price_now": 10000.0,
        "months_to_payment": 6.0,
        "monthly_discount": 0.044,
        "expected_drop_after": 0.0,
        "dividend_tax": 0.0,
        "alt_monthly_return": 0.0,
        "months_alt": 0.0,
        "round_trip_costs": 0.0,
    }
    base.update(kw)
    return AgmInputs(**base)


def test_discount_matches_the_worked_example_in_docs_05():
    # 4.4% monthly inflation, paid 6 months later: about 22.7% of the dividend is lost
    out = hold_or_sell(_inputs())
    assert 1 - out.pv_dividend / 1000 == pytest.approx(0.227, abs=0.001)


def test_formula_terms():
    x = _inputs(
        expected_drop_after=200.0,
        dividend_tax=50.0,
        alt_monthly_return=0.02,
        months_alt=3.0,
        round_trip_costs=175.0,
    )
    out = hold_or_sell(x)
    assert out.net_hold == pytest.approx(1000 / 1.044**6 - 200 - 50)
    assert out.net_sell == pytest.approx(10000 * (1.02**3 - 1) - 175)
    assert out.decision == "hold"  # 523.9 > 437.1


def test_sell_when_the_alternative_wins():
    out = hold_or_sell(_inputs(alt_monthly_return=0.03, months_alt=6.0))
    assert out.net_sell > out.net_hold
    assert out.decision == "sell"


def test_tie_is_sell():
    out = hold_or_sell(_inputs(dps=0.0, months_to_payment=0.0))
    assert out.net_hold == out.net_sell == 0
    assert out.decision == "sell"


@pytest.mark.parametrize(
    "bad",
    [
        {"price_now": 0.0},
        {"dps": -1.0},
        {"months_to_payment": -1.0},
        {"monthly_discount": -1.0},
        {"round_trip_costs": -5.0},
    ],
)
def test_rejects_invalid_inputs(bad):
    with pytest.raises(ValueError):
        hold_or_sell(_inputs(**bad))


def test_monthly_from_annual():
    assert monthly_from_annual(0.0) == 0.0
    assert (1 + monthly_from_annual(0.3)) ** 12 == pytest.approx(1.3)
