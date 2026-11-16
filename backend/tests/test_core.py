from datetime import UTC, date, datetime

import pytest

from tmon.core.engine_config import load_engine_config
from tmon.core.timeutil import (
    ensure_utc,
    from_jalali,
    to_tehran,
    yyyymmdd_to_date,
)


def test_jalali_to_gregorian():
    assert from_jalali(1405, 2, 29) == date(2026, 5, 19)
    assert from_jalali(1404, 12, 9) == date(2026, 2, 28)


def test_tehran_conversion_and_naive_rejected():
    dt = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
    assert to_tehran(dt).hour == 9  # UTC+3:30 -> 09:30
    assert to_tehran(dt).minute == 30
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))


def test_yyyymmdd():
    assert yyyymmdd_to_date(20260519) == date(2026, 5, 19)


def test_engine_yaml_loads_and_regimes_match_docs():
    cfg = load_engine_config()
    assert set(cfg.labeling.timeframes) == {"D1", "W1", "M1"}
    assert cfg.thresholds.margin == 0.05 and cfg.thresholds.p_floor == 0.35  # ADR 0002 section 3
    assert cfg.thresholds.ev_min_abs == 0.005 and cfg.thresholds.min_bucket_samples == 200
    assert cfg.labeling.grid["D1"].k_tp == [1.0, 1.5, 2.0]  # ADR 0002 section 4
    assert cfg.labeling.grid["D1"].k_sl == [1.0, 1.5]
    # halt window from docs/01: 9 Esfand 1404 .. day before 29 Ordibehesht 1405
    assert cfg.regime_of(from_jalali(1404, 12, 8)) == "normal"
    assert cfg.regime_of(from_jalali(1404, 12, 9)) == "halt"
    assert cfg.regime_of(from_jalali(1405, 2, 28)) == "halt"
    assert cfg.regime_of(from_jalali(1405, 2, 29)) == "post_reopen"
