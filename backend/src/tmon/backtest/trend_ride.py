"""Trend ride: an entry hint at the start of a run and a trailing exit.

Report: docs/reports/trend-ride-2026-11.md.

Entry signal on day t: the close is above its 50-day average, the 50-day average is above the
200-day one, and the close is within ``near_high`` of its 250-day high, while on t-1 this was not
all true. The buy is at the close of t+1; while that day is locked up (a buy queue) it moves a
day, for at most ``QUEUE_WAIT`` days. Exit signal: a close more than ``trail`` below the highest
close since the buy. The sale is at the next close;
while that day is locked down (a sell queue) it moves a day. A ride also ends after
``max_hold_days`` trading days, unless the trend still holds that day (close above its 50-day
average, which is above the 200-day one): then the ride goes on and the count and the trail's
highest close start again from that day (docs/reports/trend-marks-2026-11.md). While a ride is
open, new signals on the same symbol are ignored.

``swings`` marks the past lows and highs that only hindsight shows: a low is the lowest close
before the price rose ``trail`` or more, a high the highest close before it fell that much.

The rule was chosen from six entries and eight exits in the study; with the same exit, it beat
random entries in both halves of the last three years (mostly a rising market), but not from 2010
to mid-2018. The trailing exit beat a fixed hold of the same length in both windows. History here is
a description of past rides, not a forecast and not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl

G = "instrument_id"
QUEUE_WAIT = 20  # trading days a buy waits for a buy queue to open, as in the study
# A flat price (a halted or locked stock) makes the 50-day average equal the close, and prices in
# whole ticks can land exactly on a line (65% of the peak, 95% of the high); a rounding error of
# 1e-16 from the price adjustment then decides the side. Every comparison uses this relative
# margin, so a price on a line keeps the side its inequality names: at 95% of the high is near
# it, at 65% of the peak is not below it (docs/reports/trend-timing-2026-11.md).
EPS = 1e-9
C = pl.col


@dataclass(frozen=True)
class Ride:
    signal: int  # row of the signal day
    entry: int | None  # row of the buy; None while the buy is the next close
    exit_signal: int | None  # row whose close broke the trailing line
    exit: int | None  # row of the sale; None while it is the next close or the ride is open
    peak: int | None  # row of the highest close since the buy


def trending(close: np.ndarray, sma50: np.ndarray, sma200: np.ndarray) -> np.ndarray:
    """Close above the 50-day average above the 200-day one, by more than rounding."""
    k = 1 + EPS
    with np.errstate(invalid="ignore"):
        out: np.ndarray = (close > sma50 * k) & (sma50 > sma200 * k)
    return out


def entry_signals(
    close: np.ndarray, sma50: np.ndarray, sma200: np.ndarray, hi250: np.ndarray, near_high: float
) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        on = trending(close, sma50, sma200) & (close >= (1 - near_high) * hi250 * (1 - EPS))
    prev = np.concatenate([[True], on[:-1]])
    out: np.ndarray = on & ~prev
    return out


def rides(
    close: np.ndarray,
    locked_up: np.ndarray,
    locked_down: np.ndarray,
    signal: np.ndarray,
    trail: float,
    max_hold: int,
    trend: np.ndarray | None = None,
    same_day: bool = False,
) -> list[Ride]:
    """Every ride of one symbol, in order. Rows are the symbol's trading days. ``trend`` (one
    flag per row) renews a ride at ``max_hold`` instead of selling; without it the ride ends.
    With ``same_day`` the buy is at the close of the signal day and the sale at the close of the
    day that broke the line, unless that day is locked; otherwise both are at the next close."""
    n = len(close)
    out: list[Ride] = []
    busy = -1
    for t in map(int, np.flatnonzero(signal)):
        if t <= busy:
            continue
        e = t if same_day and not locked_up[t] else t + 1
        while e < n and locked_up[e] and e - t <= QUEUE_WAIT:
            e += 1
        if e >= n:
            out.append(Ride(t, None, None, None, None))
            break
        if locked_up[e]:
            continue
        pk = e
        hit = -1
        start = e  # the day the hold count runs from
        for j in range(e + 1, n):
            if close[j] > close[pk]:
                pk = j
            if close[j] < (1 - trail) * close[pk] * (1 - EPS):
                hit = j
                break
            if j - start >= max_hold:
                if trend is not None and trend[j]:
                    start = pk = j
                    continue
                hit = j
                break
        if hit < 0:
            out.append(Ride(t, e, None, None, pk))
            break
        x = hit if same_day and not locked_down[hit] else hit + 1
        while x < n and locked_down[x]:
            x += 1
        if x >= n:
            out.append(Ride(t, e, hit, None, pk))
            break
        out.append(Ride(t, e, hit, x, pk))
        busy = x
    return out


def _symbol_arrays(g: pl.DataFrame) -> dict[str, np.ndarray]:
    locked = (g["high"] == g["low"]).to_numpy()
    r = g["ret1"].fill_null(0.0).to_numpy()
    return {
        "close": g["close"].to_numpy().astype(float),
        "sma50": g["sma50"].to_numpy().astype(float),
        "sma200": g["sma200"].to_numpy().astype(float),
        "hi250": g["hi250"].to_numpy().astype(float),
        "up": locked & (r > EPS),  # a day with no change is not a queue either way
        "down": locked & (r < -EPS),
    }


def swings(close: np.ndarray, size: float) -> list[tuple[int, str]]:
    """Rows of the past lows ("low") and highs ("high") that a move of ``size`` or more followed,
    alternating, oldest first. The last extreme is left out until such a move confirms it."""
    out: list[tuple[int, str]] = []
    hi = lo = 0
    up: bool | None = None  # None until the first move of ``size``
    for j in range(1, len(close)):
        if up is None:
            if close[j] > close[hi]:
                hi = j
            if close[j] < close[lo]:
                lo = j
            if close[j] >= (1 + size) * close[lo] * (1 + EPS):
                out.append((lo, "low"))
                up, hi = True, j
            elif close[j] <= (1 - size) * close[hi] * (1 - EPS):
                out.append((hi, "high"))
                up, lo = False, j
        elif up:
            if close[j] > close[hi]:
                hi = j
            elif close[j] <= (1 - size) * close[hi] * (1 - EPS):
                out.append((hi, "high"))
                up, lo = False, j
        elif close[j] < close[lo]:
            lo = j
        elif close[j] >= (1 + size) * close[lo] * (1 + EPS):
            out.append((lo, "low"))
            up, hi = True, j
    return out


def all_rides(
    panel: pl.DataFrame, near_high: float, trail: float, max_hold: int, same_day: bool = False
) -> dict[int, tuple[pl.DataFrame, list[Ride]]]:
    out = {}
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        a = _symbol_arrays(g)
        sig = entry_signals(a["close"], a["sma50"], a["sma200"], a["hi250"], near_high)
        with np.errstate(invalid="ignore"):
            trend = trending(a["close"], a["sma50"], a["sma200"])
        rs = rides(a["close"], a["up"], a["down"], sig, trail, max_hold, trend, same_day)
        out[int(iid)] = (g.select("date", "close", "liquid"), rs)
    return out


def history(
    by_symbol: dict[int, tuple[pl.DataFrame, list[Ride]]],
    panel: pl.DataFrame,
    cost: float,
    since: date,
) -> dict[str, Any]:
    """Rides bought on or after ``since`` from a signal on a liquid day: net and excess over the
    liquid mean of the same days, for the whole span and for each half of the entry dates. A ride
    still open is valued at the last close, as in the study; ``open`` counts them, because most
    winners of the newer half are still running and counting only finished rides would leave
    mostly the losers."""
    mk = (
        panel.filter(C("liquid"))
        .group_by("date")
        .agg(m=C("ret1").clip(-0.3, 0.3).mean())
        .sort("date")
        .with_columns(lvl=(1 + C("m").fill_null(0)).cum_prod())
    )
    lvl = dict(zip(mk["date"].to_list(), mk["lvl"].to_list(), strict=True))
    rows = []
    for g, rs in by_symbol.values():
        d, c, liq = g["date"].to_list(), g["close"].to_numpy(), g["liquid"].to_numpy()
        for r in rs:
            if r.entry is None or not liq[r.signal] or d[r.entry] < since:
                continue
            end = len(d) - 1 if r.exit is None else r.exit
            if d[r.entry] not in lvl or d[end] not in lvl:
                continue
            net = c[end] / c[r.entry] - 1 - cost
            mkt = lvl[d[end]] / lvl[d[r.entry]] - 1
            rows.append((d[r.entry], net, net - mkt, end - r.entry, r.exit is None))
    if not rows:
        return {"n": 0}
    df = pl.DataFrame(rows, schema=["entry", "net", "excess", "hold", "open"], orient="row").sort(
        "entry"
    )
    split = df["entry"][df.height // 2]

    def block(x: pl.DataFrame) -> dict[str, Any]:
        return {
            "n": x.height,
            "open": int(x["open"].sum()),
            "net_mean": float(x["net"].mean()),  # type: ignore[arg-type]
            "net_median": float(x["net"].median()),  # type: ignore[arg-type]
            "excess_mean": float(x["excess"].mean()),  # type: ignore[arg-type]
            "win": float((x["net"] > 0).mean()),  # type: ignore[arg-type]
            "hold_median": float(x["hold"].median()),  # type: ignore[arg-type]
        }

    return {
        **block(df),
        "first": str(df["entry"][0]),
        "last": str(df["entry"][-1]),
        "split_date": str(split),
        "halves": [block(df.filter(C("entry") < split)), block(df.filter(C("entry") >= split))],
    }


def buy_trigger(close: np.ndarray, near_high: float) -> float | None:
    """The lowest close for the next day that would be an entry signal, from the closes so far;
    None when today is already in the entry state (a signal needs its first day) or the history
    is under 250 days. The three conditions each hold above one price, because the next close
    also enters the averages and the 250-day high:

    - over its own 50-day average: x > (sum of the last 49) / 49;
    - 50-day average over the 200-day one: x > (S199 / 200 - S49 / 50) / (1/50 - 1/200);
    - near the high: x >= (1 - near_high) * (highest of the last 249).
    """
    c = close
    if len(c) < 250:
        return None
    s50, s200 = c[-50:].mean(), c[-200:].mean()
    on = bool(trending(c[-1:], np.array([s50]), np.array([s200]))[0])
    if on and c[-1] >= (1 - near_high) * c[-250:].max() * (1 - EPS):
        return None
    s49, s199 = c[-49:].sum(), c[-199:].sum()
    need = max(
        s49 / 49,
        (s199 / 200 - s49 / 50) / (1 / 50 - 1 / 200),
        (1 - near_high) * c[-249:].max(),
    )
    return float(need * (1 + 1e-6))


def current(
    g: pl.DataFrame,
    rs: list[Ride],
    trail: float,
    near_high: float | None = None,
) -> dict[str, Any] | None:
    """The symbol's latest ride, as the page needs it; None when it never had one."""
    if not rs:
        return None
    r = rs[-1]
    d, c = g["date"].to_list(), g["close"].to_numpy()
    last = len(c) - 1

    def day(i: int | None) -> str | None:
        return None if i is None else str(d[i])

    def px(i: int | None) -> float | None:
        return None if i is None else float(c[i])

    if r.entry is None:
        status = "buy_next"
    elif r.exit_signal is None:
        status = "open"
    elif r.exit is None:
        status = "sell_next"
    else:
        status = "closed"
    peak = px(r.peak)
    end = r.exit if r.exit is not None else last
    stop = None if peak is None or status == "closed" else peak * (1 - trail)
    past = []
    for q in rs:
        if q.entry is None:
            continue
        q_end = q.exit if q.exit is not None else last
        past.append(
            {
                "entry_date": day(q.entry),
                "exit_date": day(q.exit),
                "gain": float(c[q_end] / c[q.entry] - 1),
            }
        )
    return {
        "rides": past,
        "swings": [
            {"date": str(d[i]), "kind": k, "close": float(c[i])} for i, k in swings(c, trail)
        ],
        "status": status,
        "signal_date": day(r.signal),
        "signal_close": px(r.signal),
        "entry_date": day(r.entry),
        "entry_close": px(r.entry),
        "peak_date": day(r.peak),
        "peak_close": peak,
        "stop": stop,
        "buy_trigger": None
        if status != "closed" or near_high is None
        else buy_trigger(c, near_high),
        # the largest rise from one close to the next in the last 250 days: a trigger further
        # than this from today's close will not be reached tomorrow
        "day_rise_max": float((c[-250:][1:] / c[-250:][:-1]).max() - 1) if len(c) > 1 else None,
        "exit_signal_date": day(r.exit_signal),
        "exit_date": day(r.exit),
        "exit_close": px(r.exit),
        "last_date": str(d[last]),
        "last_close": float(c[last]),
        "gain": None if r.entry is None else float(c[end] / c[r.entry] - 1),
        "days_since_exit": None if r.exit is None else last - r.exit,
    }
