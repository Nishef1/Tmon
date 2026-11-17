"""The "dividend-income" method from a Telegram educator's video, as exact rules, on our data.
(docs/reports/dividend-yield-2026-11.md)

The claim: buy companies whose market value is 4 to 5 times their yearly dividend (a 20-25% yield), that are
financially sound (low debt, growing profit, sells for cash), hold them, and live on the dividends while the
dividend grows faster than inflation.
Our data has no dividend per share (corporate_events.dps is empty), so the screen uses P/E <= 5 (earnings yield
>= 20%), which equals P/D <= 5 when the payout is 100%. Rules tested, all from the 100-symbol basket:
  Y5     P/E in (0, 5]
  Y5-Q   Y5 and liabilities/assets <= 0.6 and net profit growth > 0 (the video's "sound company" screen)
  Y4     P/E in (0, 4]
  cheap  the cheapest third by P/E among stocks with P/E > 0 (control: the same idea without a fixed cut)
Entry = close of t+1; hold 250 trading days (one year, one round trip of 1.75%) and 60 days; adjusted prices, so
the ex-dividend drop is already folded in (the price return includes the dividend because the price fell by it).
Judged against the mean of the whole basket on the same entry day ("excess"), in both halves of the entry dates,
with entries every 20 days (overlapping within a year: the honest sample is the number of years, i.e. very few).
Run from backend/ with the live env:  python research/market_method/dividend_yield.py
Output: results_dividend_yield.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import fundamental_model as fm  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175
STEP = 20


def main() -> None:
    p, _ids = fm.build()
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    a = apply_adjustments(prices).filter(C("close") > 0).sort(G, "date")
    a = a.with_columns(C("date").cast(pl.Date))
    c = C("adj_close")
    a = a.with_columns(
        entry=c.shift(-1).over(G),
        f250=(c.shift(-251) / c.shift(-1) - 1).over(G),
        f60=(c.shift(-61) / c.shift(-1) - 1).over(G),
    ).select("date", G, "f250", "f60")
    d = p.join(a, on=["date", G], how="inner")
    d = d.with_columns(
        cheap=(C("pe").rank("average").over("date") / C("pe").count().over("date") <= 1 / 3)
        & (C("pe") > 0),
    )
    rules = {
        "Y5": (C("pe") > 0) & (C("pe") <= 5),
        "Y5-Q": (C("pe") > 0) & (C("pe") <= 5) & (C("liab_ratio") <= 0.6) & (C("net_g") > 0),
        "Y4": (C("pe") > 0) & (C("pe") <= 4),
        "cheap": C("cheap"),
    }
    dates = d["date"].unique().sort()
    keep = set(dates[::STEP].to_list())
    d = d.filter(C("date").is_in(list(keep)))
    out: dict = {"cost": COST, "entry_every_days": STEP}
    for hz in ("f250", "f60"):
        x = d.filter(C(hz).is_not_null())
        x = x.with_columns(base=C(hz).mean().over("date"))
        mid = x["date"].unique().sort()[x["date"].n_unique() // 2]
        out[hz] = {
            "entry_dates": [str(x["date"].min()), str(x["date"].max())],
            "split": str(mid),
            "universe_mean": float(x[hz].mean()),
            "universe_median": float(x[hz].median()),
        }
        print(
            f"\n{hz}: entries {x['date'].min()}..{x['date'].max()} split {mid}; basket mean "
            f"{x[hz].mean():+.0%} median {x[hz].median():+.0%}"
        )
        for nm, mask in rules.items():
            r = {}
            for hn, sel in (
                ("all", C("date") >= x["date"].min()),
                ("h1", C("date") < mid),
                ("h2", C("date") >= mid),
            ):
                y = x.filter(sel)
                z = y.filter(mask)
                if z.height == 0:
                    r[hn] = {"n": 0}
                    continue
                per_day = z.group_by("date").agg(m=C(hz).mean(), b=C("base").first(), k=pl.len())
                ex = (per_day["m"] - per_day["b"]).to_numpy()
                r[hn] = {
                    "n": z.height,
                    "stocks": z[G].n_unique(),
                    "days": per_day.height,
                    "avg_names": float(per_day["k"].mean()),
                    "mean": float(z[hz].mean()),
                    "median": float(z[hz].median()),
                    "excess_mean": float(np.mean(ex)),
                    "excess_net": float(np.mean(ex)) - COST,
                    "win_vs_universe": float((ex > 0).mean()),
                    "base": float(y[hz].mean()),
                    "universe_share": z.height / y.height,
                }
            out[hz][nm] = r
            a_, h1, h2 = r["all"], r["h1"], r["h2"]
            if not a_["n"]:
                print(f"  {nm:6s} no entries")
                continue
            f = lambda q: (  # noqa: E731
                "n/a"
                if not q["n"]
                else f"{q['mean']:+.0%} (excess {q['excess_mean']:+.1%}, n={q['n']}, {q['stocks']} st, {q['days']} d)"
            )
            print(f"  {nm:6s} all {f(a_)} | h1 {f(h1)} | h2 {f(h2)}")
    # how many pass each day, and the earnings yield of the basket
    cnt = (
        p.group_by("date")
        .agg(
            y5=((C("pe") > 0) & (C("pe") <= 5)).sum(),
            y4=((C("pe") > 0) & (C("pe") <= 4)).sum(),
            n=C("pe").is_not_null().sum(),
            med_pe=C("pe").median(),
        )
        .sort("date")
    )
    out["pass_counts_last"] = cnt.tail(1).to_dicts()
    out["pass_counts_mean"] = {
        "y5": float(cnt["y5"].mean()),
        "y4": float(cnt["y4"].mean()),
        "n": float(cnt["n"].mean()),
    }
    last = p.filter(C("date") == p["date"].max())
    print("\nlast day:", cnt.tail(1).to_dicts())
    top = (
        last.filter((C("pe") > 0) & (C("pe") <= 5))
        .select("instrument_id", "pe", "liab_ratio", "net_g")
        .sort("pe")
        .to_dicts()
    )
    names = dict(
        fm.sqlite3.connect(fm.DB, uri=True)
        .execute("select id, symbol_fa from instruments")
        .fetchall()
    )
    out["today_pe_le_5"] = [
        {"symbol": names.get(r[G]), **{k: r[k] for k in ("pe", "liab_ratio", "net_g")}} for r in top
    ]
    print(len(top), "stocks with P/E<=5 on the last day")
    (HERE / "results_dividend_yield.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str)
    )


if __name__ == "__main__":
    main()
