"""Five learners on the same features, judged the same way (docs/reports/ml-models-2026-11.md).

Question: among Ridge, Random Forest, Extra Trees, LightGBM and XGBoost, which ranks the day's
universe best for the next 20 trading days, after the 1.75% round trip, in both halves of the test?

Data: treasure_hunt.panel() in the universe set by TMON_UNIVERSE (run with pit: each day's top 100
by 20-day median traded value up to the previous close). Features: its 19 stock features as rank
percentiles within the day, and its 3 market features (basket drawdown, basket 20-day return,
breadth) as they are. Target: the stock's 20-day return from the close of t+1, ranked within the
day. A day whose next session is a one-price buy queue cannot be entered and is dropped.

Walk forward by calendar year from 2021: each test year is predicted by models fitted only on rows
whose 20-day outcome was known before the year began (35 calendar days of embargo). Training rows
are every 5th trading day (less overlap between targets); test rows are every day.

Tuning, the same budget for every learner: four settings each, chosen on the last training year as
validation (fitted on the years before it, with the same embargo), by mean daily rank IC; the
winner is refitted on the whole training window. Learners with randomness are refitted with three
seeds and their predictions averaged; the widest gap in a year's IC between single seeds is
reported.

Baselines: EW, the equal-weight sum of feature ranks signed by their training IC (no fitting beyond
signs); mom120, the 120-day return alone; and ENS, the mean of the five learners' daily ranks.

Measures on the test days, per learner:
  ic        mean daily Spearman correlation between score and 20-day return
  top10     mean 20-day return of the day's 10 best scored names minus the universe mean (gross)
  net10     mean 20-day return of the 10 best minus the cost (1.75%)
  t         t of a daily series over non-overlapping 20-day steps (median over the 20 offsets)
  halves    the same, before and after the median test day; years, the same per test year
  vs_ew     daily IC minus EW's, with its non-overlapping t (better than no learning?)
  paired    daily IC of one learner minus another's, with its t
Run from backend/ with the live env and TMON_UNIVERSE=pit:
  python research/market_method/ml_models.py
TMON_PLACEBO=1 shuffles the training target within each day (a leak check).
Output: results_ml_models_pit.json (results_ml_models_pit_placebo.json)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
import xgboost as xgb
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).parent))
import universe as uv
from treasure_hunt import MARKET, STOCK, panel

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175
H = 20
EMBARGO = dt.timedelta(days=35)
FIRST_TEST = 2021
SEEDS = (0, 1, 2)
FEATS = STOCK + MARKET
LEARNERS = ("ridge", "rf", "et", "lgbm", "xgb")

GRID: dict[str, list[dict]] = {
    "ridge": [{"alpha": a} for a in (0.1, 1.0, 10.0, 100.0)],
    "rf": [{"max_depth": d, "min_samples_leaf": leaf} for d in (6, 12) for leaf in (50, 300)],
    "et": [{"max_depth": d, "min_samples_leaf": leaf} for d in (6, 12) for leaf in (50, 300)],
    "lgbm": [{"num_leaves": n, "min_child_samples": m} for n in (7, 31) for m in (100, 400)],
    "xgb": [{"max_depth": d, "min_child_weight": m} for d in (3, 6) for m in (100, 400)],
}


def make(name: str, p: dict, seed: int):
    if name == "ridge":
        return Ridge(**p)
    if name == "rf":
        return RandomForestRegressor(
            n_estimators=300, max_features=0.33, n_jobs=-1, random_state=seed, **p
        )
    if name == "et":
        return ExtraTreesRegressor(
            n_estimators=300, max_features=0.5, n_jobs=-1, random_state=seed, **p
        )
    if name == "lgbm":
        return lgb.LGBMRegressor(
            n_estimators=300, learning_rate=0.03, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.8, random_state=seed, n_jobs=-1, verbose=-1, **p,
        )  # fmt: skip
    return xgb.XGBRegressor(
        n_estimators=300, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", random_state=seed, n_jobs=-1, **p,
    )  # fmt: skip


def load() -> pl.DataFrame:
    a, _ = panel(drop_queue=True)
    a = a.filter(C("f20").is_not_null()).with_columns(
        r=C("f20") + COST,  # gross 20-day return from the close of t+1
        year=C("date").dt.year(),
    )
    a = a.with_columns(
        *[(C(f).rank("average") / C(f).count()).over("date").alias(f) for f in STOCK],
        y=(C("r").rank("average") / pl.len()).over("date"),
    )
    return a.select("date", "year", G, "r", "y", *FEATS)


def xy(d: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    # trees take missing values as the middle rank; market features are never missing here
    x = d.select([C(f).fill_null(0.5) if f in STOCK else C(f) for f in FEATS]).to_numpy()
    return x, d["y"].to_numpy()


def day_ic(d: pl.DataFrame, col: str) -> np.ndarray:
    g = d.group_by("date").agg(ic=pl.corr(C(col), C("r"), method="spearman")).sort("date")
    return g["ic"].fill_nan(None).drop_nulls().to_numpy()


def thin(x: np.ndarray) -> float:
    """Median t over the 20 start offsets of a non-overlapping 20-day sample of a daily series."""
    ts = []
    for k in range(H):
        s = x[k::H]
        if len(s) > 2 and s.std(ddof=1) > 0:
            ts.append(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))
    return float(np.median(ts)) if ts else float("nan")


def judge(d: pl.DataFrame, col: str) -> dict:
    g = (
        d.with_columns(rk=C(col).rank("ordinal", descending=True).over("date"))
        .group_by("date")
        .agg(
            ic=pl.corr(C(col), C("r"), method="spearman"),
            top=C("r").filter(C("rk") <= 10).mean(),
            all_=C("r").mean(),
        )
        .sort("date")
        .with_columns(ex=C("top") - C("all_"))
    )
    ic = g["ic"].fill_nan(None).fill_null(0.0).to_numpy()
    ex = g["ex"].to_numpy()
    return {
        "days": g.height,
        "ic": float(ic.mean()),
        "ic_t": thin(ic),
        "top10": float(ex.mean()),
        "top10_t": thin(ex),
        "net10": float(g["top"].mean() - COST),
        "univ_net": float(g["all_"].mean() - COST),
        "hit10": float((ex > 0).mean()),
    }


def tune(name: str, tr: pl.DataFrame) -> dict:
    last = tr["date"].max()
    v0 = dt.date(last.year, 1, 1)
    fit = tr.filter(C("date") < v0 - EMBARGO)
    val = tr.filter(C("date") >= v0)
    if fit.height < 3000 or val.height < 500:
        return GRID[name][len(GRID[name]) // 2]
    xf, yf = xy(fit)
    xv, _ = xy(val)
    best, score = GRID[name][0], -9.0
    for p in GRID[name]:
        m = make(name, p, 0)
        m.fit(xf, yf)
        s = float(day_ic(val.with_columns(pred=pl.Series(m.predict(xv))), "pred").mean())
        if s > score:
            best, score = p, s
    return best


def main() -> None:
    t0 = time.time()
    d = load()
    placebo = os.environ.get("TMON_PLACEBO") == "1"
    if placebo:  # the learners see a target shuffled within each day; any skill left is a leak
        d = d.with_columns(y=C("y").shuffle(seed=0).over("date"))
    print("rows", d.height, "days", d["date"].n_unique(), "from", d["date"].min(), flush=True)
    days = d["date"].unique().sort()
    sample = set(days.gather_every(5).to_list())
    preds, chosen, seed_ic = [], {}, {k: [] for k in LEARNERS if k != "ridge"}
    for y in range(FIRST_TEST, int(d["year"].max()) + 1):
        start = dt.date(y, 1, 1)
        tr = d.filter((C("date") < start - EMBARGO) & C("date").is_in(sample))
        te = d.filter(C("year") == y)
        if te.height == 0:
            continue
        xs, ys = xy(tr)
        xt, _ = xy(te)
        out = te.select("date", G, "r")
        # EW: sign of each feature's training IC, then the sum of signed ranks
        signs = {
            f: float(np.sign(day_ic(tr.rename({"y": "_y"}).with_columns(r=C("_y")), f).mean()) or 1)
            for f in STOCK
        }
        out = out.with_columns(
            ew=pl.sum_horizontal([te[f].fill_null(0.5) * s for f, s in signs.items()]),
            mom120=te["r120"],
        )
        for name in LEARNERS:
            p = tune(name, tr)
            chosen.setdefault(name, []).append({"year": y, **p})
            seeds = (0,) if name == "ridge" else SEEDS
            each = []
            for s in seeds:
                m = make(name, p, s)
                m.fit(xs, ys)
                each.append(m.predict(xt))
            if name != "ridge":
                ics = [
                    float(day_ic(te.with_columns(pred=pl.Series(e)), "pred").mean()) for e in each
                ]
                seed_ic[name].append(max(ics) - min(ics))
            out = out.with_columns(pl.Series(name, np.mean(each, axis=0)))
        out = out.with_columns(ens=pl.mean_horizontal([C(k).rank().over("date") for k in LEARNERS]))
        preds.append(out)
        print(f"{y}: train {tr.height} test {te.height} ({time.time() - t0:.0f}s)", flush=True)
    p = pl.concat(preds)
    mid = p["date"].unique().sort()[p["date"].n_unique() // 2]
    cols = ("ew", "mom120", *LEARNERS, "ens")
    res: dict = {
        "universe": uv.mode(),
        "test": [str(p["date"].min()), str(p["date"].max())],
        "split": str(mid),
        "chosen": chosen,
        "seed_ic_range_max": {k: max(v) for k, v in seed_ic.items() if v},
    }
    ew_ic = day_ic(p, "ew")
    for col in cols:
        r = {
            "all": judge(p, col),
            "halves": [
                judge(p.filter(C("date") < mid), col),
                judge(p.filter(C("date") >= mid), col),
            ],
        }
        r["years"] = {
            str(y): judge(p.filter(C("date").dt.year() == y), col)
            for y in p["date"].dt.year().unique().sort()
        }
        if col != "ew":
            diff = day_ic(p, col) - ew_ic
            r["vs_ew"] = {"ic": float(diff.mean()), "t": thin(diff)}
        res[col] = r
        a, h = r["all"], r["halves"]
        print(
            f"{col:6s} IC {a['ic']:+.3f} (t {a['ic_t']:+.1f})  top10 {a['top10']:+.2%} "
            f"(t {a['top10_t']:+.1f}) net10 {a['net10']:+.2%}  halves top10 "
            f"{h[0]['top10']:+.2%} / {h[1]['top10']:+.2%}  IC {h[0]['ic']:+.3f} / {h[1]['ic']:+.3f}"
            + (
                f"  vs EW {r['vs_ew']['ic']:+.3f} (t {r['vs_ew']['t']:+.1f})" if col != "ew" else ""
            ),
            flush=True,
        )
    # paired: does a learner rank better than another on the same days? (row beats column)
    ics = {k: day_ic(p, k) for k in (*LEARNERS, "ens")}
    res["paired"] = {
        a: {
            b: {"ic": float((ics[a] - ics[b]).mean()), "t": thin(ics[a] - ics[b])}
            for b in ics
            if b != a
        }
        for a in ics
    }
    for a in ics:
        print(
            a, " ".join(f"{b}:{v['ic']:+.3f}({v['t']:+.1f})" for b, v in res["paired"][a].items())
        )
    (HERE / f"results_ml_models{uv.suffix()}{'_placebo' if placebo else ''}.json").write_text(
        json.dumps(res, indent=1, default=str)
    )


if __name__ == "__main__":
    main()
