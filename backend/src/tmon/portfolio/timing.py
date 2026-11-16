"""The time of day: is any quarter-hour of the session reliably cheaper to buy or dearer to sell?

``intraday_profile_daily`` keeps, for every 15-minute slice of past sessions, the time-weighted
mid price (and the extreme best-ask and best-bid, which this module deliberately does not rank on:
the opening quotes are the widest and noisiest, so those extremes always point at 09:00).

For each day every slice's mid is expressed against that day's own average. A slice counts as the
better time only if it passes an out-of-sample test: it is picked on the older half of the days and
must then show, on the newer half it was not picked on, a gap of at least :data:`MIN_EDGE` with a
t-statistic of at least :data:`T_CONFIRM`. Otherwise the answer says that no hour is reliably
better and shows how little the slices differ. That is the usual answer, and the honest one.

The day's low and high are also counted per slice, next to the share a driftless random price
would give the same slice (the first and last slices hold the extremes far more often than an even
split): a high share at the open is an effect of volatility, not a cheap hour.

Needs :data:`MIN_DAYS` of the stock's own days; otherwise the pooled days of all stocks are used
and labelled so. Nothing here is cached by time: the arrays are rebuilt only when the table's
fingerprint changes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.ingest.tsetmc.book_history import N_WINDOWS, WINDOW_SECONDS
from tmon.storage.models import Base, IntradayProfileDaily

MIN_DAYS = 20  # own days before a stock's own slices are shown
MIN_POOL_DAYS = 200  # symbol-days before the pooled market slices are shown
MIN_WINDOWS_PER_DAY = 8  # a day with fewer usable slices says little about its low or high
MIN_EDGE = 0.001  # the confirmed gap against the day's average must be at least 0.1 %
T_CONFIRM = 2.0  # and at least this many standard errors on the days it was not picked on
MIN_CONFIRM_DAYS = 8
NULL_PATHS = 20_000
HISTORY_DAYS = 120


def window_label(k: int) -> str:
    """«09:15–09:30» for slice 1."""
    a = k * WINDOW_SECONDS // 60
    b = (k + 1) * WINDOW_SECONDS // 60
    return f"{9 + a // 60:02d}:{a % 60:02d}–{9 + b // 60:02d}:{b % 60:02d}"


@dataclass(frozen=True)
class Slices:
    """One row per (symbol, day, slice); NaN where the book had no usable side."""

    iid: np.ndarray
    day: np.ndarray  # ordinal of the date
    win: np.ndarray
    mid: np.ndarray
    ask_min: np.ndarray
    bid_max: np.ndarray
    secs: np.ndarray


_memo: dict[tuple[object, ...], Slices | None] = {}


def ensure_table(session: Session) -> None:
    Base.metadata.create_all(session.get_bind(), tables=[IntradayProfileDaily.__table__])  # type: ignore[list-item]


def load(session: Session) -> Slices | None:
    """The last :data:`HISTORY_DAYS` days of slices; re-read only when the table changes."""
    ensure_table(session)
    stamp = (
        session.scalar(select(func.max(IntradayProfileDaily.date))),
        session.scalar(select(func.count()).select_from(IntradayProfileDaily)),
        # a re-fetched day keeps the date and the count but not the prices
        session.scalar(
            select(
                func.sum(
                    func.coalesce(IntradayProfileDaily.ask_min, 0)
                    + func.coalesce(IntradayProfileDaily.bid_max, 0)
                )
            )
        ),
    )
    if stamp in _memo:
        return _memo[stamp]
    _memo.clear()
    last = stamp[0]
    if not isinstance(last, dt.date) or not stamp[1]:
        _memo[stamp] = None
        return None
    rows = session.execute(
        select(
            IntradayProfileDaily.instrument_id,
            IntradayProfileDaily.date,
            IntradayProfileDaily.window,
            IntradayProfileDaily.mid,
            IntradayProfileDaily.ask_min,
            IntradayProfileDaily.bid_max,
            IntradayProfileDaily.secs,
        ).where(IntradayProfileDaily.date > last - dt.timedelta(days=HISTORY_DAYS))
    ).all()
    nan = float("nan")
    out = Slices(
        iid=np.array([r[0] for r in rows], dtype=np.int64),
        day=np.array([r[1].toordinal() for r in rows], dtype=np.int64),
        win=np.array([r[2] for r in rows], dtype=np.int64),
        mid=np.array([nan if r[3] is None else float(r[3]) for r in rows]),
        ask_min=np.array([nan if r[4] is None else float(r[4]) for r in rows]),
        bid_max=np.array([nan if r[5] is None else float(r[5]) for r in rows]),
        secs=np.array([0.0 if r[6] is None else float(r[6]) for r in rows]),
    )
    _memo[stamp] = out
    return out


@cache
def chance() -> tuple[np.ndarray, np.ndarray]:
    """Share of days whose lowest / highest slice mean falls in each slice for a price with no
    drift and no opening noise (a random walk, twenty steps per slice). The first and last slices
    hold the extremes far more often than 1 / N_WINDOWS."""
    rng = np.random.default_rng(20261116)
    path = np.cumsum(rng.standard_normal((NULL_PATHS, N_WINDOWS * 20)), axis=1)
    m = path.reshape(NULL_PATHS, N_WINDOWS, 20).mean(axis=2)
    lo = np.bincount(m.argmin(axis=1), minlength=N_WINDOWS) / NULL_PATHS
    hi = np.bincount(m.argmax(axis=1), minlength=N_WINDOWS) / NULL_PATHS
    return lo, hi


def _by_day(sl: Slices, mask: np.ndarray) -> list[dict[str, Any]]:
    """One record per (symbol, day) in ``mask``: each slice's mid against the day's average
    (NaN where the slice had no two-sided book) and the slices of the day's lowest and highest."""
    out: list[dict[str, Any]] = []
    keys = np.stack([sl.iid[mask], sl.day[mask]], axis=1)
    idx = np.flatnonzero(mask)
    if not len(idx):
        return out
    order = np.lexsort((keys[:, 1], keys[:, 0]))
    keys, idx = keys[order], idx[order]
    cut = np.flatnonzero(np.any(keys[1:] != keys[:-1], axis=1)) + 1
    for part in np.split(np.arange(len(idx)), cut):
        rows = idx[part]
        ok = np.isfinite(sl.mid[rows]) & (sl.secs[rows] > 0)
        if ok.sum() < MIN_WINDOWS_PER_DAY:
            continue
        fair = float(np.average(sl.mid[rows][ok], weights=sl.secs[rows][ok]))
        if fair <= 0:
            continue
        rel = np.full(N_WINDOWS, np.nan)
        rel[sl.win[rows][ok]] = sl.mid[rows][ok] / fair - 1
        out.append(
            {
                "day": int(sl.day[rows][0]),
                "rel": rel,
                "low_win": int(np.nanargmin(rel)),
                "high_win": int(np.nanargmax(rel)),
            }
        )
    return out


