"""Entry odds (tmon.backtest.entry_odds): streaks, the win/loss race, labels and the readings."""

from __future__ import annotations

import numpy as np
import polars as pl

from test_ta_signals import _world
from tmon.api.entry import entry_out, verdict
from tmon.backtest import entry_odds as eo

C = pl.col


def _with_closes(closes: list[float]) -> pl.DataFrame:
    prices, flows = _world(n=len(closes))
    c = np.array(closes, dtype=float)
    prices = prices.with_columns(
        close=pl.Series(c),
        last=pl.Series(c),
        open=pl.Series(c),
        high=pl.Series(c * 1.001),
        low=pl.Series(c * 0.999),
        prev_close=pl.Series(np.r_[np.nan, c[:-1]]).fill_nan(None),
    )
    return eo.prepare(prices, flows).sort("date")


def _day(p: pl.DataFrame, n: int, i: int) -> dict:
    """Row of input day ``i`` of ``n`` (prepare drops the warm-up days at the start)."""
    return p.row(p.height - (n - i), named=True)


def test_streaks_count_green_and_red_candles_in_a_row() -> None:
    closes = [100.0] * 300 + [101, 102, 103, 102, 101, 101, 102]
    p = _with_closes(closes)
    tail = p.tail(7)
    assert tail["green"].to_list() == [1, 2, 3, 0, 0, 0, 1]
    assert tail["red"].to_list() == [0, 0, 0, 1, 2, 0, 0]


def test_race_and_dip_follow_the_closes_after_the_entry_day() -> None:
    base = [100.0] * 300
    # entry at the close of day t+1 (=100); +11% on t+3 comes before any -5%
    w = base + [100, 100, 104, 111] + [111] * 25
    assert _day(_with_closes(w), len(w), 299)["race"] == 1
    # -6% on t+2 comes first, then +12%: the loss is what happened first
    lo = base + [100, 100, 94, 100, 112] + [112] * 25
    r = _day(_with_closes(lo), len(lo), 299)
    assert r["race"] == -1
    assert r["dip_hit"] == 1.0
    # nothing hit within PATH candles: a full flat path is a draw
    fl = base + [100.0] * 30
    flat = _with_closes(fl)
    assert _day(flat, len(fl), 299)["race"] == 0
    # the path after the last days is unknown: no score rather than a guess
    assert flat.tail(1)["race"].to_list() == [None]


def _part(n: int, edges: dict[int, float]) -> dict:
    return {
        "n": n,
        **{f"h{h}": {"edge": e, "up": 0.5, "up_all": 0.5 - e} for h, e in edges.items()},
    }


def test_label_needs_both_halves_to_agree() -> None:
    both = [_part(500, {1: 0.05, 5: 0.04}), _part(500, {1: 0.04, 5: 0.01})]
    assert eo._label(_part(1000, {1: 0.045, 5: 0.02}), both) == ("better", 1)
    one = [_part(500, {1: 0.10}), _part(500, {1: 0.01})]
    assert eo._label(_part(1000, {1: 0.05}), one) == ("same", None)
    worse = [_part(500, {1: -0.08}), _part(500, {1: -0.05})]
    assert eo._label(_part(1000, {1: -0.06}), worse) == ("worse", 1)
    mixed = [_part(500, {1: 0.05, 20: -0.05}), _part(500, {1: 0.04, 20: -0.04})]
    assert eo._label(_part(1000, {1: 0.04, 20: -0.04}), mixed)[0] == "mixed"
    assert eo._label(_part(eo.MIN_N - 1, {1: 0.2}), both) == ("too_few", None)


def test_history_and_current_on_a_small_exchange() -> None:
    prices, flows = _world(n=500, symbols=4)
    p = eo.flags(eo.prepare(prices, flows))
    h = eo.history(p)
    assert set(h["setups"]) == set(eo.SETUPS)
    labels = {s["label"] for s in h["setups"].values()}
    assert labels <= {"better", "worse", "same", "mixed", "too_few"}
    anyday = h["setups"]["any"]
    # the baseline is every liquid day: its own edge is zero by construction
    assert anyday["h1"] is None or abs(anyday["h1"]["edge"]) < 1e-9
    now = eo.current(p)
    assert set(now) == {1, 2, 3, 4}
    for s in now.values():
        assert not (s["green"] and s["red"])
        assert all(m["ago"] < eo.MARKS_DAYS for m in s["marks"])


