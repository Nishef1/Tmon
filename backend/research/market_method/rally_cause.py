"""What moved the market since the 80-day closure? (docs/reports/mega-winners-2026-11.md)

Month-end values of the official indices (TEDPIX, equal-weight), the free-market dollar, the emami coin,
gold and Brent from ``macro_series`` and ``market_index_daily``, and the equal-weight index measured in
dollars. Also the closure itself: the days with a frozen index, and the change from the last pre-closure
close to the latest. Descriptive: it shows what moved together, not what caused what.
Run from backend/ with the live env:  python research/market_method/rally_cause.py
Output: results_rally_cause.json
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

DB = "D:/Data/Tmon/data/tmon-live.sqlite3"
TEDPIX, EQW = "32097828799138957", "67130298613737946"
HERE = Path(__file__).parent


def main() -> None:
    c = sqlite3.connect(DB)
    idx = pd.read_sql("select index_code, date, close from market_index_daily", c)
    idx["date"] = pd.to_datetime(idx["date"])
    ted = idx[idx.index_code == TEDPIX].set_index("date").close.rename("tedpix")
    eqw = idx[idx.index_code == EQW].set_index("date").close.rename("eqw")
    m = pd.read_sql(
        "select series, ref_period d, value v from macro_series "
        "where series in ('usd_free','coin_emami','brent_usd','gold_usd')",
        c,
    )
    m["d"] = pd.to_datetime(m["d"])
    m = m.pivot(index="d", columns="series", values="v")
    df = pd.concat([ted, eqw, m], axis=1, sort=True).ffill()["2025-01-01":]
    df["eqw_usd"] = df.eqw / df.usd_free * 1000
    df["ted_usd"] = df.tedpix / df.usd_free * 1000
    me = df.resample("ME").last()
    print(me.round(0).to_string())

    frozen = df[(df.tedpix.diff() == 0) & (df.index >= "2026-02-26") & (df.index <= "2026-05-18")]
    pre = df.loc["2026-02-25"]
    now = df.iloc[-1]
    low = df.loc["2025-08-01":"2025-09-30"].eqw.idxmin()
    out = {
        "frozen_from": str(frozen.index.min().date()),
        "frozen_to": str(frozen.index.max().date()),
        "pre_closure": {
            k: float(pre[k]) for k in ("tedpix", "eqw", "usd_free", "eqw_usd", "ted_usd")
        },
        "latest_date": str(df.index[-1].date()),
        "latest": {k: float(now[k]) for k in ("tedpix", "eqw", "usd_free", "eqw_usd", "ted_usd")},
        "trough_2025": {
            "date": str(low.date()),
            **{k: float(df.loc[low][k]) for k in ("eqw", "usd_free", "eqw_usd")},
        },
        "month_end": json.loads(
            me.round(1).reset_index().astype({"index": str}).to_json(orient="records")
        ),
    }
    for k in ("tedpix", "eqw", "usd_free", "eqw_usd", "ted_usd"):
        out[f"chg_since_closure_{k}"] = float(now[k] / pre[k] - 1)
        out[f"chg_since_trough_{k}"] = (
            float(now[k] / df.loc[low][k] - 1) if k in df.columns else None
        )
    print(
        f"closure {out['frozen_from']}..{out['frozen_to']}; since pre-closure: tedpix "
        f"{out['chg_since_closure_tedpix']:+.0%} eqw {out['chg_since_closure_eqw']:+.0%} usd "
        f"{out['chg_since_closure_usd_free']:+.0%} eqw in usd {out['chg_since_closure_eqw_usd']:+.0%}"
    )
    print(
        f"since the Aug-Sep 2025 trough ({out['trough_2025']['date']}): eqw {out['chg_since_trough_eqw']:+.0%} "
        f"usd {out['chg_since_trough_usd_free']:+.0%} eqw in usd {out['chg_since_trough_eqw_usd']:+.0%}"
    )
    (HERE / "results_rally_cause.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
