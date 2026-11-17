"""Test the educator's fundamental rules on the 100-symbol basket, point in time.

Events are first publications of an income statement and balance sheet (TSETMC statements, table
`financial_statements`). The signal is known on the publish day t; entry is the close of the next
trading day; the outcome is the adjusted-close return over 20 and 60 trading days, minus the mean
of the same return over the whole basket on the same day ("excess"). Terciles are taken within the
publish month so the filing season does not leak into the signal. Both halves of time are shown.
The statements endpoint only serves the newest 15 filings per symbol, so the history is short.

Run from backend/ with the live env.  Output: results_fundamentals.json and a symbol table.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs
from tmon.ingest.tsetmc.statements import normalize_label

C = pl.col
G = "instrument_id"
HZ = (20, 60)
COST = 0.0175
DB = "file:D:/Data/Tmon/data/tmon-live.sqlite3?mode=ro"
HERE = Path(__file__).parent
BASKET = HERE.parents[1].parent / "data" / "liquid-basket.json"


def row(table: list[list[object]], *names: str, start: bool = False) -> list[float | None] | None:
    """First row whose normalised label equals (or starts with) one of ``names``."""
    for n in names:
        key = normalize_label(n)
        for r in table:
            lab = str(r[0])
            if lab == key or (start and lab.startswith(key)):
                return [v if isinstance(v, (int, float)) else None for v in r[1:]]
    return None


def at(v: list[float | None] | None, i: int) -> float | None:
    return v[i] if v is not None and i < len(v) else None


def growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev <= 0 or cur <= 0:
        return None
    return cur / prev - 1


def events(c: sqlite3.Connection, ids: dict[int, str]) -> list[dict]:
    rows = c.execute(
        "select instrument_id, published_at, kind, period_end, period_months, audited, balance, income"
        " from financial_statements order by instrument_id, published_at"
    ).fetchall()
    by: dict[int, list[tuple]] = {}
    for r in rows:
        if r[0] in ids and r[7]:
            by.setdefault(r[0], []).append(r)
    out: list[dict] = []
    for iid, lst in by.items():
        kind = "consolidated" if any(r[2] == "consolidated" for r in lst) else "separate"
        seen: set[str] = set()
        for _, pub, k, pend, months, aud, bal, inc in lst:  # earliest publication per period
            if k != kind or pend in seen:
                continue
            seen.add(pend)
            bal, inc = json.loads(bal), json.loads(inc)
            rev, gross = row(inc, "درآمدهای عملیاتی"), row(inc, "سود(زیان) ناخالص")
            op, net = row(inc, "سود(زیان) عملیاتی"), row(inc, "سود(زیان) خالص")
            eps = row(inc, "سود (زیان) خالص هر سهم", start=True) or row(
                inc, "سود(زیان) پایه هر سهم"
            )
            cap = row(inc, "سرمایه")
            annual = months == 12

            def ttm(v: list[float | None] | None, annual: bool = annual) -> float | None:
                cur, prev_same, prev_fy = at(v, 0), at(v, 1), at(v, 2)
                if cur is None:
                    return None
                if annual:
                    return cur
                return None if prev_same is None or prev_fy is None else cur + prev_fy - prev_same

            eq = row(bal, "جمع حقوق مالکانه")
            liab, assets = row(bal, "جمع بدهی ها"), row(bal, "جمع دارایی ها")
            ca, cl = row(bal, "جمع دارایی های جاری"), row(bal, "جمع بدهی های جاری")
            published = datetime.fromisoformat(pub)
            out.append(
                {
                    "iid": iid,
                    "sym": ids[iid],
                    "t": published.date(),
                    "period_end": pend,
                    "months": months,
                    "rev_g": growth(at(rev, 0), at(rev, 1)),
                    "net_g": growth(at(net, 0), at(net, 1)),
                    "op_g": growth(at(op, 0), at(op, 1)),
                    "gm": None
                    if not at(rev, 0) or at(gross, 0) is None
                    else at(gross, 0) / at(rev, 0),
                    "opm": None if not at(rev, 0) or at(op, 0) is None else at(op, 0) / at(rev, 0),
                    "opm_prev": None
                    if not at(rev, 1) or at(op, 1) is None
                    else at(op, 1) / at(rev, 1),
                    "eps_ttm": ttm(eps),
                    "rev_ttm": ttm(rev),
                    "net_ttm": ttm(net),
                    "capital": at(cap, 0),
                    "equity": at(eq, 0),
                    "liab_ratio": None
                    if not at(assets, 0) or at(liab, 0) is None
                    else at(liab, 0) / at(assets, 0),
                    "current_ratio": None
                    if not at(cl, 0) or at(ca, 0) is None
                    else at(ca, 0) / at(cl, 0),
                }
            )
    return out


def main() -> int:
    c = sqlite3.connect(DB, uri=True)
    syms = json.loads(BASKET.read_text(encoding="utf-8"))["symbols"]
    ids: dict[int, str] = {}
    for iid, sym in c.execute(
        "select id, symbol_fa from instruments where instrument_type='stock' order by id"
    ):
        if sym in syms and sym not in ids.values():
            ids[iid] = sym
    ev = events(c, ids)
    if not ev:
        print("no statements stored; run tmon.ingest.tsetmc.cli statements first")
        return 1
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("adj_close") > 0)).sort(G, "date")
    p = p.with_columns(C("date").cast(pl.Date))
    cl = C("adj_close")
    p = p.with_columns(
        *[(cl.shift(-1 - h).over(G) / cl.shift(-1).over(G) - 1).alias(f"f{h}") for h in HZ]
    )
    # basket mean on the same day, over the 100 symbols only
    pb = p.filter(C(G).is_in(list(ids)))
    mean = pb.group_by("date").agg(*[C(f"f{h}").mean().alias(f"m{h}") for h in HZ])
    pb = pb.join(mean, on="date").with_columns(
        *[(C(f"f{h}") - C(f"m{h}")).alias(f"x{h}") for h in HZ]
    )
    pb = pb.select(G, "date", "close", *[f"f{h}" for h in HZ], *[f"x{h}" for h in HZ]).sort("date")
    e = pl.DataFrame(ev, infer_schema_length=None).with_columns(C("t").cast(pl.Date)).sort("t")
    e = e.join_asof(
        pb, left_on="t", right_on="date", by_left="iid", by_right=G, strategy="backward"
    )
    e = e.filter(C("date").is_not_null() & ((C("t") - C("date")).dt.total_days() <= 5))
    sh = C("capital") * 1e6 / 1000  # nominal 1000 rial per share; capital in million rial
    e = e.with_columns(
        pe=pl.when(C("eps_ttm") > 0).then(C("close") / C("eps_ttm")),
        ps=pl.when(C("rev_ttm") > 0).then(C("close") * sh / (C("rev_ttm") * 1e6)),
        pb=pl.when(C("equity") > 0).then(C("close") * sh / (C("equity") * 1e6)),
        opm_chg=C("opm") - C("opm_prev"),
        season=C("t").dt.strftime("%Y-%m"),
    )

    def tercile(col: str) -> pl.Expr:
        r = C(col).rank("average").over("season")
        n = C(col).count().over("season")
        return pl.when(C(col).is_null() | (n < 6)).then(None).otherwise(r / n)

    e = e.with_columns(pe_r=tercile("pe"), pb_r=tercile("pb"), ps_r=tercile("ps"))
    mid = e["t"].sort()[e.height // 2]
    tests = [
        ("all events", pl.lit(True)),
        ("R1 cheap: P/E TTM lowest third", C("pe_r") <= 1 / 3),
        ("R1b dear: P/E TTM top third", C("pe_r") > 2 / 3),
        ("R1c cheap: P/B lowest third", C("pb_r") <= 1 / 3),
        ("R1d cheap: P/S lowest third", C("ps_r") <= 1 / 3),
        ("R2 growth: revenue > +20% and profit > +30%", (C("rev_g") > 0.20) & (C("net_g") > 0.30)),
        ("R2b shrinking: revenue < 0 or profit < 0", (C("rev_g") < 0) | (C("net_g") < 0)),
        ("R3 margin up: operating margin +2 points", C("opm_chg") > 0.02),
        ("R3b margin down: operating margin -2 points", C("opm_chg") < -0.02),
        (
            "R4 operating leverage: op profit growth > revenue growth + 10pt",
            C("op_g") - C("rev_g") > 0.10,
        ),
        ("R5 low leverage: liabilities/assets < 60%", C("liab_ratio") < 0.60),
        (
            "S1 his screen: R2 and P/E not top third and R5",
            (C("rev_g") > 0.20)
            & (C("net_g") > 0.30)
            & (C("pe_r") <= 2 / 3)
            & (C("liab_ratio") < 0.60),
        ),
    ]

    def stat(name: str, mask: pl.Expr) -> dict:
        r: dict = {"name": name}
        for hlf, sel in (("h1", C("t") < mid), ("h2", C("t") >= mid)):
            d = e.filter(sel & mask.fill_null(False))
            r[hlf] = {"n": d.height, "syms": d["iid"].n_unique()}
            for h in HZ:
                v = d.filter(C(f"x{h}").is_not_null())
                r[hlf][f"x{h}"] = v[f"x{h}"].mean() if v.height else None
                r[hlf][f"net{h}"] = (v[f"f{h}"].mean() - COST) if v.height else None
                r[hlf][f"n{h}"] = v.height
        return r

    out = {
        "split": str(mid),
        "events": e.height,
        "span": [str(e["t"].min()), str(e["t"].max())],
        "rows": [stat(n, m) for n, m in tests],
    }
    # rank correlation of each signal with the 60-day excess, per half
    ic: dict = {}
    for col in ("pe", "pb", "ps", "rev_g", "net_g", "opm_chg", "liab_ratio"):
        ic[col] = {}
        for hlf, sel in (("h1", C("t") < mid), ("h2", C("t") >= mid)):
            d = e.filter(sel & C(col).is_not_null() & C("x20").is_not_null())
            ic[col][hlf] = {
                "n": d.height,
                "ic20": d.select(pl.corr(C(col).rank(), C("x20").rank()))[0, 0]
                if d.height > 10
                else None,
            }
    out["rank_ic_20d"] = ic
    # within each filing month: does the group that passes beat the events of that month that fail?
    seasons: dict = {}
    for name, mask in tests[1:]:
        wins = tot = 0
        for _, d in e.filter(C("x60").is_not_null()).group_by("season"):
            a = d.filter(mask.fill_null(False))["x60"]
            b = d.filter(~mask.fill_null(False))["x60"]
            if len(a) >= 2 and len(b) >= 2:
                tot += 1
                wins += a.mean() > b.mean()
        seasons[name] = [int(wins), tot]
    out["seasons_pass_beats_rest_60d"] = seasons
    out["events_by_year"] = dict(
        sorted(e.group_by(C("t").dt.year().alias("y")).len().iter_rows(), key=lambda x: x[0])
    )
    (HERE / "results_fundamentals.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str)
    )
    print("events", e.height, "span", out["span"], "split", mid)
    for r in out["rows"]:

        def f(h: str) -> str:
            d = r[h]
            if not d["n"]:
                return "none"
            x20, x60 = d["x20"], d["x60"]
            return f"n={d['n']:3d}/{d['syms']:3d} ex20 {100 * x20:+5.1f}% ex60 {('%+5.1f%%' % (100 * x60)) if x60 is not None else '  n/a '} (n60={d['n60']})"

        print(f"{r['name'][:52]:52s} H1 {f('h1')} | H2 {f('h2')}")
    print("rank IC 20d:", json.dumps(ic, ensure_ascii=False))
    # latest signals per symbol: only filings from the last 200 days count as current
    latest = e.sort("t").group_by("iid", maintain_order=True).last()
    latest = latest.with_columns(
        age=(pl.lit(date(2026, 11, 17)) - C("t")).dt.total_days(),
        s1=(C("rev_g") > 0.20)
        & (C("net_g") > 0.30)
        & (C("pe_r") <= 2 / 3)
        & (C("liab_ratio") < 0.60),
    )
    cur = latest.filter(C("age") <= 200)
    cols = ["sym", "t", "months", "age", "pe", "pb", "rev_g", "net_g", "opm_chg", "liab_ratio"]
    cur.select(*cols, "s1", "x20").sort("sym").write_csv(HERE / "symbols_latest.csv")
    scr = cur.filter(C("s1").fill_null(False)).sort("net_g", descending=True)
    print("current filings:", cur.height, "of", latest.height, "symbols with statements")
    print("screen S1 passes now:", scr["sym"].to_list())
    # return since the filing (partial window): adjusted close now over the close after publication,
    # minus the basket mean over the same window
    ac = p.filter(C(G).is_in(list(ids))).select(G, "date", "adj_close").sort("date")
    last = dict(ac.group_by(G).agg(C("adj_close").last().alias("l")).iter_rows())
    by_sym = {k[0]: v for k, v in ac.partition_by(G, as_dict=True).items()}

    def since(iid: int, t0: date) -> float | None:
        d = by_sym.get(iid)
        if d is None:
            return None
        nxt = d.filter(C("date") > t0)
        if nxt.height < 2:
            return None
        e0 = nxt["date"][0]
        mine = last[iid] / nxt["adj_close"][0] - 1
        vals = []
        for k, dd in by_sym.items():
            row0 = dd.filter(C("date") == e0)
            if row0.height:
                vals.append(last[k] / row0["adj_close"][0] - 1)
        return mine - sum(vals) / len(vals) if len(vals) >= 20 else None

    for r in scr.iter_rows(named=True):
        r["x20"] = since(r["iid"], r["t"])
        pe = r["pe"]
        print(
            f"  {r['sym']:8s} {r['t']} {r['months']:>2}m  P/E {pe:5.1f}  rev {100 * r['rev_g']:+4.0f}%  "
            f"profit {100 * r['net_g']:+5.0f}%  opm {100 * (r['opm_chg'] or 0):+5.1f}pt  "
            f"excess20 since {('%+.1f%%' % (100 * r['x20'])) if r['x20'] is not None else 'n/a'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
