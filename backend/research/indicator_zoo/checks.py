"""Robustness of the models.py result (argv[1] = scratch dir, live DB env).

1. Tradability: drop rows whose entry day t+1 was locked at the daily limit (high == low and a
   move above 2.8%), where a buy order at the close would usually not fill.
2. Which family carries the gain: the zoo model without the candle/gap features, and with only
   them.
Walk-forward LightGBM at 20 days, as in models.py.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

SP = Path(sys.argv[1])
C = pl.col
G = "instrument_id"
BASE = ["b_power", "b_rv20", "b_dist52", "b_mom121"]
CANDLE = ["gap", "candle_body", "rvgi", "upper_wick", "lower_wick", "bop", "uo", "elder_bear",
          "elder_bull", "rsi2", "crsi", "cmf", "ad_slope", "chaikin_osc", "stoch", "willr",
          "pivot", "keltner", "donchian", "bb_pctb", "cci", "fisher", "smi", "wavetrend_x"]  # fmt: skip


def locked_next() -> pl.DataFrame:
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    p = p.with_columns(
        lock=(
            (C("adj_high") == C("adj_low"))
            & ((C("adj_close") / C("adj_close").shift(1).over(G) - 1).abs() > 0.028)
        ),
        up=C("adj_close") > C("adj_close").shift(1).over(G),
    )
    return p.with_columns(
        lock_next=C("lock").shift(-1).over(G), up_next=C("up").shift(-1).over(G)
    ).select(G, "date", "lock_next", "up_next")


def run(d: pl.DataFrame, sets: dict[str, list[str]], y: str = "x20") -> dict:
    preds: dict[str, list] = {k: [] for k in sets}
    for yr in range(2010, int(d["year"].max()) + 1):
        cut = dt.date(yr, 1, 1) - dt.timedelta(days=90)
        tr, te = d.filter(C("date") < cut), d.filter(C("year") == yr)
        if tr.height < 20000 or te.height == 0:
            continue
        for k, cols in sets.items():
            m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=31,
                                  min_child_samples=300, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, verbose=-1)  # fmt: skip
            m.fit(tr.select(cols).to_numpy(), tr["ry"].to_numpy())
            preds[k].append(
                te.select("date", y, "tradable").with_columns(
                    s=pl.Series(m.predict(te.select(cols).to_numpy()))
                )
            )
    out = {}
    for k, parts in preds.items():
        p = pl.concat(parts)
        for name, q in (("all", p), ("tradable", p.filter(C("tradable")))):
            g = (
                q.group_by("date")
                .agg(
                    ic=pl.corr("s", y, method="spearman"),
                    top=C(y).filter(C("s") >= C("s").quantile(0.9)).mean(),
                )
                .drop_nulls()
                .sort("date")
            )
            mid = g["date"][g.height // 2]
            a, b = g.filter(C("date") < mid), g.filter(C("date") >= mid)
            out[f"{k}/{name}"] = {
                "ic": float(g["ic"].mean()), "ic_a": float(a["ic"].mean()), "ic_b": float(b["ic"].mean()),
                "top": float(g["top"].mean()), "top_a": float(a["top"].mean()), "top_b": float(b["top"].mean()),
            }  # fmt: skip
        print(k, json.dumps({n: v for n, v in out.items() if n.startswith(k)}), flush=True)
    return out


def main() -> None:
    d = pl.read_parquet(SP / "zoo_panel.parquet")
    info = json.loads((SP / "zoo_panel.json").read_text())["info"]
    zoo = list(info)
    d = d.join(locked_next(), on=[G, "date"], how="left").with_columns(
        tradable=~(C("lock_next").fill_null(False) & C("up_next").fill_null(False))
    )
    print("share of rows whose next day is locked limit-up:", float(1 - d["tradable"].mean()))
    feats = zoo + BASE
    d = d.with_columns(*[((C(f).rank() - 0.5) / C(f).count()).over("date").alias(f) for f in feats])
    d = d.filter(C("x20").is_not_null()).with_columns(
        ry=((C("x20").rank() - 0.5) / C("x20").count()).over("date")
    )
    sets = {
        "base4+zoo": feats,
        "no_candle": [f for f in feats if f not in CANDLE],
        "base4+candle": BASE + CANDLE,
    }
    res = run(d, sets)
    (SP / "zoo_checks.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
