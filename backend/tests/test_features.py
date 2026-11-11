"""Board, queue, market and builder tests with hand-computable inputs."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from tmon.domain.rules import RuleBook, RuleRecord
from tmon.features.builder import (
    FEATURE_SETS,
    UnsupportedTimeframeError,
    build_features,
    get_feature_set,
    limit_pct_expr,
    model_matrix,
)
from tmon.features.orderbook import (
    add_board_features,
    add_queue_features,
    order_book_imbalance,
)

CLIENT_COLS = [
    f"{s}_{m}_{k}"
    for s in ("buy", "sell")
    for m in ("count", "volume", "value")
    for k in ("i", "n")
]
RULES = RuleBook([RuleRecord("IR", "price_limit", {"pct": 0.03}, date(2000, 1, 1), None)])


def board_frame(rows: list[dict]) -> pl.DataFrame:
    base = {
        "instrument_id": 1,
        "open": 1000.0, "high": 1030.0, "low": 1000.0, "close": 1030.0, "last": 1030.0,
        "prev_close": 1000.0, "volume": 1000.0, "adj_volume": 1000.0, "value": 1_030_000.0,
        "base_volume": 2000.0, "limit_pct": 0.03,
        **{c: None for c in CLIENT_COLS},
    }  # fmt: skip
    out = []
    for i, r in enumerate(rows):
        out.append({**base, "date": date(2025, 1, 1) + timedelta(days=i), **r})
    return pl.DataFrame(out, schema_overrides={c: pl.Float64 for c in CLIENT_COLS})


def test_board_features_hand_computed():
    df = board_frame(
        [
            {
                "buy_count_i": 10.0, "buy_value_i": 1000.0, "buy_volume_i": 600.0,
                "sell_count_i": 8.0, "sell_value_i": 400.0, "sell_volume_i": 300.0,
                "buy_volume_n": 100.0, "sell_volume_n": 300.0,
                "buy_value_n": 1.0, "sell_value_n": 1.0, "value": 2000.0,
                "last": 1020.0, "close": 1010.0, "high": 1030.0, "low": 1000.0,
            }
        ]
    )  # fmt: skip
    r = add_board_features(df).row(0, named=True)
    assert r["ind_buy_per_capita"] == pytest.approx(100.0)
    assert r["ind_sell_per_capita"] == pytest.approx(50.0)
    assert r["ind_buy_power"] == pytest.approx(2.0)
    assert r["ind_net_flow"] == pytest.approx(600.0)
    assert r["ind_net_flow_ratio"] == pytest.approx(0.3)
    assert r["inst_to_ind"] == pytest.approx((300 - 100) / 1000)
    assert r["vol_to_base"] == pytest.approx(0.5)
    assert r["last_close_gap"] == pytest.approx((1020 - 1010) / 1010)
    assert r["intraday_range_pos"] == pytest.approx((1010 - 1000) / (1030 - 1000))
    assert r["ret_1_norm"] == pytest.approx(0.01 / 0.03)
    assert r["client_value_estimated"] is False
    assert r["rel_volume"] is None  # no history yet


def test_values_are_estimated_and_flagged_when_missing():
    df = board_frame(
        [{"buy_count_i": 5.0, "buy_volume_i": 400.0, "sell_count_i": 5.0, "sell_volume_i": 100.0,
          "buy_volume_n": 0.0, "sell_volume_n": 0.0}]
    )  # fmt: skip
    r = add_board_features(df).row(0, named=True)
    assert r["client_value_estimated"] is True
    assert r["ind_net_flow"] == pytest.approx((400 - 100) * 1030.0)  # volume x (value/volume)


def test_rel_volume_uses_previous_20_days_only():
    rows = [{"volume": 100.0, "adj_volume": 100.0} for _ in range(20)]
    rows.append({"volume": 300.0, "adj_volume": 300.0})
    out = add_board_features(board_frame(rows))
    assert out["rel_volume"][19] is None  # the 20-day window of *previous* days is incomplete
    assert out["rel_volume"][20] == pytest.approx(3.0)


def test_smart_money_flag_requires_all_three_conditions():
    strong = {
        "buy_count_i": 1.0, "buy_value_i": 900.0, "sell_count_i": 1.0, "sell_value_i": 100.0,
        "buy_volume_i": 1.0, "sell_volume_i": 1.0, "buy_volume_n": 0.0, "sell_volume_n": 0.0,
        "buy_value_n": 0.0, "sell_value_n": 0.0,
    }  # fmt: skip
    quiet = [{"volume": 100.0, "adj_volume": 100.0} for _ in range(20)]
    big = {**strong, "volume": 500.0, "adj_volume": 500.0}  # rel_volume 5 > 2, power 9 > 2
    small = {**strong, "volume": 110.0, "adj_volume": 110.0}  # rel_volume 1.1
    out = add_board_features(board_frame([*quiet, big, small]))
    assert out["smart_money_flag"][20] == 1
    assert out["smart_money_flag"][21] == 0


def test_queue_state_and_days_in_queue():
    rows = [
        {"prev_close": 1000.0, "close": 1030.0},  # buy queue (day 1)
        {"prev_close": 1030.0, "close": 1061.0},  # 1030 * 1.03 = 1060.9 -> buy queue (day 2)
        {"prev_close": 1061.0, "close": 1050.0},  # ordinary day
        {"prev_close": 1050.0, "close": 1018.0},  # 1050 * 0.97 = 1018.5 -> sell queue
        {"prev_close": 1018.0, "close": 1018.0},
    ]
    out = add_queue_features(board_frame(rows))
    assert out["queue_state"].to_list()[:2] == ["buy_queue", "buy_queue"]
    assert out["days_in_queue"].to_list()[:2] == [1, 2]
    assert out["queue_state"][2] == "none" and out["days_in_queue"][2] == 0
    assert out["queue_state"][3] == "sell_queue" and out["days_in_queue"][3] == 1
    assert out["queue_state"][4] == "none"


def test_queue_state_null_without_limit_rule():
    out = add_queue_features(board_frame([{"limit_pct": None}]))
    assert out["queue_state"][0] is None and out["days_in_queue"][0] is None


def test_queue_is_per_instrument():
    a = board_frame([{"close": 1030.0}, {"close": 1030.0, "prev_close": 1030.0}])
    b = board_frame([{"close": 1030.0}]).with_columns(instrument_id=pl.lit(2, dtype=pl.Int64))
    out = add_queue_features(pl.concat([a, b]).sort("instrument_id", "date"))
    assert out.filter(pl.col("instrument_id") == 2)["days_in_queue"].to_list() == [1]


def test_order_book_imbalance():
    levels = [
        {"row": 1, "bid_volume": 300, "ask_volume": 100},
        {"row": 2, "bid_volume": 100, "ask_volume": 100},
        {"row": 6, "bid_volume": 10_000, "ask_volume": 0},  # beyond depth 5 -> ignored
    ]
    assert order_book_imbalance(levels) == pytest.approx((400 - 200) / 600)
    assert order_book_imbalance([]) is None


def test_limit_pct_follows_rule_validity():
    rules = RuleBook(
        [
            RuleRecord("IR", "price_limit", {"pct": 0.03}, date(2000, 1, 1), date(2026, 12, 31)),
            RuleRecord("IR", "price_limit", {"pct": 0.05}, date(2027, 1, 1), None),
        ]
    )
    df = pl.DataFrame({"date": [date(1999, 1, 1), date(2026, 12, 31), date(2027, 1, 1)]})
    assert df.select(limit_pct_expr(rules))["literal"].to_list() == [None, 0.03, 0.05]


def test_feature_sets_are_versioned_and_timeframe_gated():
    d1 = get_feature_set("D1")
    assert d1.key.startswith("D1_v1_") and len(d1.fingerprint) == 12
    assert len(set(d1.columns)) == len(d1.columns)
    assert list(FEATURE_SETS) == ["D1"]
    with pytest.raises(UnsupportedTimeframeError):
        get_feature_set("W1")


def synthetic_market(n_days: int = 330, n_inst: int = 4, seed: int = 3):
    rng = np.random.default_rng(seed)
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(n_days)]
    price_rows, client_rows = [], []
    for iid in range(1, n_inst + 1):
        close = 10_000.0
        for i, d in enumerate(dates):
            prev = close
            if iid == 2 and i == 300:
                prev = round(close / 2)  # 2:1 capital event: exchange resets the reference
            close = round(prev * (1 + float(np.clip(rng.normal(0, 0.015), -0.03, 0.03))))
            high = round(max(close, prev) * (1 + rng.uniform(0, 0.005)))
            low = round(min(close, prev) * (1 - rng.uniform(0, 0.005)))
            vol = float(rng.integers(50_000, 500_000))
            price_rows.append(
                {
                    "instrument_id": iid, "date": d, "open": float(prev), "high": float(high),
                    "low": float(low), "close": float(close), "last": float(close),
                    "prev_close": float(prev), "volume": vol, "value": vol * close,
                    "base_volume": 100_000.0, "market_halt": False,
                }
            )  # fmt: skip
            bi = vol * rng.uniform(0.3, 0.7)
            client_rows.append(
                {
                    "instrument_id": iid, "date": d,
                    "buy_count_i": float(rng.integers(50, 500)), "buy_count_n": 3.0,
                    "sell_count_i": float(rng.integers(50, 500)), "sell_count_n": 2.0,
                    "buy_volume_i": bi, "buy_volume_n": vol - bi,
                    "sell_volume_i": vol - bi, "sell_volume_n": bi,
                    "buy_value_i": bi * close, "buy_value_n": (vol - bi) * close,
                    "sell_value_i": (vol - bi) * close, "sell_value_n": bi * close,
                }
            )  # fmt: skip
    return pl.DataFrame(price_rows), pl.DataFrame(client_rows)


def test_build_features_shapes_flags_and_model_matrix():
    prices, clients = synthetic_market()
    sectors = pl.DataFrame({"instrument_id": [1, 2, 3, 4], "sector_code": ["a", "a", "b", "b"]})
    feats = build_features(prices, clients, RULES, sectors=sectors)
    assert feats.height == prices.height
    fs = get_feature_set("D1")
    assert set(fs.columns) <= set(feats.columns)
    last = feats.filter(pl.col("date") == feats["date"].max())
    assert last["breadth"].null_count() == 0
    assert last["sector_ret_ew"].null_count() == 0
    # the 2:1 event must not appear as a crash in the adjusted return
    ev = feats.filter(
        (pl.col("instrument_id") == 2) & (pl.col("date") == date(2023, 1, 1) + timedelta(days=300))
    )
    assert abs(ev["ret_1"][0]) <= 0.031
    # eligibility needs history and liquidity
    assert not feats.filter(pl.col("history_len") < 120)["eligible"].any()
    mm = model_matrix(feats)
    assert mm.columns == ["instrument_id", "date", *fs.columns]


def test_halt_rows_are_flagged_excluded_and_not_filled():
    prices, clients = synthetic_market(n_days=200, n_inst=2)
    prices = prices.with_columns(
        market_halt=pl.col("date").is_between(date(2023, 4, 1), date(2023, 4, 30))
    )
    feats = build_features(prices, clients, RULES)
    assert feats.filter(pl.col("market_halt"))["eligible"].any() is False
    assert (
        model_matrix(feats)
        .filter(pl.col("date").is_between(date(2023, 4, 1), date(2023, 4, 30)))
        .is_empty()
    )
    assert feats.height == prices.height  # no rows invented, none dropped


def test_missing_client_types_still_builds():
    prices, _ = synthetic_market(n_days=150, n_inst=2)
    feats = build_features(prices, None, RULES)
    assert feats["ind_buy_power"].null_count() == feats.height
    assert feats["rsi_14"].null_count() < feats.height