def _confirm(first: np.ndarray, second: np.ndarray, sign: int) -> dict[str, Any]:
    """Pick the slice on ``first`` (lowest mean for ``sign`` -1, highest for +1) and test it on
    ``second``. ``vs_day`` is the gap measured on the days it was not picked on."""
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(first, axis=0)
    seen = np.isfinite(first).sum(axis=0) >= MIN_CONFIRM_DAYS
    pick_from = np.where(seen & np.isfinite(mean), sign * mean, -np.inf)
    k = int(np.argmax(pick_from))
    x = second[:, k]
    x = x[np.isfinite(x)]
    res: dict[str, Any] = {"window": k, "label": window_label(k), "confirmed": False}
    if len(x) < MIN_CONFIRM_DAYS:
        return {**res, "vs_day": None, "t": None, "days": len(x)}
    m = float(x.mean())
    se = float(x.std(ddof=1)) / float(np.sqrt(len(x)))
    t = m / se if se > 0 else 0.0
    ok = sign * m >= MIN_EDGE and sign * t >= T_CONFIRM
    return {**res, "confirmed": bool(ok), "vs_day": m, "t": float(t), "days": len(x)}


def summarize(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Per-slice table, the out-of-sample best buying and selling slice and the share of days each
    slice held the day's low or high (with the share a random price gives it)."""
    if not days:
        return None
    days = sorted(days, key=lambda d: d["day"])
    m = np.vstack([d["rel"] for d in days])
    half = len(days) // 2
    buy = _confirm(m[:half], m[half:], -1)
    sell = _confirm(m[:half], m[half:], +1)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(m, axis=0)
    low = np.bincount([d["low_win"] for d in days], minlength=N_WINDOWS) / len(days)
    high = np.bincount([d["high_win"] for d in days], minlength=N_WINDOWS) / len(days)
    c_lo, c_hi = chance()
    table = [
        {
            "window": k,
            "label": window_label(k),
            "mid_vs_day": None if not np.isfinite(mean[k]) else float(mean[k]),
            "low_share": float(low[k]),
            "high_share": float(high[k]),
            "chance_low": float(c_lo[k]),
            "chance_high": float(c_hi[k]),
        }
        for k in range(N_WINDOWS)
    ]
    fin = mean[np.isfinite(mean)]
    return {
        "days": len(days),
        "table": table,
        "spread": float(fin.max() - fin.min()) if len(fin) else 0.0,
        "buy": buy,
        "sell": sell,
        "open_low_share": float(low[:2].sum()),
        "open_high_share": float(high[:2].sum()),
        "open_chance_low": float(c_lo[:2].sum()),
        "open_chance_high": float(c_hi[:2].sum()),
    }


def _pct(x: float, digits: int = 1) -> str:
    return f"{abs(x) * 100:.{digits}f}".replace(".", "٫")


def _headline(res: dict[str, Any]) -> str:
    b, s = res["buy"], res["sell"]
    if not b["confirmed"] and not s["confirmed"]:
        return (
            "ساعت مشخصی برای خرید یا فروش این نماد به‌طور معتبر بهتر نبوده؛ میانگین قیمت بازه‌های "
            f"۱۵ دقیقه‌ای حداکثر {_pct(res['spread'])}٪ با هم فرق دارد، پس قیمت سفارش مهم‌تر از "
            "ساعتِ سفارش است."
        )
    parts = []
    if b["confirmed"]:
        parts.append(
            f"خرید: {b['label']} (در روزهای آزمون‌شده {_pct(b['vs_day'])}٪ پایین‌تر از میانگین روز)"
        )
    else:
        parts.append("برای خرید ساعت معتبری پیدا نشد")
    if s["confirmed"]:
        parts.append(
            f"فروش: {s['label']} (در روزهای آزمون‌شده {_pct(s['vs_day'])}٪ بالاتر از میانگین روز)"
        )
    else:
        parts.append("برای فروش ساعت معتبری پیدا نشد")
    return "؛ ".join(parts) + "."


def time_of_day(session: Session, instrument_id: int) -> dict[str, Any]:
    """Whether any quarter-hour was reliably cheaper to buy or dearer to sell ``instrument_id``."""
    sl = load(session)
    base: dict[str, Any] = {
        "available": False,
        "basis": None,
        "out_of_sample": True,
        "slices": N_WINDOWS,
    }
    if sl is None:
        return {**base, "message": "هنوز دادهٔ ساعتی ذخیره نشده است."}
    own_mask = sl.iid == instrument_id
    own = _by_day(sl, own_mask)
    basis = "own"
    n = len(own)
    if n >= MIN_DAYS:
        res = summarize(own)
    else:
        pool = _by_day(sl, np.ones_like(own_mask))
        if len(pool) < MIN_POOL_DAYS:
            return {
                **base,
                "own_days": n,
                "message": "دادهٔ کافی برای ساعت بهتر خرید و فروش این نماد نیست.",
            }
        res = summarize(pool)
        basis, n = "market", len(pool)
    if res is None:
        return {**base, "message": "دادهٔ کافی نیست."}
    last = dt.date.fromordinal(int(sl.day.max()))
    notes = [
        "قیمتِ هر بازه (میانگین زمانیِ وسطِ خریدار و فروشنده) با میانگین همان روز سنجیده شده، نه "
        "با سفارشِ پرشده. یک ساعت وقتی «معتبر» است که روی نیمهٔ قدیمی‌تر تاریخچه انتخاب شود و روی "
        "نیمهٔ تازه‌تر، که در انتخاب نقش نداشته، هم دست‌کم ۰٫۱٪ فرق با t ≥ ۲ نشان دهد.",
        f"کمینهٔ روز در {_pct(res['open_low_share'], 0)}٪ روزها و بیشینهٔ روز در "
        f"{_pct(res['open_high_share'], 0)}٪ روزها در نیم‌ساعت اول افتاده (برای قیمتِ تصادفی "
        f"{_pct(res['open_chance_low'], 0)}٪ و {_pct(res['open_chance_high'], 0)}٪)؛ این نوسانِ "
        "آغاز بازار است، نه ارزان‌تر بودنِ آن ساعت.",
        "اثر ساعت روی بازدهٔ سفارش‌های واقعی هنوز آزموده نشده است (برآورد اولیه).",
    ]
    if res["buy"]["confirmed"] or res["sell"]["confirmed"]:
        notes.append(
            "آزمونی با t ≥ ۲ حدود ۲٫۵٪ موارد حتی بدون هیچ اثری تصادفاً می‌گذرد؛ این ساعت را "
            "سفارشِ قطعی نگیرید."
        )
    if basis == "market":
        notes.append("برای این نماد روز کافی نیست؛ از روزهای همهٔ نمادهای دارای داده استفاده شد.")
    return {
        **base,
        **res,
        "available": True,
        "basis": basis,  # own: this stock's days; market: all stocks' days pooled
        "basis_days": n,
        "last_day": last.isoformat(),
        "headline": _headline(res),
        "notes": notes,
    }
