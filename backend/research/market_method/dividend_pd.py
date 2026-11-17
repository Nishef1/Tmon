"""The dividend-income method from a Telegram educator's two videos, with the real dividend per share.
(docs/reports/dividend-yield-2026-11.md)

Dividend per share (DPS), and EPS beside it, are read from the Codal decisions letter (ن-۵۲) of each
assembly (python -m tmon.ingest.codal.cli dividends). A letter is usable from the day it was announced.
Rules, all on the 100-symbol basket, entry = close of t+1, hold 250 and 60 trading days, adjusted prices
(so the ex-dividend drop is inside the return), cost 1.75% round trip:
  PD5    P/D <= 5     (price / latest announced DPS; yield >= 20%)
  PD4    P/D <= 4
  PD3    P/D <= 3     (the video's "ideal")
  PAY    payout (DPS / EPS) > 60%
  GROW   DPS growth over the previous assembly > 50%  (the video: above inflation)
  FULL   PD5 and PAY and GROW (the video's whole screen)
  PD5+PAY, PD5+GROW  halves of it
  cheapPD the third of covered stocks with the highest yield (control: no fixed cut)
Judged against (a) the whole basket's mean on the entry day and (b) the covered stocks' mean (those with a
dividend letter), in both halves of the entry dates; entries every 20 days (overlapping, so the honest sample
is the number of years). A last check: on entry days when the basket then fell (60-day mean < 0), did the
high-yield names fall less ("floor under the price in a correction")?
Run from backend/ with the live env:  python research/market_method/dividend_pd.py
Output: results_dividend_pd.json
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import fundamental_model as fm  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.adjustment import apply_adjustments  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402
from tmon.ingest.codal.tsetmc_content import decisions_of  # noqa: E402
from tmon.ingest.tsetmc.parsers import normalize_fa  # noqa: E402
from tmon.ingest.codal.parsers import ascii_digits  # noqa: E402

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175
STEP = 20
DB = fm.DB
STORE = Path(os.environ.get("TMON_OBJECT_STORE_DIR", "D:/Data/Tmon/data/objects")) / "raw-payloads"
_EPS = re.compile(r"PropertyName\">\s*EarningsPerShareAfterTax\s*</td>(.*?)</tr>", re.DOTALL)
_FY = re.compile(r"منتهی به\s*([0-9۰-۹]{4})/")


def eps_of(html: str) -> float | None:
    m = _EPS.search(html)
    if not m:
        return None
    v = re.search(r"CurrentPeriod[^>]*value=\"([^\"]*)\"|value=\"([^\"]*)\"[^>]*CurrentPeriod", m.group(1))
    if not v:
        return None
    t = ascii_digits(v.group(1) or v.group(2) or "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def letters(ids_by_symbol: dict[str, int]) -> pl.DataFrame:
    con = sqlite3.connect(DB, uri=True)
    rows = con.execute(
        "select l.symbol, e.announced_at, e.dps, e.title, l.url from corporate_events e "
        "join codal_letters l on l.tracing_no = e.tracing_no "
        "where e.stage = 'decisions' and e.dps is not null"
    ).fetchall()
    keys = dict(
        con.execute(
            "select source_url, object_key from raw_payloads "
            "where source = 'codal' and source_url like '%Decision.aspx%' order by id"
        ).fetchall()
    )
    ins = {c: i for i, c in con.execute("select id, ins_code from instruments").fetchall()}
    eps_ts: dict[tuple[int, str, str], float | None] = {}
    for url, key in con.execute(
        "select source_url, object_key from raw_payloads "
        "where source = 'tsetmc-codal' and source_url like '%/14/0/-1/%' order by id"
    ).fetchall():
        iid = ins.get(url.rsplit("/", 1)[1])
        if iid is None or not (STORE / key).exists():
            continue
        for r in decisions_of((STORE / key).read_bytes()):
            d = str(r["day"])
            eps_ts[(iid, f"{d[:4]}-{d[4:6]}-{d[6:8]}", r["title"])] = r["eps"]
    out = []
    for sym, ann, dps, title, url in rows:
        iid = ids_by_symbol.get(sym)
        fy = _FY.search(title or "")
        if iid is None or fy is None:
            continue
        eps = None
        key = keys.get(url)
        if key and (STORE / key).exists():
            eps = eps_of((STORE / key).read_text(encoding="utf-8", errors="ignore"))
        if eps is None:
            eps = eps_ts.get((iid, str(ann)[:10], normalize_fa(title or "")))
        out.append(
            {
                G: iid,
                "ann": ann,
                "dps": float(dps),
                "eps": eps,
                "fy": int(ascii_digits(fy.group(1))),
                "corr": "اصلاحیه" in (title or ""),
            }
        )
    d = pl.DataFrame(out).with_columns(C("ann").str.to_date())
    # one row per (stock, fiscal year): the latest announcement (a correction replaces the original)
    d = d.sort(G, "fy", "ann").group_by(G, "fy", maintain_order=True).last()
    d = d.sort(G, "ann").with_columns(
        dps_prev=C("dps").shift(1).over(G), fy_prev=C("fy").shift(1).over(G)
    )
    d = d.with_columns(
        growth=pl.when((C("fy") - C("fy_prev") == 1) & (C("dps_prev") > 0))
        .then(C("dps") / C("dps_prev") - 1)
        .otherwise(None),
        payout=pl.when(C("eps") > 0).then(C("dps") / C("eps")).otherwise(None),
    )
    return d.select(G, C("ann").alias("date"), "fy", "dps", "growth", "payout").sort("date")


def main() -> None:
    _p, ids = fm.build()
    names = dict(
        sqlite3.connect(DB, uri=True).execute("select id, symbol_fa from instruments").fetchall()
    )
    ids_by_symbol = {v: k for k, v in ids.items()}
    div = letters(ids_by_symbol)
    print("dividend rows:", div.height, "stocks:", div[G].n_unique())

    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    a = apply_adjustments(prices).filter(C("close") > 0).sort(G, "date")
    a = a.with_columns(C("date").cast(pl.Date))
    c = C("adj_close")
    a = a.with_columns(
        f250=(c.shift(-251) / c.shift(-1) - 1).over(G),
        f60=(c.shift(-61) / c.shift(-1) - 1).over(G),
    ).select("date", G, "close", "f250", "f60")
    d = a.filter(C(G).is_in(list(ids)) & (C("date") >= pl.date(2023, 4, 1))).sort("date")
    d = d.join_asof(
        div.sort("date").rename({"date": "ann_date"}),
        left_on="date",
        right_on="ann_date",
        by=G,
        strategy="backward",
        tolerance="400d",
    )
    d = d.with_columns(pd=pl.when(C("dps") > 0).then(C("close") / C("dps")).otherwise(None))
    d = d.with_columns(covered=C("dps").is_not_null())
    keep = set(d["date"].unique().sort()[::STEP].to_list())
    d = d.filter(C("date").is_in(list(keep)))
    d = d.with_columns(
        ypct=pl.when(C("pd").is_not_null())
        .then(1 / C("pd"))
        .otherwise(None)
    )
    d = d.with_columns(
        cheap=(
            C("ypct").rank("average", descending=True).over("date")
            / C("covered").sum().over("date")
            <= 1 / 3
        )
        & C("ypct").is_not_null()
    )
    pd5 = C("pd").is_not_null() & (C("pd") <= 5)
    pay = C("payout") > 0.6
    grow = C("growth") > 0.5
    rules = {
        "PD5": pd5,
        "PD4": C("pd").is_not_null() & (C("pd") <= 4),
        "PD3": C("pd").is_not_null() & (C("pd") <= 3),
        "PAY": pay,
        "GROW": grow,
        "PD5+PAY": pd5 & pay,
        "PD5+GROW": pd5 & grow,
        "FULL": pd5 & pay & grow,
        "cheapPD": C("cheap"),
    }
    out: dict = {
        "cost": COST,
        "entry_every_days": STEP,
        "dividend_stocks": div[G].n_unique(),
        "dividend_rows": div.height,
    }
    cov_share = d.group_by("date").agg(k=C("covered").sum(), n=pl.len())
    out["covered_per_day_mean"] = float(cov_share["k"].mean())
    out["basket_per_day_mean"] = float(cov_share["n"].mean())
    print(
        f"covered stocks per entry day {out['covered_per_day_mean']:.1f} of "
        f"{out['basket_per_day_mean']:.1f}"
    )
    for hz in ("f250", "f60"):
        x = d.filter(C(hz).is_not_null())
        x = x.with_columns(
            base=C(hz).mean().over("date"),
            base_cov=C(hz).filter(C("covered")).mean().over("date"),
        )
        mid = x["date"].unique().sort()[x["date"].n_unique() // 2]
        out[hz] = {
            "entry_dates": [str(x["date"].min()), str(x["date"].max())],
            "split": str(mid),
            "universe_mean": float(x[hz].mean()),
            "covered_mean": float(x.filter(C("covered"))[hz].mean()),
        }
        print(
            f"\n{hz}: entries {x['date'].min()}..{x['date'].max()} split {mid}; basket mean "
            f"{x[hz].mean():+.0%}, covered mean {out[hz]['covered_mean']:+.0%}"
        )
        for nm, mask in rules.items():
            r = {}
            for hn, sel in (
                ("all", C("date") >= x["date"].min()),
                ("h1", C("date") < mid),
                ("h2", C("date") >= mid),
                ("down", C("base") < 0),
            ):
                y = x.filter(sel)
                z = y.filter(mask)
                if z.height == 0:
                    r[hn] = {"n": 0}
                    continue
                g = z.group_by("date").agg(
                    m=C(hz).mean(), b=C("base").first(), bc=C("base_cov").first(), k=pl.len()
                )
                ex = (g["m"] - g["b"]).to_numpy()
                exc = (g["m"] - g["bc"]).to_numpy()
                r[hn] = {
                    "n": z.height,
                    "stocks": z[G].n_unique(),
                    "days": g.height,
                    "avg_names": float(g["k"].mean()),
                    "mean": float(z[hz].mean()),
                    "median": float(z[hz].median()),
                    "yield_mean": float(z["ypct"].mean()) if z["ypct"].null_count() < z.height else None,
                    "excess_mean": float(np.mean(ex)),
                    "excess_net": float(np.mean(ex)) - COST,
                    "excess_vs_covered": float(np.mean(exc)),
                    "win_vs_universe": float((ex > 0).mean()),
                }
            out[hz][nm] = r
            a_ = r["all"]
            if not a_["n"]:
                print(f"  {nm:9s} no entries")
                continue

            def f(q: dict) -> str:
                if not q["n"]:
                    return "n/a"
                return (
                    f"{q['mean']:+.0%} (ex {q['excess_mean']:+.1%}, cov {q['excess_vs_covered']:+.1%}, "
                    f"n={q['n']}, {q['stocks']}st, {q['days']}d)"
                )

            print(f"  {nm:9s} all {f(a_)} | h1 {f(r['h1'])} | h2 {f(r['h2'])} | down {f(r['down'])}")
    last = d.filter(C("date") == d["date"].max()).filter(pd5)
    out["last_day_pd5"] = [
        {"symbol": names.get(r[G]), "pd": r["pd"], "payout": r["payout"], "growth": r["growth"]}
        for r in last.iter_rows(named=True)
    ]
    print("last entry day P/D<=5:", out["last_day_pd5"])
    (HERE / "results_dividend_pd.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str)
    )


if __name__ == "__main__":
    main()
