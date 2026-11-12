"""LightGBM vs XGBoost vs a plain linear model on the technical indicators of study.py.

Run after study.py with the same scratch dir (argv[1]). Walk-forward by calendar year: each test
year is predicted by a model trained only on rows whose 20-day outcome was known 30 days before
the year began. Rows are the liquid universe every 5th trading day (less overlap). The target is
the 20-day excess return; scores are judged per day by rank IC and by the top-decile excess, which
must beat the 1.75% round-trip cost to be worth trading.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import lightgbm as lgb
import numpy as np
import polars as pl
import xgboost as xgb
from sklearn.linear_model import Ridge

SP = sys.argv[1]
C = pl.col
COST = 0.0175
FEATS = ["ret5", "ret20", "ret60", "dd", "rsi", "macd_n", "macd_h", "bbw", "vr", "net5",
         "power5", "d_sma20", "d_sma50", "d_sma200", "d_cloud_top", "d_cloud_bot", "tk",
         "lvalue"]  # fmt: skip


def load() -> pl.DataFrame:
    d = pl.read_parquet(SP + "/ts_panel.parquet").filter(C("liquid") & C("x20").is_not_null())
    days = d["date"].unique().sort()
    keep = days.gather_every(5)
    d = d.filter(C("date").is_in(keep.implode()))
    cl = C("close")
    d = d.with_columns(
        macd_n=C("macd") / cl,
        macd_h=(C("macd") - C("macd_sig")) / cl,
        d_sma20=cl / C("sma20") - 1,
        d_sma50=cl / C("sma50") - 1,
        d_sma200=cl / C("sma200") - 1,
        d_cloud_top=cl / C("cloud_top") - 1,
        d_cloud_bot=cl / C("cloud_bot") - 1,
        tk=C("tenkan") / C("kijun") - 1,
        lvalue=C("vmed20").log(),
    )
    # cross-sectional ranks per day: robust to regime level shifts and outliers
    d = d.with_columns(*[(C(f).rank() / pl.len()).over("date").alias(f) for f in FEATS])
    return d.with_columns(y=(C("x20").rank() / pl.len()).over("date"))


def daily(test: pl.DataFrame, col: str) -> dict:
    g = test.group_by("date").agg(
        ic=pl.corr(C(col), C("x20"), method="spearman"),
        top=C("x20").filter(C(col) >= C(col).quantile(0.9)).mean(),
        bot=C("x20").filter(C(col) <= C(col).quantile(0.1)).mean(),
    )
    return {
        "ic": float(g["ic"].mean()),
        "ic_t": float(g["ic"].mean() / g["ic"].std() * np.sqrt(g.height)),
        "top": float(g["top"].mean()),
        "bot": float(g["bot"].mean()),
        "days": g.height,
    }


def main() -> None:
    d = load()
    years = list(range(2010, int(d["year"].max()) + 1))
    preds = []
    for y in years:
        cut = dt.date(y, 1, 1) - dt.timedelta(days=30)
        tr = d.filter(C("date") < cut).drop_nulls(FEATS)
        te = d.filter(C("year") == y).drop_nulls(FEATS)
        if tr.height < 5000 or te.height == 0:
            continue
        xs, ys, xt = tr.select(FEATS).to_numpy(), tr["y"].to_numpy(), te.select(FEATS).to_numpy()
        m1 = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=31,
                               min_child_samples=200, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, verbose=-1)  # fmt: skip
        m2 = xgb.XGBRegressor(n_estimators=300, learning_rate=0.03, max_depth=5,
                              min_child_weight=200, subsample=0.8, colsample_bytree=0.8,
                              tree_method="hist")  # fmt: skip
        m3 = Ridge(alpha=10.0)
        for m in (m1, m2, m3):
            m.fit(xs, ys)
        preds.append(
            te.select("date", "year", "x20").with_columns(
                lgbm=pl.Series(m1.predict(xt)),
                xgb=pl.Series(m2.predict(xt)),
                ridge=pl.Series(m3.predict(xt)),
                mom60=te["ret60"],
                money=te["net5"],
            )
        )
        print(f"{y}: train={tr.height} test={te.height}", flush=True)
    p = pl.concat(preds)
    mid = p["date"].unique().sort()[p["date"].n_unique() // 2]
    res: dict = {"split": str(mid), "first": str(p["date"].min()), "last": str(p["date"].max())}
    for col in ("lgbm", "xgb", "ridge", "mom60", "money"):
        res[col] = {
            "all": daily(p, col),
            "halves": [
                daily(p.filter(C("date") < mid), col),
                daily(p.filter(C("date") >= mid), col),
            ],
        }
        a = res[col]["all"]
        h = res[col]["halves"]
        print(
            f"{col:6s} IC={a['ic']:+.3f} (t={a['ic_t']:+.1f}) top10={a['top']:+.4f} "
            f"bot10={a['bot']:+.4f} halves top={h[0]['top']:+.4f}/{h[1]['top']:+.4f} "
            f"IC={h[0]['ic']:+.3f}/{h[1]['ic']:+.3f}"
        )
    with open(SP + "/ts_models.json", "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
