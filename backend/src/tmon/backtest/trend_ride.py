"""Trend ride: an entry hint at the start of a run and a trailing exit.

Report: docs/reports/trend-ride-2026-11.md.

Entry signal on day t: the close is above its 50-day average, the 50-day average is above the
200-day one, and the close is within ``near_high`` of its 250-day high, while on t-1 this was not
all true. The buy is at the close of t+1; while that day is locked up (a buy queue) it moves a
day, for at most ``QUEUE_WAIT`` days. Exit signal: a close more than ``trail`` below the highest
close since the buy. The sale is at the next close;
while that day is locked down (a sell queue) it moves a day. A ride also ends after
``max_hold_days`` trading days. While a ride is open, new signals on the same symbol are ignored.

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
C = pl.col


@dataclass(frozen=True)
class Ride:
    signal: int  # row of the signal day
    entry: int | None  # row of the buy; None while the buy is the next close
    exit_signal: int | None  # row whose close broke the trailing line
    exit: int | None  # row of the sale; None while it is the next close or the ride is open
    peak: int | None  # row of the highest close since the buy


def entry_signals(
    close: np.ndarray, sma50: np.ndarray, sma200: np.ndarray, hi250: np.ndarray, near_high: float
) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        on = (close > sma50) & (sma50 > sma200) & (close >= (1 - near_high) * hi250)
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
) -> list[Ride]:
    """Every ride of one symbol, in order. Rows are the symbol's trading days."""
    n = len(close)
    out: list[Ride] = []
    busy = -1
    for t in map(int, np.flatnonzero(signal)):
        if t <= busy:
            continue
        e = t + 1
        while e < n and locked_up[e] and e - t <= QUEUE_WAIT:
            e += 1
        if e >= n:
            out.append(Ride(t, None, None, None, None))
            break
        if locked_up[e]:
            continue
        pk = e
        hit = -1
        for j in range(e + 1, n):
            if close[j] > close[pk]:
                pk = j
            if close[j] < (1 - trail) * close[pk] or j - e >= max_hold:
                hit = j
                break
        if hit < 0:
            out.append(Ride(t, e, None, None, pk))
            break
        x = hit + 1
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
        "up": locked & (r > 0),
        "down": locked & (r < 0),
    }


def all_rides(
    panel: pl.DataFrame, near_high: float, trail: float, max_hold: int
) -> dict[int, tuple[pl.DataFrame, list[Ride]]]:
    out = {}
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        a = _symbol_arrays(g)
        sig = entry_signals(a["close"], a["sma50"], a["sma200"], a["hi250"], near_high)
        rs = rides(a["close"], a["up"], a["down"], sig, trail, max_hold)
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


def current(
    g: pl.DataFrame,
    rs: list[Ride],
    trail: float,
    buy_range: tuple[float, float] | None = None,
    sell_range: tuple[float, float] | None = None,
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
    sig_close = px(r.signal)
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
        "status": status,
        "signal_date": day(r.signal),
        "signal_close": px(r.signal),
        "entry_date": day(r.entry),
        "entry_close": px(r.entry),
        "peak_date": day(r.peak),
        "peak_close": peak,
        "stop": stop,
        # 80% price ranges: where the buy has landed against the signal close, and where a sale
        # has landed against the stop line (docs/reports/trend-ranges-2026-11.md)
        "buy_low": None
        if buy_range is None or sig_close is None
        else sig_close * (1 + buy_range[0]),
        "buy_high": None
        if buy_range is None or sig_close is None
        else sig_close * (1 + buy_range[1]),
        "stop_low": None if sell_range is None or stop is None else stop * sell_range[0],
        "stop_high": None if sell_range is None or stop is None else stop * sell_range[1],
        "exit_signal_date": day(r.exit_signal),
        "exit_date": day(r.exit),
        "exit_close": px(r.exit),
        "last_date": str(d[last]),
        "last_close": float(c[last]),
        "gain": None if r.entry is None else float(c[end] / c[r.entry] - 1),
        "days_since_exit": None if r.exit is None else last - r.exit,
    }
