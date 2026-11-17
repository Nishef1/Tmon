"""Does a monthly sales figure better than its peers' predict the next 20 and 60 days? (OPEN_QUESTIONS 99)

Input: D:/Data/Tmon/data/monthly-sales.csv (monthly_pdf_build.py): 1-month ن-۳۰ reports, production template.
Signal at the publication day of a report: YoY = month / same month a year earlier - 1 (needs both reports),
and SURP = YoY minus the median YoY of every report published in the 30 days up to that day (backward only,
so nothing from the future; it removes the inflation level). Entry: close of the next trading day. Return
over 20 and 60 trading days on adjusted prices, minus the basket mean on the same entry day, minus the
1.75% round trip cost. Events: SURP > 0, SURP > +20 points (untested threshold), SURP <= 0 (control).
Two halves = events before / after the median event date. Events overlap in time, so the honest sample is
small; the count is printed.
Run from backend/ with the live env:  python research/market_method/sales_surprise.py
Output: results_sales_surprise.json
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import fundamental_model as fm  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.core.timeutil import from_jalali  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
COST = 0.0175
HERE = Path(__file__).parent


def main() -> None:
    _p, ids = fm.build()
    by_sym = {v: k for k, v in ids.items()}
    rows = list(csv.DictReader(open("D:/Data/Tmon/data/monthly-sales.csv", encoding="utf-8")))
    s = pl.DataFrame(
        [
            {
                "symbol": r["symbol"],
                "jy": int(r["jy"]),
                "jm": int(r["jm"]),
                "pub": r["published_at"],
                "month": float(r["month"]),
            }
            for r in rows
        ]
    ).with_columns(C("pub").str.to_date())
    prev = s.select("symbol", (C("jy") + 1).alias("jy"), "jm", C("month").alias("m_prev"))
    s = s.join(prev, on=["symbol", "jy", "jm"], how="inner").filter((C("month") > 0) & (C("m_prev") > 0))
    s = s.with_columns(yoy=C("month") / C("m_prev") - 1).sort("pub")
    pubs = s["pub"].to_list()
    yoys = s["yoy"].to_numpy()
    med = []
    for i, d in enumerate(pubs):
        lo = d - timedelta(days=30)
        w = [yoys[j] for j in range(i + 1) if pubs[j] >= lo]
        med.append(float(np.median(w)) if len(w) >= 10 else None)
    s = s.with_columns(pl.Series("med", med, dtype=pl.Float64)).drop_nulls("med")
    s = s.with_columns(surp=C("yoy") - C("med")).filter(C("symbol").is_in(list(by_sym)))
    s = s.with_columns(C("symbol").replace_strict(by_sym, return_dtype=pl.Int64).alias(G))
    print("events with a signal:", s.height, "stocks:", s[G].n_unique())

    with session_scope() as sc:
        prices, _cl, _ = load_inputs(sc)
    a = apply_adjustments(prices).filter(C("close") > 0).sort(G, "date")
    a = a.with_columns(C("date").cast(pl.Date))
    c = C("adj_close")
    a = a.with_columns(
        f20=(c.shift(-21) / c.shift(-1) - 1).over(G), f60=(c.shift(-61) / c.shift(-1) - 1).over(G)
    ).select("date", G, "f20", "f60")
    b = a.filter(C(G).is_in(list(ids))).group_by("date").agg(b20=C("f20").mean(), b60=C("f60").mean())
    a = a.join(b, on="date").sort("date")
    # entry row = first trading day strictly after the publication day (its f = close(t+1) -> close(t+1+h) is
    # measured from the entry close: the row of the entry day itself)
    ev = s.sort("pub").join_asof(
        a.sort("date").rename({"date": "d"}), left_on="pub", right_on="d", by=G, strategy="forward"
    )
    ev = ev.filter(C("d") > C("pub")) if False else ev
    ev = ev.drop_nulls(["f20", "b20"]).with_columns(
        x20=C("f20") - C("b20") - COST, x60=C("f60") - C("b60") - COST
    )
    cut = ev["pub"].sort()[ev.height // 2]
    out: dict = {"cost": COST, "events": ev.height, "median_date": str(cut)}
    sets = {
        "SURP>0": C("surp") > 0,
        "SURP>+0.20": C("surp") > 0.20,
        "SURP<=0 (control)": C("surp") <= 0,
        "all": C("surp").is_not_null(),
    }
    for name, f in sets.items():
        for half, hf in (("first", C("pub") < cut), ("second", C("pub") >= cut), ("both", C("pub").is_not_null())):
            e = ev.filter(f & hf)
            r = {"n": e.height, "stocks": e[G].n_unique() if e.height else 0}
            for h in ("x20", "x60"):
                v = e[h].drop_nulls()
                r[h] = {
                    "mean": float(v.mean()) if v.len() else None,
                    "hit": float((v > 0).mean()) if v.len() else None,
                }
            out[f"{name} | {half}"] = r
            print(name, half, r)
    # spread SURP>0 minus control, one number per publication month (the honest sample)
    mo = ev.with_columns(ym=C("pub").dt.strftime("%Y-%m"), up=C("surp") > 0)
    for h in ("x20", "x60"):
        g = mo.group_by("ym", "up").agg(m=C(h).mean()).pivot(on="up", index="ym", values="m").drop_nulls()
        sp = (g["true"] - g["false"]).to_numpy()
        t = float(sp.mean() / (sp.std(ddof=1) / np.sqrt(len(sp)))) if len(sp) > 2 else None
        out[f"spread_{h}"] = {"months": len(sp), "mean": float(sp.mean()), "positive": int((sp > 0).sum()), "t": t}
        print("spread", h, out[f"spread_{h}"])
    (HERE / "results_sales_surprise.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
