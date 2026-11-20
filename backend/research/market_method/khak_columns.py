"""Do the new derived columns tell a real floor from a falling knife? («طلا تو خاک»)

Same events as drawdown_floor.py: every ladder step (S1..S4, at 0.75/1.0/1.15/1.30 x the stock's
usual drawdown depth, 100-symbol liquid basket, events from 2023-04). The outcome is the 60-day
and 250-day return after the next close, minus 1.75% cost, minus the basket mean of the same entry
day (x60, x250). New here: at each event day, every column of features/extra.py and
features/relative.py (point in time) is read, and the question is whether a column ranks the events
by how they turned out.

Per column and per half of time (cut at the median event date): the Spearman correlation of the
column with x60 over the events. A column "agrees" when both halves have the same sign and each
|IC| >= 0.05. Because ~90 columns are tried, the number of columns that agree is compared with how
many agree when the outcomes are shuffled (200 permutations), which is what chance alone gives.
Then each agreeing column is used as a filter: events in its favourable third, mean x60 per half,
alone and among sound companies only.

The chance level shuffles outcomes only among events of the same calendar month (events cluster in
sell-offs). The "sound" filter (EPS TTM > 0, liabilities / assets < 0.7) is tested on its own with
the same month-clustered shuffle of its label. With TMON_UNIVERSE=pit (universe.py) the events and
the basket mean are those of the day's 100 most traded stocks.

Run from backend/ with the live env: python research/market_method/khak_columns.py
Output: docs/data/khak-columns-study.json (khak-columns-study-pit.json for the pit universe)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import drawdown_floor as dfl
import fundamental_model as fm
import universe as uv

from tmon.backtest.extra_columns_study import load_columns
from tmon.features.adjustment import apply_adjustments
from tmon.features.extra import EXTRA_COLUMNS
from tmon.features.relative import REL_COLUMNS, build_relative

C = pl.col
G = "instrument_id"
MIN_IC = 0.05
MIN_N = 150
PERMS = 200
DATA = Path(__file__).resolve().parents[3] / "docs" / "data"


def events() -> pl.DataFrame:
    p, ids = fm.build()
    fund = p.select("date", G, "eps_ttm", "liab_ratio")
    w = load_columns()
    a = (
        apply_adjustments(w["prices"])
        .filter((C("close") > 0) & C(G).is_in(list(ids)))
        .sort(G, "date")
        .with_columns(C("date").cast(pl.Date))
    )
    c = C("adj_close")
    a = a.with_columns(
        f60=(c.shift(-61) / c.shift(-1) - 1 - dfl.COST).over(G),
        f250=(c.shift(-251) / c.shift(-1) - 1 - dfl.COST).over(G),
    )
    a = dfl.with_basket_excess(a, w["prices"], ids)
    rows = []
    for (iid,), g in a.group_by(G, maintain_order=True):
        dts = g["date"].to_numpy().astype("datetime64[D]")
        ev, _rep, _st = dfl.scan(dts, g["adj_close"].to_numpy())
        rows.extend({G: iid, "date": g["date"][x.pop("i")], **x} for x in ev)
    e = pl.DataFrame(rows).join(
        a.filter(C("member")).select(G, "date", "x60", "x250"), on=[G, "date"], how="inner"
    )
    e = e.sort("date").join_asof(fund.sort("date"), on="date", by=G, strategy="backward")
    e = e.with_columns(sound=(C("eps_ttm") > 0) & (C("liab_ratio") < 0.7))
    rel = build_relative(
        w["prices"], w["clients"], w["extra"], sectors=w["sectors"], index_close=w["ix"]
    )
    e = e.join(w["extra"], on=[G, "date"], how="left").join(rel, on=[G, "date"], how="left")
    return e.with_columns((C("dd") / C("usual")).alias("depth_vs_usual"))


def _rank(x: np.ndarray) -> np.ndarray:
    return pl.Series(x).rank("average").to_numpy()


def ic(x: np.ndarray, y: np.ndarray) -> tuple[float | None, int]:
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < MIN_N or np.nanstd(x[ok]) == 0:
        return None, n
    return float(np.corrcoef(_rank(x[ok]), _rank(y[ok]))[0, 1]), n


def month_shuffle(y: np.ndarray, month: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """``y`` shuffled only among events of the same calendar month. Events cluster in sell-offs,
    so a shuffle across the whole half would break that clustering and make chance look narrower
    than it is."""
    out = y.copy()
    for m in np.unique(month):
        idx = np.flatnonzero(month == m)
        out[idx] = y[rng.permutation(idx)]
    return out


def sound_test(first: pl.DataFrame, second: pl.DataFrame, rng: np.random.Generator) -> dict:
    """Mean x60 of sound and other events per half, and how often a month-clustered shuffle of
    the sound label gives a gap (sound minus other) at least as large in both halves."""
    out: dict = {}
    gaps = []
    for name, df in (("first", first), ("second", second)):
        d = df.filter(C("sound").is_not_null())
        snd = d["sound"].to_numpy().astype(bool)
        y = d["x60"].to_numpy()
        gap = float(y[snd].mean() - y[~snd].mean()) if snd.any() and (~snd).any() else None
        out[name] = {
            "sound_mean_x60": float(y[snd].mean()) if snd.any() else None,
            "other_mean_x60": float(y[~snd].mean()) if (~snd).any() else None,
            "n_sound": int(snd.sum()),
            "n_other": int((~snd).sum()),
            "gap": gap,
        }
        gaps.append((y, snd, d["month"].to_numpy(), gap))
    if all(g[3] is not None for g in gaps):
        hits = 0
        for _ in range(PERMS):
            ok = True
            for y, snd, month, gap in gaps:
                s = month_shuffle(snd, month, rng)
                if not s.any() or s.all() or y[s].mean() - y[~s].mean() < gap:
                    ok = False
            hits += ok
        out["p_both_halves"] = (hits + 1) / (PERMS + 1)
    return out


def agree(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a * b > 0 and min(abs(a), abs(b)) >= MIN_IC


def main() -> None:
    e = events().filter(C("x60").is_not_null()).with_columns(month=C("date").dt.strftime("%Y-%m"))
    cut = e["date"].sort()[e.height // 2]
    first, second = e.filter(C("date") < cut), e.filter(C("date") >= cut)
    cols = [*EXTRA_COLUMNS, *REL_COLUMNS, "depth_vs_usual"]
    y1, y2 = first["x60"].to_numpy(), second["x60"].to_numpy()
    table: dict[str, dict[str, float | int | bool | None]] = {}
    for col in cols:
        a, na = ic(first[col].to_numpy().astype(float), y1)
        b, nb = ic(second[col].to_numpy().astype(float), y2)
        table[col] = {"ic1": a, "n1": na, "ic2": b, "n2": nb, "agree": agree(a, b)}
    n_agree = sum(1 for v in table.values() if v["agree"])

    rng = np.random.default_rng(7)
    xs1 = {c: first[c].to_numpy().astype(float) for c in cols}
    xs2 = {c: second[c].to_numpy().astype(float) for c in cols}
    m1, m2 = first["month"].to_numpy(), second["month"].to_numpy()
    null_counts = []
    for _ in range(PERMS):
        p1, p2 = month_shuffle(y1, m1, rng), month_shuffle(y2, m2, rng)
        k = 0
        for col in cols:
            if table[col]["ic1"] is None or table[col]["ic2"] is None:
                continue
            a, _ = ic(xs1[col], p1)
            b, _ = ic(xs2[col], p2)
            k += agree(a, b)
        null_counts.append(k)

    def third(df: pl.DataFrame, col: str, sign: float) -> pl.DataFrame:
        x = df[col].to_numpy().astype(float) * sign
        q = np.nanquantile(x, 2 / 3)
        return df.filter(pl.Series(np.where(np.isfinite(x), x >= q, False)))

    base = {
        "all": [float(first["x60"].mean()), float(second["x60"].mean())],
        "n": [first.height, second.height],
    }
    filters = {}
    for col, v in table.items():
        if not v["agree"]:
            continue
        sign = 1.0 if (v["ic1"] or 0) > 0 else -1.0
        f1, f2 = third(first, col, sign), third(second, col, sign)
        filters[col] = {
            "favourable": "high" if sign > 0 else "low",
            "mean_x60_first": float(f1["x60"].mean()),
            "mean_x60_second": float(f2["x60"].mean()),
            "n": [f1.height, f2.height],
        }
        s1, s2 = (third(d.filter(C("sound").fill_null(False)), col, sign) for d in (first, second))
        filters[col]["with_sound"] = {
            "mean_x60_first": float(s1["x60"].mean()) if s1.height else None,
            "mean_x60_second": float(s2["x60"].mean()) if s2.height else None,
            "n": [s1.height, s2.height],
        }
    out = {
        "universe": uv.mode(),
        "sound": sound_test(first, second, rng),
        "split_date": str(cut),
        "events": base,
        "columns_tried": len(cols),
        "columns_agreeing": n_agree,
        "chance_agreeing": {
            "mean": float(np.mean(null_counts)),
            "p95": float(np.percentile(null_counts, 95)),
            "max": int(np.max(null_counts)),
        },
        "table": table,
        "filters": filters,
    }
    (DATA / f"khak-columns-study{uv.suffix().replace('_', '-')}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print("events", base, "cut", cut)
    print("sound", out["sound"])
    print("agree", n_agree, "of", len(cols), "chance", out["chance_agreeing"])
    for col, f in sorted(
        filters.items(), key=lambda kv: -min(kv[1]["mean_x60_first"], kv[1]["mean_x60_second"])
    ):
        print(col, f)


if __name__ == "__main__":
    main()
