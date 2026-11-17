"""Stock-level tests of three ideas from the same educator (docs/reports/market-method-2026-11.md).

C1 leader of its sector (largest median traded value in the sector) beats the other symbols.
C2 sector rotation: members of the sectors with the best trailing 60-day return keep winning.
C3 dollar lens: a symbol close to its own dollar-priced 500-day high keeps winning; one far below does not.
Universe: the liquid 60% each day, as in docs/reports/turning-points-2026-11.md. Entry at the close of t+1;
excess = return minus the day's mean of the universe; both halves of time; round trip cost 1.75%.
Run from backend/ with the live env.  Output: results_stock.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

C = pl.col
G = "instrument_id"
HZ = (20, 60)
COST = 0.0175
DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"


def main() -> int:
    with session_scope() as s:
        prices, _clients, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0)).sort(G, "date")
    p = p.with_columns(close=C("adj_close"))
    c = sqlite3.connect(DB, uri=True)
    sec = pl.DataFrame(
        c.execute("select id, sector_code from instruments").fetchall(),
        schema={G: pl.Int64, "sector": pl.Utf8},
        orient="row",
    )
    usd = (
        pl.DataFrame(
            c.execute(
                "select ref_period, value from macro_series where series='usd_free'"
            ).fetchall(),
            schema={"date": pl.Utf8, "usd": pl.Float64},
            orient="row",
        )
        .with_columns(C("date").str.to_date())
        .sort("date")
    )
    p = p.with_columns(C("date").cast(pl.Date)).join(sec, on=G, how="left")
    p = (
        p.sort("date")
        .join_asof(usd, on="date")
        .sort(G, "date")
        .with_columns(pc=C("close") / C("usd"))
    )
    cl = C("close")
    roll = lambda e, f, n: getattr(e, f"rolling_{f}")(n, min_samples=n).over(G)  # noqa: E731
    p = p.with_columns(
        ret60=cl / cl.shift(60).over(G) - 1,
        vmed20=roll(C("value"), "median", 20),
        pchi=roll(C("pc"), "max", 500),
    )
    entry = cl.shift(-1).over(G)
    p = p.with_columns(*[(cl.shift(-1 - h).over(G) / entry - 1).alias(f"f{h}") for h in HZ])
    p = p.with_columns(pgap=C("pc") / C("pchi") - 1)
    # universe: liquid 60% each day
    p = p.filter(C("vmed20").is_not_null() & C("sector").is_not_null())
    p = p.with_columns(
        lq=C("vmed20").rank("average").over("date") / C("vmed20").count().over("date")
    )
    u = p.filter(C("lq") > 0.4)
    u = u.with_columns(*[(C(f"f{h}") - C(f"f{h}").mean().over("date")).alias(f"x{h}") for h in HZ])
    # C1 leader of sector
    u = u.with_columns(
        n_sec=pl.len().over("date", "sector"),
        rank_sec=C("vmed20").rank("ordinal", descending=True).over("date", "sector"),
    )
    u = u.with_columns(leader=(C("rank_sec") == 1) & (C("n_sec") >= 4))
    # C2 sector momentum: mean 60d return of the sector, tercile among sectors that day
    sm = u.group_by("date", "sector").agg(sret=C("ret60").mean(), k=pl.len()).filter(C("k") >= 4)
    sm = sm.with_columns(sr=C("sret").rank("average").over("date") / C("sret").count().over("date"))
    u = u.join(sm.select("date", "sector", "sr", "sret"), on=["date", "sector"], how="left")
    # own 60-day return, tercile in the day's universe: does sector momentum add to it?
    u = u.with_columns(
        own=C("ret60").rank("average").over("date") / C("ret60").count().over("date")
    )
    # C3 dollar position
    mid = u["date"].sort()[u.height // 2]
    out: dict = {"split": str(mid)}

    def stat(name: str, mask: pl.Expr) -> dict:
        r: dict = {"name": name}
        for hlf, sel in (("h1", C("date") < mid), ("h2", C("date") >= mid)):
            d = u.filter(sel)
            m = d.filter(mask & C("x60").is_not_null())
            days = m["date"].n_unique()
            r[hlf] = {
                "rows": m.height,
                "days": days,
                "ex20": m["x20"].drop_nulls().mean(),
                "ex60": m["x60"].mean(),
                "med60": m["x60"].median(),
                "win60": float((m["x60"] > 0).mean()) if m.height else None,
            }
        return r

    tests = [
        ("U all liquid", pl.lit(True)),
        ("C1 sector leader (>=4 symbols)", C("leader")),
        ("C1b not leader", ~C("leader")),
        ("C2 top-third sectors by 60d return", C("sr") > 2 / 3),
        ("C2b bottom-third sectors", C("sr") <= 1 / 3),
        ("C2c top sectors, own return in bottom third", (C("sr") > 2 / 3) & (C("own") <= 1 / 3)),
        ("C2d bottom sectors, own return in top third", (C("sr") <= 1 / 3) & (C("own") > 2 / 3)),
        ("C2e own return top third (any sector)", C("own") > 2 / 3),
        ("C2f own return bottom third (any sector)", C("own") <= 1 / 3),
        ("C3 near dollar 500d high (gap > -10%)", C("pgap") > -0.10),
        ("C3b dollar gap -10..-40%", (C("pgap") <= -0.10) & (C("pgap") > -0.40)),
        ("C3c far below dollar high (< -40%)", C("pgap") <= -0.40),
        ("C1xC3 leader and gap > -10%", C("leader") & (C("pgap") > -0.10)),
    ]
    out["rows"] = [stat(n, m) for n, m in tests]
    Path(__file__).with_name("results_stock.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1)
    )
    print("split", mid, "universe rows", u.height)
    for r in out["rows"]:
        f = lambda h: (  # noqa: E731
            f"{r[h]['rows']:7d}/{r[h]['days']:4d}d ex60 {100 * r[h]['ex60']:+5.1f}% med {100 * r[h]['med60']:+5.1f}% win {100 * r[h]['win60']:3.0f}%"
            if r[h]["rows"]
            else "none"
        )
        print(f"{r['name'][:42]:42s} H1 {f('h1')} | H2 {f('h2')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
