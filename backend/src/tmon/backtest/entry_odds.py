"""Entry odds: after a given candle, how often were the next candles green, and how often did
the price dip first (docs/reports/entry-odds-2026-11.md).

The question this answers is the buyer's: "if I buy now, what are the chances the next candles
are green, and how likely is a sharp dip before a gain?" Each *setup* is a condition on the signal
day ``t`` fixed before any result was looked at: green and red streaks, entry candles inside a
months-long base near the bottom, and pullbacks inside an uptrend. Entry is the close of ``t+1``
(the first price one can actually get after seeing the candle), on adjusted prices, and entries
probably locked at the upper limit (``ta_signals.LOCK_MOVE``) are dropped because nobody could buy.

For every setup and horizon ``h`` (1 to 20 candles after entry) we keep the share of entries that
were up, next to the share for every liquid symbol one could have bought on the same days, and the
mean excess return over those symbols. Path risk: the chance of a close 5% below entry within 10
candles, and of reaching +10% before -5% (or the reverse) within 20 candles, both against the same
days' universe. A setup is "better" only when its up-share beats the same days' by ``DIR_EDGE`` in
both halves of the history, and "worse" when it trails by as much in both halves.

These are base rates of the past on the whole market, not a forecast for one symbol and not advice.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest import ta_signals as ts

G = "instrument_id"
C = pl.col
H = (1, 3, 5, 10, 20)
PATH = 20  # candles followed after entry for the win/loss race
DIP = -0.05  # "a 5% dip"
DIP_WITHIN = 10
WIN, LOSS = 0.10, -0.05  # the race: +10% before -5%
DIR_EDGE = 0.03
MIN_N = 200
RECENT = 5  # an entry event is "current" when it fired in the symbol's last 5 trading days
MARKS_DAYS = 250  # chart markers for the last year
OWN_H = H
OWN_MIN = 20  # fewer own entries than this: no own odds
Z95 = 1.96
BASE_DD = -0.30  # at least 30% under the 52-week high ...
BASE_RANGE = 0.25  # ... and the last 60 closes within a 25% band: months near the bottom
BASE_DAYS = 60
lag, turns_on, cross_up = ts.lag, ts.turns_on, ts.cross_up
cl = C("close")


def prepare(prices: pl.DataFrame, clients: pl.DataFrame) -> pl.DataFrame:
    """Indicators, outcomes, streaks, the base and uptrend flags and the path outcomes."""
    p = ts.with_outcomes(ts.indicators(prices, clients))
    d = pl.when(C("ret1") > 0).then(1).when(C("ret1") < 0).then(-1).otherwise(0)
    p = p.with_columns(dir=d)
    p = p.with_columns(run=(C("dir") != lag(C("dir"))).fill_null(True).cum_sum().over(G))
    p = p.with_columns(streak=pl.int_range(1, pl.len() + 1).over(G, "run"))
    p = p.with_columns(
        green=pl.when(C("dir") == 1).then(C("streak")).otherwise(0),
        red=pl.when(C("dir") == -1).then(C("streak")).otherwise(0),
        hi60=lag(ts.roll(cl, "max", BASE_DAYS)),
        lo60=lag(ts.roll(cl, "min", BASE_DAYS)),
        rng60=ts.roll(cl, "max", BASE_DAYS) / ts.roll(cl, "min", BASE_DAYS) - 1,
    )
    p = p.with_columns(
        in_base=(C("dd") <= BASE_DD) & (C("rng60") <= BASE_RANGE),
        in_up=(C("sma20") > C("sma50")) & (C("sma50") > C("sma200")) & (cl > C("sma50")),
    )
    entry = lag(cl, -1)
    path = [(lag(cl, -1 - k) / entry - 1) for k in range(1, PATH + 1)]
    never = PATH + 1
    first_up = pl.min_horizontal(
        [pl.when(f >= WIN).then(k).otherwise(never) for k, f in enumerate(path, 1)]
    )
    first_dn = pl.min_horizontal(
        [pl.when(f <= LOSS).then(k).otherwise(never) for k, f in enumerate(path, 1)]
    )
    # a day that hits both is counted as the loss (the cautious reading); a race is only scored
    # when it ended or the whole PATH is known
    full = lag(cl, -1 - PATH).is_not_null()
    race = (
        pl.when((first_dn < never) & (first_dn <= first_up))
        .then(pl.lit(-1, dtype=pl.Int8))
        .when(first_up < never)
        .then(pl.lit(1, dtype=pl.Int8))
        .when(full)
        .then(pl.lit(0, dtype=pl.Int8))
    )
    p = p.with_columns(dip=pl.min_horizontal(path[:DIP_WITHIN]), race=race)
    keep = C("liquid") & ~C("entry_up_locked")
    p = p.with_columns(
        dip_hit=pl.when(lag(cl, -1 - DIP_WITHIN).is_not_null()).then(
            (C("dip") <= DIP).cast(pl.Float64)
        ),
        win=pl.when(C("race").is_not_null()).then((C("race") == 1).cast(pl.Float64)),
        loss=pl.when(C("race").is_not_null()).then((C("race") == -1).cast(pl.Float64)),
    )
    # the same days' universe (liquid, not locked) for the path numbers
    return p.with_columns(
        *[
            C(c).filter(keep & C(c).is_not_null()).mean().over("date").alias(f"{c}_all")
            for c in ("dip_hit", "win", "loss")
        ]
    )


# key: (group, plain Persian title, condition on the signal day, event?)
SETUPS: dict[str, tuple[str, str, pl.Expr, bool]] = {
    "any": ("all", "هر روز، هر سهم (مبنا)", pl.lit(True), False),
    "g1": ("streak", "اولین شمع سبز بعد از قرمز", C("green") == 1, False),
    "g2": ("streak", "دو شمع سبز پشت سر هم", C("green") == 2, False),
    "g3": ("streak", "سه شمع سبز پشت سر هم", C("green") == 3, False),
    "g45": ("streak", "چهار یا پنج شمع سبز پشت سر هم", C("green").is_between(4, 5), False),
    "g6": ("streak", "شش شمع سبز یا بیشتر", C("green") >= 6, False),
    "r1": ("streak", "اولین شمع قرمز بعد از سبز", C("red") == 1, False),
    "r2": ("streak", "دو شمع قرمز پشت سر هم", C("red") == 2, False),
    "r3": ("streak", "سه شمع قرمز پشت سر هم", C("red") == 3, False),
    "r45": ("streak", "چهار یا پنج شمع قرمز پشت سر هم", C("red").is_between(4, 5), False),
    "r6": ("streak", "شش شمع قرمز یا بیشتر", C("red") >= 6, False),
    "base_any": ("base", "یک روز معمولی در کف چندماهه (مبنای کف)", C("in_base"), False),
    "base_breakout": (
        "base",
        "بسته شدن بالای سقف ۶۰ روزهٔ کف",
        C("in_base").shift(1).over(G) & turns_on(cl > C("hi60")),
        True,
    ),
    "base_ma20": (
        "base",
        "بسته شدن بالای میانگین ۲۰ روزه در کف",
        C("in_base") & cross_up(cl, C("sma20")),
        True,
    ),
    "base_ma50": (
        "base",
        "بسته شدن بالای میانگین ۵۰ روزه در کف",
        C("in_base") & cross_up(cl, C("sma50")),
        True,
    ),
    "base_vol": (
        "base",
        "شمع سبز با حجم بیش از ۲ برابر میانگین در کف",
        C("in_base") & turns_on((C("vr") > 2) & (C("ret1") > 0)),
        True,
    ),
    "base_first_green": (
        "base",
        "اولین شمع سبز بعد از سه قرمز یا بیشتر در کف",
        C("in_base") & (C("green") == 1) & (lag(C("red")) >= 3),
        True,
    ),
    "base_rsi30": (
        "base",
        "برگشت RSI به بالای ۳۰ در کف",
        C("in_base") & (C("rsi") > 30) & (lag(C("rsi")) <= 30),
        True,
    ),
    "base_flow": (
        "base",
        "ورود پول حقیقی (۵ روز) در کف",
        C("in_base") & turns_on((C("net5") >= 0.05) & (C("power5") >= 1.2)),
        True,
    ),
    "base_new_low": (
        "base",
        "شکستن کف ۶۰ روزه (بسته شدن زیر کف)",
        C("in_base").shift(1).over(G) & turns_on(cl < C("lo60")),
        True,
    ),
    "up_any": ("uptrend", "یک روز معمولی در روند صعودی (مبنای روند)", C("in_up"), False),
    "up_red2": (
        "uptrend",
        "دو شمع قرمز پشت سر هم در روند صعودی",
        C("in_up") & (C("red") == 2),
        True,
    ),
    "up_touch20": (
        "uptrend",
        "اصلاح تا میانگین ۲۰ روزه در روند صعودی",
        C("in_up") & turns_on((C("low") <= C("sma20")) & (cl > C("sma20"))),
        True,
    ),
    "up_high": (
        "uptrend",
        "سقف تازهٔ ۵۲ هفته در روند صعودی",
        C("in_up") & turns_on(cl > C("hi250")),
        True,
    ),
    "up_g4": (
        "uptrend",
        "چهار شمع سبز یا بیشتر در روند صعودی",
        C("in_up") & (C("green") == 4),
        True,
    ),
}

GROUPS = {
    "all": "مبنا",
    "streak": "حالا که سبز (یا قرمز) است، ادامه می‌دهد؟",
    "base": "سهمی که ماه‌ها در کف بوده: کدام شمع؟",
    "uptrend": "در روند صعودی: کی وارد شویم؟",
}


def flags(p: pl.DataFrame) -> pl.DataFrame:
    return p.with_columns(
        *[e.fill_null(False).alias("e_" + k) for k, (_, _, e, _) in SETUPS.items()]
    )


def _f(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x)
    return None if np.isnan(v) else v


def _mean(s: pl.Series) -> float | None:
    s = s.drop_nulls()
    return _f(s.mean()) if s.len() else None


def _part(sub: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": sub.height}
    for h in H:
        ok = sub.filter(C(f"f{h}").is_not_null() & C(f"ub{h}").is_not_null())
        if ok.height < 30:
            out[f"h{h}"] = None
            continue
        up = _mean((ok[f"f{h}"] > 0).cast(pl.Float64))
        up_all = _mean(ok[f"ub{h}"])
        out[f"h{h}"] = {
            "n": ok.height,
            "up": up,
            "up_all": up_all,
            "edge": None if up is None or up_all is None else up - up_all,
            "excess_mean": _mean(ok[f"xb{h}"]),
            "median": _f(ok[f"f{h}"].median()),
        }
    for c in ("dip_hit", "win", "loss"):
        ok = sub.filter(C(c).is_not_null())
        out[c] = _mean(ok[c]) if ok.height >= 30 else None
        out[c + "_all"] = _mean(ok[c + "_all"]) if ok.height >= 30 else None
    d = sub["dip"].drop_nulls()
    out["dip_median"] = _f(d.median()) if d.len() >= 30 else None
    return out


def _label(whole: dict[str, Any], halves: list[dict[str, Any]]) -> tuple[str, int | None]:
    """``better``/``worse`` when both halves agree by DIR_EDGE at some horizon and no horizon
    agrees the other way; the horizon it held best at; ``too_few`` under MIN_N entries."""
    if whole["n"] < MIN_N:
        return "too_few", None
    agree: dict[int, int] = {}
    for h in H:
        e = [(b.get(f"h{h}") or {}).get("edge") for b in halves]
        if any(x is None for x in e):
            continue
        if all(x >= DIR_EDGE for x in e):  # type: ignore[operator]
            agree[h] = 1
        elif all(x <= -DIR_EDGE for x in e):  # type: ignore[operator]
            agree[h] = -1
    pos = [h for h, v in agree.items() if v > 0]
    neg = [h for h, v in agree.items() if v < 0]
    if pos and not neg:
        return "better", max(pos, key=lambda h: (whole.get(f"h{h}") or {}).get("edge") or 0)
    if neg and not pos:
        return "worse", min(neg, key=lambda h: (whole.get(f"h{h}") or {}).get("edge") or 0)
    return ("mixed" if pos and neg else "same"), None


YEAR_H = (1, 5, 20)
YEAR_MIN = 50  # a year with fewer entries than this is shown but not counted


def _years(sub: pl.DataFrame) -> list[dict[str, Any]]:
    """The setup's edge over every liquid symbol on the same days, Iranian year by year
    (Nowruz to Nowruz): each year's market is different, so a setup that only worked in a few
    years shows it here."""
    y = sub.with_columns(
        fy=pl.when(
            (C("date").dt.month() > 3) | ((C("date").dt.month() == 3) & (C("date").dt.day() >= 21))
        )
        .then(C("date").dt.year() - 621)
        .otherwise(C("date").dt.year() - 622)
    )
    aggs = [pl.len().alias("n")]
    for h in YEAR_H:
        ok = C(f"f{h}").is_not_null() & C(f"ub{h}").is_not_null()
        aggs.append(
            (
                (C(f"f{h}") > 0).cast(pl.Float64).filter(ok).mean() - C(f"ub{h}").filter(ok).mean()
            ).alias(f"e{h}")
        )
    out = []
    for r in y.group_by("fy").agg(aggs).sort("fy").iter_rows(named=True):
        out.append(
            {"year": int(r["fy"]), "n": int(r["n"]), **{f"e{h}": _f(r[f"e{h}"]) for h in YEAR_H}}
        )
    return out


def year_count(years: list[dict[str, Any]], h: int) -> dict[str, int]:
    """How many counted years (YEAR_MIN entries or more) the setup was above, below or within
    DIR_EDGE of every other symbol at h candles."""
    c = {"better": 0, "worse": 0, "same": 0}
    for y in years:
        e = y.get(f"e{h}")
        if y["n"] < YEAR_MIN or e is None:
            continue
        c["better" if e >= DIR_EDGE else "worse" if e <= -DIR_EDGE else "same"] += 1
    return c


def history(p: pl.DataFrame) -> dict[str, Any]:
    liq = p.filter(C("liquid") & ~C("entry_up_locked"))
    days = liq["date"].unique().sort()
    split = days[len(days) // 2]
    out: dict[str, Any] = {
        "split_date": str(split),
        "first": str(days[0]),
        "last": str(days[-1]),
        "setups": {},
    }
    locked_all = p.filter(C("liquid"))
    for k, (group, title, _, event) in SETUPS.items():
        sub = liq.filter(C("e_" + k))
        whole = _part(sub)
        halves = [_part(sub.filter(C("date") < split)), _part(sub.filter(C("date") >= split))]
        label, best = _label(whole, halves)
        fired = locked_all.filter(C("e_" + k))
        out["setups"][k] = {
            "group": group,
            "title": title,
            "event": event,
            **whole,
            "symbols": sub[G].n_unique(),
            "halves": halves,
            "years": _years(sub),
            "label": label,
            "best_h": best,
            # entries dropped because the next day was probably locked at the upper limit
            "locked_share": _f(fired["entry_up_locked"].mean()) if fired.height else None,
        }
    return out


def current(p: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """Each symbol's last day: streaks, base/uptrend, the setups true now (or fired in the last
    RECENT days for entry events) and the entry events of its last year for the chart."""
    s = p.sort(G, "date")
    keys = list(SETUPS)
    last = s.group_by(G).agg(
        *[C(c).last() for c in ("date", "green", "red", "in_base", "in_up", "dd", "rng60")]
    )
    tail = (
        s.group_by(G).tail(MARKS_DAYS).with_columns(ago=pl.int_range(pl.len(), 0, -1).over(G) - 1)
    )
    ev = [k for k in keys if SETUPS[k][3]]
    long = (
        tail.select(G, "date", "ago", *["e_" + k for k in ev])
        .unpivot(index=[G, "date", "ago"], variable_name="k", value_name="on")
        .filter(C("on"))
        .sort(G, "date")
    )
    marks: dict[int, list[dict[str, Any]]] = {}
    for r in long.iter_rows(named=True):
        marks.setdefault(int(r[G]), []).append(
            {"key": r["k"][2:], "date": str(r["date"]), "ago": int(r["ago"])}
        )
    own = _own(s)
    now_states = s.group_by(G).agg(*[C("e_" + k).last() for k in keys if not SETUPS[k][3]])
    st = {int(r[G]): r for r in now_states.iter_rows(named=True)}
    out: dict[int, dict[str, Any]] = {}
    for r in last.iter_rows(named=True):
        i = int(r[G])
        ms = marks.get(i, [])
        active = [k for k in keys if not SETUPS[k][3] and k != "any" and st[i]["e_" + k]]
        active += sorted({m["key"] for m in ms if m["ago"] < RECENT})
        out[i] = {
            "date": str(r["date"]),
            "green": int(r["green"] or 0),
            "red": int(r["red"] or 0),
            "in_base": bool(r["in_base"]),
            "in_up": bool(r["in_up"]),
            "dd": _f(r["dd"]),
            "rng60": _f(r["rng60"]),
            "active": active,
            "marks": ms,
            "own": own.get(i),
        }
    return out


def wilson(k: float, n: int) -> tuple[float, float]:
    """95% Wilson interval for a share k/n: where the true rate plausibly lies given n tries."""
    p = k / n
    d = 1 + Z95**2 / n
    c = (p + Z95**2 / (2 * n)) / d
    w = Z95 * np.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / d
    return float(max(0.0, c - w)), float(min(1.0, c + w))


def year_start(d: Any) -> dt.date:
    """1 Farvardin of the Iranian year that ``d`` falls in (Nowruz, taken as 21 March): each
    year's market is different, so a symbol's own record starts at this year's spring."""
    y = d.year if (d.month, d.day) >= (3, 21) else d.year - 1
    return dt.date(y, 3, 21)


