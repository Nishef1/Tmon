"""The owner's drawdown-floor entry («طلا تو خاک») on tradable funds.
(docs/reports/drawdown-floor-2026-11.md, section on funds)

Same rules as drawdown_floor.py: episodes from one new high to the next, depth = lowest close /
peak - 1, episodes shallower than -20% ignored, "usual" = median depth of the fund's completed
episodes before the day (at least 2), steps at 0.75 / 1 / 1.15 / 1.3 x usual. Entry = close of
t+1, hold 60 and 250 trading days, round-trip cost 0.3% (a fund), excess over the mean of the
same fund group on the same entry day. Events from 2023-04, both halves.

Funds have no statements, so the "sound company" filter has no fund version; price / NAV is not
testable either (NAV history is a few days, OPEN_QUESTIONS 78). Fixed-income funds never fall
20%, so they are left out. Liquid = median daily value of the last 60 days at least 10 billion
rial (1 billion toman), the same bar as the fund ranking study.

Run from backend/ with the live env: python research/market_method/fund_drawdown_floor.py
Output: results_fund_drawdown_floor.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))
import drawdown_floor as dfl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs
from tmon.storage.models import Instrument

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.003
MIN_VALUE = 1e10
GROUP = {
    "etf_equity": "equity_mixed",
    "etf_mixed": "equity_mixed",
    "etf_leveraged": "leveraged",
    "etf_commodity": "commodity",
}
dfl.COST = COST


def clustered(e: pl.DataFrame) -> dict:
    """Funds of one group fall together, so events are not independent: the mean excess of each
    entry month, and the t over months."""
    out: dict = {}
    for h in ("x60", "x250"):
        m = (
            e.filter(C(h).is_not_null())
            .group_by(C("date").dt.strftime("%Y-%m").alias("m"))
            .agg(C(h).mean())[h]
            .to_numpy()
        )
        t = float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))) if len(m) > 2 else None
        out[h + "_months"] = {"months": len(m), "t": t}
    return out


def main() -> None:
    with session_scope() as s:
        main, _cl, _ = load_inputs(s)
        comp, _cl, _ = load_inputs(s, comparison_funds=True)
        inst = {i.id: i for i in s.scalars(select(Instrument))}
    kinds = {i: GROUP[x.instrument_type] for i, x in inst.items() if x.instrument_type in GROUP}
    prices = pl.concat([main.filter(C(G).is_in(list(kinds))), comp.select(main.columns)])
    a = apply_adjustments(prices).filter((C("close") > 0) & C(G).is_in(list(kinds)))
    a = a.sort(G, "date").with_columns(C("date").cast(pl.Date))
    a = a.with_columns(kind=C(G).replace_strict(kinds, default=None))
    c = C("adj_close")
    a = a.with_columns(
        f60=(c.shift(-61) / c.shift(-1) - 1 - COST).over(G),
        f250=(c.shift(-251) / c.shift(-1) - 1 - COST).over(G),
        hi60=(c >= c.rolling_max(60)).over(G),
        up7=((c > c.shift(1)).cast(pl.Int8).rolling_sum(7) >= 5).over(G),
    )
    a = a.with_columns(
        x60=C("f60") - C("f60").mean().over("date", "kind"),
        x250=C("f250") - C("f250").mean().over("date", "kind"),
    )
    last = a["date"].max()
    liquid = set(
        a.filter(C("date") > pl.lit(last).dt.offset_by("-90d"))
        .group_by(G)
        .agg(C("value").median().alias("v"))
        .filter(C("v") >= MIN_VALUE)[G]
        .to_list()
    )
    rows, reps, table = [], [], []
    for (iid,), g in a.group_by(G, maintain_order=True):
        dts = g["date"].to_numpy().astype("datetime64[D]")
        ev, rep, st = dfl.scan(dts, g["adj_close"].to_numpy())
        reps += [{**r, "kind": kinds[iid]} for r in rep]
        if iid in liquid and st["n"] >= 2:
            table.append({"symbol": inst[iid].symbol_fa, "kind": kinds[iid], **st})
        rows.extend({G: iid, "kind": kinds[iid], "date": g["date"][x.pop("i")], **x} for x in ev)
    e = pl.DataFrame(rows).join(a.select(G, "date", "x60", "x250"), on=[G, "date"], how="left")
    green = a.filter((C("date") >= pl.date(2023, 4, 1)) & C("hi60") & C("up7"))
    res: dict = {}
    for k in ("equity_mixed", "leveraged", "commodity", None):
        ek = e if k is None else e.filter(C("kind") == k)
        gk = green if k is None else green.filter(C("kind") == k)
        out = [dfl.judge(ek.filter(C("step") == s), s) for s in dfl.STEPS]
        anyk = ek.unique([G, "date"])
        out.append({**dfl.judge(anyk, "any step"), **clustered(anyk)})
        out.append(dfl.judge(gk, "GREEN"))
        res[k or "all"] = out
    r = pl.DataFrame(reps)
    repeat = {}
    for k in ("equity_mixed", "leveraged", "commodity", None):
        rk = r if k is None else r.filter(C("kind") == k)
        if rk.height < 3:
            repeat[k or "all"] = {"n": rk.height}
            continue
        repeat[k or "all"] = {
            "n": rk.height,
            "corr": float(np.corrcoef(rk["med"], rk["next"])[0, 1]),
            "inside_range": float(((rk["next"] >= rk["lo"]) & (rk["next"] <= rk["hi"])).mean()),
            "deeper_than_range": float((rk["next"] < rk["lo"]).mean()),
            "shallower_than_range": float((rk["next"] > rk["hi"]).mean()),
            "mae_vs_median": float((rk["next"] - rk["med"]).abs().mean()),
        }
    table.sort(key=lambda t: t["median"] if t["median"] is not None else 0)
    out = {"results": res, "repeat": repeat, "table": table, "as_of": str(last)}
    (HERE / "results_fund_drawdown_floor.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    for k, xs in res.items():
        for x in xs:
            print(k, x["name"], x["n"], {h: x[h] for h in ("x60", "x250") if h in x})
    print("repeat", json.dumps(repeat, indent=1))
    print("table", len(table))


if __name__ == "__main__":
    main()
