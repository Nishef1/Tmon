"""Tests of market-level rules taken from a public educator's videos (see docs/reports/market-method-2026-11.md).

Rule A (exhaustion): a record day of value traded together with net selling by individuals
  is followed by a weak index in the next days.
Rule B (dollar lens): the index measured in the free-market dollar tells more than the rial index;
  a rial record while the dollar-index is far below its own peak is "not expensive".
Everything is judged on both halves of time, against the unconditional average, with the
index only (no trading costs on the index; costs are a single round trip stated in the report).
Run: python research/market_method/study.py  (read-only on the live database)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
TEDPIX = "32097828799138957"
HORIZONS = (1, 5, 10, 20, 60)
OUT = Path(__file__).with_name("results.json")


def load() -> pd.DataFrame:
    c = sqlite3.connect(DB, uri=True)
    idx = pd.read_sql(
        "select date, close from market_index_daily where index_code=?", c, params=(TEDPIX,)
    )
    val = pd.read_sql(
        "select p.date, sum(p.value) as value from prices_daily p join instruments i "
        "on i.id=p.instrument_id where i.instrument_type='stock' group by p.date",
        c,
    )
    flow = pd.read_sql(
        "select t.date, sum(t.buy_value_i - t.sell_value_i) as net_i, "
        "sum(t.buy_value_i + t.buy_value_n) as tot from client_types_daily t join instruments i "
        "on i.id=t.instrument_id where i.instrument_type='stock' group by t.date",
        c,
    )
    usd = pd.read_sql(
        "select ref_period as date, value as usd from macro_series where series='usd_free'", c
    )
    df = (
        idx.merge(val, on="date", how="left")
        .merge(flow, on="date", how="left")
        .merge(usd, on="date", how="left")
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df["usd"] = df["usd"].ffill()
    return df


def fwd(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1


def summarise(df: pd.DataFrame, mask: pd.Series, name: str, split: pd.Timestamp) -> dict:
    out: dict = {"name": name, "days": int(mask.sum())}
    for h in HORIZONS:
        f = df[f"f{h}"]
        both = {}
        for half, sel in (("h1", df.index < split), ("h2", df.index >= split)):
            m = mask & sel & f.notna()
            base = f[sel & f.notna()]
            both[half] = {
                "n": int(m.sum()),
                "mean": float(f[m].mean()) if m.sum() else None,
                "base": float(base.mean()),
                "hit_down": float((f[m] < 0).mean()) if m.sum() else None,
                "base_down": float((base < 0).mean()),
            }
        out[f"h{h}"] = both
    return out


def main() -> int:
    df = load()
    df = df[df["close"].notna()]
    for h in HORIZONS:
        df[f"f{h}"] = fwd(df["close"], h)
    df["ret1"] = df["close"].pct_change()
    split = df.index[len(df) // 2]
    res: dict = {"split": str(split.date()), "rows": len(df), "first": str(df.index[0].date())}

    # Rule A. value record vs trailing 250 days, plus net individual outflow
    v = df["value"]
    df["val_rec250"] = v >= v.rolling(250, min_periods=200).max()
    df["val_rec_all"] = v >= v.expanding(min_periods=250).max()
    df["net_ratio"] = df["net_i"] / df["tot"]
    out_i = df["net_ratio"] < 0
    out_deep = df["net_ratio"] < df["net_ratio"].rolling(250, min_periods=200).quantile(0.10)
    avg20 = v.rolling(20).mean().shift(1)
    big = v > 2 * avg20
    # the 'sell the record' reading needs the index to be near its high too
    near_high = df["close"] >= df["close"].rolling(60).max() * 0.98
    A = [
        ("A0 all days", pd.Series(True, index=df.index)),
        ("A1 value record (250d)", df["val_rec250"]),
        ("A2 value record (all-time)", df["val_rec_all"]),
        ("A3 value record + individuals net selling", df["val_rec250"] & out_i),
        ("A4 value record + deep outflow (bottom decile of 250d)", df["val_rec250"] & out_deep),
        ("A5 value > 2x 20d avg + individuals net selling", big & out_i),
        ("A6 value record + outflow + index near 60d high", df["val_rec250"] & out_i & near_high),
        ("A7 deep outflow only", out_deep),
        (
            "A8 value record + individuals net buying",
            df["val_rec250"] & ~out_i & df["net_ratio"].notna(),
        ),
    ]
    res["A"] = [summarise(df, m.fillna(False), n, split) for n, m in A]

    # Rule B. dollar lens
    df["idx_usd"] = df["close"] / df["usd"]
    d = df[df["usd"].notna()].copy()
    d["pct_rial"] = d["close"].expanding(500).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    d["pct_usd"] = d["idx_usd"].expanding(500).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    d["rial_high"] = d["close"] >= d["close"].rolling(250).max()
    d["usd_gap"] = d["idx_usd"] / d["idx_usd"].expanding(250).max() - 1
    for h in HORIZONS:
        d[f"f{h}"] = fwd(d["close"], h)
    B = [
        ("B0 all days (dollar era)", pd.Series(True, index=d.index)),
        ("B1 rial 250d high", d["rial_high"]),
        (
            "B2 rial 250d high, dollar-index within 10% of its peak",
            d["rial_high"] & (d["usd_gap"] > -0.10),
        ),
        (
            "B3 rial 250d high, dollar-index more than 30% below its peak",
            d["rial_high"] & (d["usd_gap"] < -0.30),
        ),
        ("B4 dollar-index percentile < 25%", d["pct_usd"] < 0.25),
        ("B5 dollar-index percentile > 75%", d["pct_usd"] > 0.75),
        (
            "B6 rial percentile > 90% and dollar-index percentile < 50%",
            (d["pct_rial"] > 0.9) & (d["pct_usd"] < 0.5),
        ),
    ]
    split_b = d.index[len(d) // 2]
    res["B_split"] = str(split_b.date())
    res["B"] = [summarise(d, m.fillna(False), n, split_b) for n, m in B]
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    def show(title: str, rows: list[dict]) -> None:
        print("\n" + title)
        for r in rows:
            line = f"{r['name'][:62]:62s} n={r['days']:5d}"
            for h in (5, 20, 60):
                x = r[f"h{h}"]
                a, b = x["h1"], x["h2"]
                fmt = lambda s: (
                    "  n/a "
                    if s["mean"] is None
                    else f"{100 * s['mean']:+5.1f}/{100 * s['base']:+4.1f}({s['n']})"
                )  # noqa: E731
                line += f" | {h}d {fmt(a)} {fmt(b)}"
            print(line)

    show("Rule A (mean fwd return / half baseline (n))", res["A"])
    show("Rule B", res["B"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
