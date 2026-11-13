"""Do the chart readings call the next candles on this year's data, and does it depend on
whether the symbol went up, sideways or down this year?

Every signal is causal (it only uses data up to its day; Elliott pivots count from the day the
10% turn confirmed them). Outcome: was the close 5 / 20 candles after the next day's close
higher (buy readings) or lower (sell readings)? Compared with every liquid day of symbols in the
same group this year. Groups by the symbol's move over the year so far (hindsight, used only to
split the table): up >= +15%, down <= -15%, range in between. Thresholds fixed before running.

python research/forecast_check/run.py  (env: TMON_DATABASE_URL ...)
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import polars as pl

from tmon.backtest import ta_signals as ts
from tmon.core.db import session_scope
from tmon.features.store import load_inputs

C = pl.col
START = dt.date(2026, 3, 21)  # Nowruz 1405
BAND = 0.15
HS = (5, 20)


def main() -> None:
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    p = ts.flags(ts.with_outcomes(ts.indicators(prices, clients)))
    y = p.filter((C("date") >= START) & C("liquid"))
    move = y.group_by(ts.G).agg(
        (C("close").sort_by("date").last() / C("close").sort_by("date").first() - 1).alias("mv")
    )
    y = y.join(move, on=ts.G).with_columns(
        grp=pl.when(C("mv") >= BAND)
        .then(pl.lit("up"))
        .when(C("mv") <= -BAND)
        .then(pl.lit("down"))
        .otherwise(pl.lit("range"))
    )
    # the trend visible that day (no hindsight): close vs the 50-day average and its 10-day slope
    y = y.with_columns(
        now=pl.when((C("close") > C("sma50")) & (C("sma50") > C("sma50").shift(10).over(ts.G)))
        .then(pl.lit("now_up"))
        .when((C("close") < C("sma50")) & (C("sma50") < C("sma50").shift(10).over(ts.G)))
        .then(pl.lit("now_down"))
        .otherwise(pl.lit("now_range"))
    )
    out: dict = {"start": str(START), "last": str(y["date"].max()), "groups": {}, "signals": {}}
    for g in ("up", "range", "down", "now_up", "now_range", "now_down", "all"):
        col = "now" if g.startswith("now_") else "grp"
        gy = y if g == "all" else y.filter(C(col) == g)
        base = {h: gy.filter(C(f"f{h}").is_not_null()) for h in HS}
        out["groups"][g] = {
            "symbols": gy[ts.G].n_unique(),
            **{f"up{h}": float((base[h][f"f{h}"] > 0).mean()) for h in HS},
            **{f"dn{h}": float((base[h][f"f{h}"] < 0).mean()) for h in HS},
        }
        for k, (_term, side, title, _) in ts.SIGNALS.items():
            row = out["signals"].setdefault(k, {"title": title, "side": side})
            cell = {}
            for h in HS:
                sub = base[h].filter(C("s_" + k))
                if sub.height == 0:
                    continue
                hit = (sub[f"f{h}"] > 0) if side == "buy" else (sub[f"f{h}"] < 0)
                b = out["groups"][g][("up" if side == "buy" else "dn") + str(h)]
                cell[f"n{h}"] = sub.height
                cell[f"hit{h}"] = float(hit.mean())
                cell[f"edge{h}"] = float(hit.mean()) - b
            row[g] = cell
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__" and "--examples" not in sys.argv:
    main()


def examples() -> None:
    """Three liquid symbols this year (the most up, the flattest, the most down): every reading
    each fired and how often the next 5 candles went its way."""
    from tmon.storage.models import Instrument

    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        names = dict(s.query(Instrument.id, Instrument.symbol_fa).all())
    p = ts.flags(ts.with_outcomes(ts.indicators(prices, clients)))
    y = p.filter((C("date") >= START) & C("liquid") & C("f5").is_not_null())
    cl = C("close").sort_by("date")
    days = y.group_by(ts.G).agg(pl.len().alias("d"), (cl.last() / cl.first() - 1).alias("mv"))
    days = days.filter(C("d") >= 100).sort("mv")
    mid = days.with_columns(a=C("mv").abs()).sort("a")
    picks = {"down": days[0, ts.G], "range": mid[0, ts.G], "up": days[-1, ts.G]}
    for g, iid in picks.items():
        sy = y.filter(C(ts.G) == iid)
        mv = days.filter(C(ts.G) == iid)["mv"][0]
        tot = hits = 0
        per = []
        for k, (_t, side, _title, _) in ts.SIGNALS.items():
            sub = sy.filter(C("s_" + k))
            if sub.height == 0:
                continue
            h = int(((sub["f5"] > 0) if side == "buy" else (sub["f5"] < 0)).sum())
            tot += sub.height
            hits += h
            per.append(f"{k}:{h}/{sub.height}")
        up = float((sy["f5"] > 0).mean())
        right = hits / max(tot, 1)
        print(f"{g} {names.get(iid)} move={mv:+.0%} up5={up:.0%} n={tot} right={right:.0%}")
        print("   ", " ".join(per))


if __name__ == "__main__" and "--examples" in sys.argv:
    examples()
