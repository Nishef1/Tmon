from datetime import date

import polars as pl
import pytest

from tmon.core.engine_config import load_engine_config
from tmon.domain.calendar import (
    HaltWindow,
    build_calendar,
    halt_windows,
    is_in_halt,
    next_open_day,
    trading_days_between,
)
from tmon.domain.rules import CostModel, MissingRuleError, RuleBook, RuleRecord
from tmon.storage.seed import SEED_RULES, seed_market_rules


def test_seed_is_idempotent_and_loadable(session):
    assert seed_market_rules(session) == len(SEED_RULES)
    assert seed_market_rules(session) == 0
    book = RuleBook.from_session(session)
    assert book.value("trading_hours", date(2026, 7, 1))["close"] == "12:30"
    with pytest.raises(MissingRuleError):
        book.value("trading_hours", date(2026, 1, 1))  # before valid_from: no silent default


def test_unverified_rules_are_listed(session):
    seed_market_rules(session)
    names = {r.rule for r in RuleBook.from_session(session).unverified()}
    assert {"commission_buy", "commission_sell", "sell_tax", "price_limit"} <= names


def test_rule_versioning_latest_valid_from_wins():
    book = RuleBook(
        [
            RuleRecord("IR", "price_limit", {"pct": 0.03}, date(2020, 1, 1), date(2026, 12, 31)),
            RuleRecord("IR", "price_limit", {"pct": 0.05}, date(2027, 1, 1), None),
        ]
    )
    assert book.value("price_limit", date(2026, 6, 1))["pct"] == 0.03
    assert book.value("price_limit", date(2027, 6, 1))["pct"] == 0.05


def test_halt_seed_matches_engine_regimes(session):
    seed_market_rules(session)
    w = halt_windows(RuleBook.from_session(session))[0]
    cfg = load_engine_config()
    halt_regime = next(r for r in cfg.validation.regimes if r.name == "halt")
    assert (w.start, w.end) == (halt_regime.start, halt_regime.end)


def test_cost_model_round_trip():
    cm = CostModel(commission_buy=0.004, commission_sell=0.004, sell_tax=0.005, slippage=0.002)
    assert cm.round_trip == pytest.approx(0.015)
    assert cm.net_return(0.0) == pytest.approx(
        (1 - 0.005 - 0.004 - 0.001) / (1 + 0.004 + 0.001) - 1
    )
    assert cm.net_return(0.10) > 0.08


def test_cost_model_from_rules_requires_rules(session):
    seed_market_rules(session)
    book = RuleBook.from_session(session)
    cm = CostModel.from_rules(book, date(2026, 7, 1), slippage_fraction=0.005)
    assert cm.sell_tax == 0.005
    with pytest.raises(MissingRuleError):
        CostModel.from_rules(RuleBook([]), date(2026, 7, 1), 0.005)


def _counts(days):
    return pl.DataFrame({"date": [d for d, _ in days], "n_traded": [n for _, n in days]})


def test_calendar_marks_holidays_and_halts_without_forward_fill():
    days = [
        (date(2026, 2, 25), 800),
        (date(2026, 2, 26), 790),
        (date(2026, 2, 27), 3),  # weekend noise: below threshold
        (date(2026, 3, 1), 10),  # inside halt window, stray rows must not reopen the day
        (date(2026, 5, 19), 700),
    ]
    cal = build_calendar(_counts(days), [HaltWindow(date(2026, 2, 28), date(2026, 5, 18), "war")])
    by_date = {r["date"]: r for r in cal.iter_rows(named=True)}
    assert by_date[date(2026, 2, 25)]["is_open"] is True
    assert by_date[date(2026, 2, 27)]["is_open"] is False
    assert by_date[date(2026, 3, 1)]["is_open"] is False
    assert by_date[date(2026, 3, 1)]["halt_reason"] == "war"
    assert by_date[date(2026, 4, 10)]["halt_reason"] == "war"
    assert by_date[date(2026, 5, 19)]["is_open"] is True
    assert cal.height == (date(2026, 5, 19) - date(2026, 2, 25)).days + 1

    assert trading_days_between(cal, date(2026, 2, 1), date(2026, 6, 1)) == [
        date(2026, 2, 25),
        date(2026, 2, 26),
        date(2026, 5, 19),
    ]
    assert next_open_day(cal, date(2026, 2, 26)) == date(2026, 5, 19)
    assert is_in_halt(date(2026, 4, 1), [HaltWindow(date(2026, 2, 28), date(2026, 5, 18), "war")])
