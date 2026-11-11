from datetime import UTC, date, datetime

import pytest

from tmon.core.engine_config import load_engine_config
from tmon.core.timeutil import (
    date_to_yyyymmdd,
    ensure_utc,
    format_jalali,
    format_jalali_long,
    parse_jalali,
    to_tehran,
    yyyymmdd_to_date,
)


def test_jalali_roundtrip():
    d = parse_jalali("1405/02/29")
    assert d == date(2026, 5, 19)
    assert format_jalali(d) == "1405/02/29"
    assert parse_jalali("1404-12-09") == date(2026, 2, 28)


def test_jalali_long_uses_persian_digits():
    assert format_jalali_long(date(2026, 5, 19)) == "۲۹ اردیبهشت ۱۴۰۵"


def test_tehran_conversion_and_naive_rejected():
    dt = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
    assert to_tehran(dt).hour == 9  # UTC+3:30 -> 09:30
    assert to_tehran(dt).minute == 30
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))


def test_yyyymmdd():
    assert yyyymmdd_to_date(20260519) == date(2026, 5, 19)
    assert date_to_yyyymmdd(date(2026, 5, 19)) == 20260519


def test_engine_yaml_loads_and_regimes_match_docs():
    cfg = load_engine_config()
    assert set(cfg.labeling.timeframes) == {"D1", "W1", "M1"}
    assert cfg.thresholds.p_min["D1"] == 0.60
    # halt window from docs/01: 9 Esfand 1404 .. day before 29 Ordibehesht 1405
    assert cfg.regime_of(parse_jalali("1404/12/08")) == "normal"
    assert cfg.regime_of(parse_jalali("1404/12/09")) == "halt"
    assert cfg.regime_of(parse_jalali("1405/02/28")) == "halt"
    assert cfg.regime_of(parse_jalali("1405/02/29")) == "post_reopen"