OWN_WINDOWS = (("year", "امسال", None), ("y1", "۱ سال", 1), ("y3", "۳ سال", 3),
               ("y5", "۵ سال", 5), ("all", "همه", 0))  # fmt: skip


def _own_window(base: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """One window of each symbol's own record: after h candles, how often it closed above the
    price paid, the 95% interval of that share, and where 8 in 10 of the outcomes fell (10th to
    90th percentile), next to every liquid symbol on the same days."""
    out: dict[int, dict[str, Any]] = {}
    for h in OWN_H:
        ok = base.filter(C(f"f{h}").is_not_null() & C(f"ub{h}").is_not_null())
        agg = ok.group_by(G).agg(
            n=pl.len(),
            k=(C(f"f{h}") > 0).sum(),
            up_all=C(f"ub{h}").mean(),
            q10=C(f"f{h}").quantile(0.1),
            q50=C(f"f{h}").median(),
            q90=C(f"f{h}").quantile(0.9),
            first=C("date").min(),
        )
        for r in agg.iter_rows(named=True):
            n = int(r["n"])
            if n < OWN_MIN:
                continue
            # h-candle windows overlap, so neighbouring days are not separate tries: the interval
            # uses one try per h days, which widens it honestly.
            eff = max(1, n // h)
            lo, hi = wilson(float(r["k"]) * eff / n, eff)
            d = out.setdefault(int(r[G]), {"since": str(r["first"]), "h": []})
            d["since"] = min(d["since"], str(r["first"]))
            d["h"].append(
                {
                    "h": h,
                    "n": n,
                    "eff": eff,
                    "up": r["k"] / n,
                    "lo": lo,
                    "hi": hi,
                    "up_all": _f(r["up_all"]),
                    "q10": _f(r["q10"]),
                    "q50": _f(r["q50"]),
                    "q90": _f(r["q90"]),
                }
            )
    return out


def _own(s: pl.DataFrame) -> dict[int, dict[str, Any]]:
    """Each symbol's own record in every window of OWN_WINDOWS: this Iranian year (the default,
    since each year's market differs), the last 1, 3 or 5 years, or all of its history."""
    tradable = s.filter(C("liquid") & ~C("entry_up_locked"))
    last = s["date"].max()
    close = dict(s.group_by(G).agg(C("close").last()).iter_rows())
    out: dict[int, dict[str, Any]] = {}
    for key, _, years in OWN_WINDOWS:
        if years is None:
            cut: dt.date | None = year_start(last)
        elif years:
            cut = dt.date.fromisoformat(str(last)) - dt.timedelta(days=365 * years)
        else:
            cut = None
        part = tradable if cut is None else tradable.filter(C("date") >= cut)
        for i, w in _own_window(part).items():
            d = out.setdefault(i, {"close": _f(close.get(i)), "windows": {}})
            d["windows"][key] = w
    return out
