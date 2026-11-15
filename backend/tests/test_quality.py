from datetime import date, timedelta

import polars as pl

from tmon.features.quality import clean_clients, clean_prices

D0 = date(2025, 1, 4)  # a Saturday


def _prices(rows, iid=1):
    """rows: (open, high, low, close, prev_close, volume) on consecutive Sat..Thu days."""
    days = [d for d in (D0 + timedelta(days=i) for i in range(30)) if d.weekday() != 4]
    return pl.DataFrame(
        {
            "instrument_id": [iid] * len(rows),
            "date": days[: len(rows)],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "last": [r[3] for r in rows],
            "prev_close": [r[4] for r in rows],
            "volume": [float(r[5]) for r in rows],
            "value": [r[3] * r[5] for r in rows],
        }
    )


def test_spike_is_dropped_and_the_next_reference_repaired():
    a = _prices([(100, 101, 99, 100, 100, 10), (100, 131, 130, 130, 100, 10),
                 (101, 102, 100, 101, 130, 10), (101, 102, 100, 102, 101, 10)])  # fmt: skip
    # other symbols moving 3% a day set the day's limit band
    rest = [_prices([(100, 103, 100, 103, 100, 10 + i)] * 4, iid=i) for i in range(2, 200)]
    out = clean_prices(pl.concat([a, *rest])).filter(pl.col("instrument_id") == 1)
    assert out.height == 3
    assert out["prev_close"].to_list()[1] == 100  # not 130: no fake adjustment


def test_copied_day_and_nonpositive_are_dropped():
    a = _prices([(100, 101, 99, 100, 100, 10), (100, 101, 99, 100, 100, 10),
                 (0, 0, 0, 0, 100, 0), (100, 101, 99, 101, 100, 12)])  # fmt: skip
    assert clean_prices(a).height == 2


def test_open_outside_the_range_is_clipped():
    a = _prices([(100, 101, 99, 100, 100, 10), (120, 102, 99, 101, 100, 11)])
    assert clean_prices(a)["open"].to_list() == [100, 102]


def test_flows_that_do_not_add_up_are_dropped():
    p = _prices([(100, 101, 99, 100, 100, 10), (100, 101, 99, 100, 100, 11)])
    cols = {
        "buy_count_i": [1.0, 1.0], "buy_count_n": [0.0, 0.0],
        "sell_count_i": [1.0, 1.0], "sell_count_n": [0.0, 0.0],
        "buy_volume_i": [10.0, 5.0], "buy_volume_n": [0.0, 0.0],
        "sell_volume_i": [10.0, 11.0], "sell_volume_n": [0.0, 0.0],
        "buy_value_i": [1000.0, 500.0], "buy_value_n": [0.0, 0.0],
        "sell_value_i": [1000.0, 1100.0], "sell_value_n": [0.0, 0.0],
    }  # fmt: skip
    c = pl.DataFrame({"instrument_id": [1, 1], "date": p["date"], **cols})
    assert clean_clients(c, p)["date"].to_list() == [p["date"][0]]


def test_zero_reference_price_becomes_unknown():
    a = _prices([(100, 101, 99, 100, 0, 10), (100, 102, 99, 101, 100, 11)])
    assert clean_prices(a)["prev_close"].to_list() == [None, 100]