def _setup(label: str, **kw) -> dict:
    hz = {f"h{h}": {"n": 900, "up": 0.52, "up_all": 0.43, "edge": 0.09} for h in eo.H}
    return {
        "group": "streak",
        "title": "شش شمع سبز یا بیشتر",
        "event": False,
        "label": label,
        "best_h": 1 if label == "better" else None,
        "n": 900,
        "symbols": 50,
        "halves": [hz, hz],
        **hz,
        **kw,
    }


def test_readings_follow_the_numbers() -> None:
    assert "۵۲" not in verdict(_setup("better"))  # digits stay Latin; the page converts them
    assert "52 بار از ۱۰۰" in verdict(_setup("better"))
    assert "بیشتر از بقیهٔ سهم‌ها" in verdict(_setup("better"))
    assert "نمونه کم" in verdict(_setup("too_few"))
    doc = {
        "as_of": "2026-11-11",
        "horizons": list(eo.H),
        "setups": {"g6": _setup("better")},
        "now": {
            "7": {
                "green": 1, "red": 0, "in_base": True, "in_up": False, "dd": -0.4,
                "rng60": 0.2, "active": ["g6", "gone"],
                "marks": [{"key": "g6", "date": "2026-11-10", "ago": 1}],
            }
        },
    }  # fmt: skip
    e = entry_out(doc, 7)
    assert e is not None
    assert [s.key for s in e.now] == ["g6"]  # an unknown key is dropped, not invented
    assert e.marks[0].label == "better"
    assert e.lines[0] == "آخرین شمع سبز بوده و شمع پیش از آن سبز نبوده است."
    assert "40٪ زیر سقف" in e.lines[1]
    assert entry_out(doc, 8) is None


def test_wilson_interval_widens_with_fewer_tries() -> None:
    lo, hi = eo.wilson(50, 100)
    assert lo < 0.5 < hi
    lo2, hi2 = eo.wilson(500, 1000)
    assert hi2 - lo2 < hi - lo


def test_forecast_reads_the_symbols_own_record() -> None:
    from tmon.api.entry import forecast
    from tmon.api.schemas import OwnOdds

    coin = OwnOdds(h=5, n=700, eff=140, up=0.5, lo=0.42, hi=0.58, up_all=0.47, q10=-0.06, q90=0.09)
    lines = forecast([coin], [])
    assert "شانس بالاتر بودن از قیمت خرید 50٪" in lines[0] and "42" not in lines[0]
    assert "−6٪" in lines[0] and "+9٪" in lines[0]
    assert "شیر یا خط" in lines[1]
    up = coin.model_copy(update={"up": 0.6, "lo": 0.55, "hi": 0.65})
    assert "بیشتر بالا رفته" in forecast([up], [])[1]
    assert forecast([], []) == []


def test_year_starts_at_nowruz() -> None:
    import datetime as dt

    assert eo.year_start(dt.date(2026, 11, 11)) == dt.date(2026, 3, 21)
    assert eo.year_start(dt.date(2026, 2, 1)) == dt.date(2025, 3, 21)


def test_years_split_at_nowruz_and_count_only_full_years() -> None:
    import datetime as dt

    import polars as pl

    from tmon.backtest.entry_odds import _years, year_count

    days = [dt.date(2024, 3, 20)] * 60 + [dt.date(2024, 3, 21)] * 10
    sub = pl.DataFrame(
        {
            "date": days,
            **{f"f{h}": [0.01] * 60 + [-0.01] * 10 for h in (1, 5, 20)},
            **{f"ub{h}": [0.4] * 70 for h in (1, 5, 20)},
        }
    )
    ys = _years(sub)
    assert [(y["year"], y["n"]) for y in ys] == [(1402, 60), (1403, 10)]
    assert abs(ys[0]["e5"] - 0.6) < 1e-9
    assert year_count(ys, 5) == {"better": 1, "worse": 0, "same": 0}
