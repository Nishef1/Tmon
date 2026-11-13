"""Do outside prices help pick stocks? Single-feature tests, then XGBoost with and without them.

Run after technical_signals/study.py and models.py with the same scratch dir (argv[1]).
Features, all point-in-time (a value is used only from its release date on, betas lag a week):
- usd_beta: 104-week beta of the stock's weekly excess return (over TEDPIX) on the dollar;
- usd_push: usd_beta x the dollar's change over the last 20 trading days;
- cu_push: the same with copper priced in rial (world copper x dollar);
- usd_pctl: where the stock's price in dollars sits in its own last three years (0 cheap, 1 dear).
Judged like models.py: daily rank IC and top-decile 20-day excess, both halves, against the
1.75% round-trip cost.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import polars as pl
import xgboost as xgb

from tmon.core.db import session_scope

SP = sys.argv[1]
C = pl.col
G = "instrument_id"
TEDPIX = "32097828799138957"
NEW = ["usd_beta", "usd_push", "cu_push", "usd_pctl"]

_spec = importlib.util.spec_from_file_location(
    "ts_models", Path(__file__).parents[1] / "technical_signals" / "models.py"
)
assert _spec and _spec.loader
tsm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tsm)


def sql(q: str) -> pl.DataFrame:
    with session_scope() as s:
        return pl.read_database(q, s.connection())


def daily_macro(days: pl.Series) -> pl.DataFrame:
    """Dollar, rial copper and TEDPIX as known on each trading day (by release date)."""
    m = sql(
        "select series, release_date, value from macro_series "
        "where series in ('usd_free','copper_usd')"
    ).with_columns(C("release_date").cast(pl.String).str.slice(0, 10).str.to_date())
    d = pl.DataFrame({"date": days.unique().sort()})
    for s in ("usd_free", "copper_usd"):
        one = m.filter(C("series") == s).group_by("release_date").agg(C("value").last())
        one = one.sort("release_date").rename({"release_date": "date", "value": s})
        d = d.join_asof(one, on="date", strategy="backward")
    idx = sql(
        f"select date, close as tedpix from market_index_daily where index_code='{TEDPIX}'"
    ).with_columns(C("date").cast(pl.String).str.slice(0, 10).str.to_date())
    d = d.join(idx, on="date", how="left").sort("date").with_columns(C("tedpix").forward_fill())
    return d.with_columns(
        cu_rial=C("copper_usd") * C("usd_free"),
        usd_m20=C("usd_free") / C("usd_free").shift(20) - 1,
    ).with_columns(cu_m20=C("cu_rial") / C("cu_rial").shift(20) - 1)


def features() -> pl.DataFrame:
    p = pl.read_parquet(SP + "/ts_panel.parquet").select(G, "date", "close", "liquid", "x20")
    mac = daily_macro(p["date"])
    p = p.join(mac, on="date", how="left").sort(G, "date")
    wk = (C("date") + pl.duration(days=2)).dt.truncate("1w")
    w = (
        p.group_by(G, wk=wk)
        .agg(C("close", "tedpix", "usd_free", "cu_rial").sort_by("date").last())
        .sort(G, "wk")
    )
    lg = lambda c: (C(c) / C(c).shift(1).over(G)).log()  # noqa: E731
    w = w.with_columns(ex=lg("close") - lg("tedpix"), u=lg("usd_free"), k=lg("cu_rial"))
    n = 104

    def beta(x: str) -> pl.Expr:
        mxy = (C("ex") * C(x)).rolling_mean(n, min_samples=52).over(G)
        mx = C(x).rolling_mean(n, min_samples=52).over(G)
        my = C("ex").rolling_mean(n, min_samples=52).over(G)
        vx = (C(x) ** 2).rolling_mean(n, min_samples=52).over(G) - mx**2
        return (mxy - mx * my) / vx

    w = w.with_columns(usd_beta=beta("u"), cu_beta=beta("k"))
    # use last week's beta on this week's days
    w = w.with_columns(C("usd_beta", "cu_beta").shift(1).over(G)).select(
        G, "wk", "usd_beta", "cu_beta"
    )
    p = p.with_columns(wk=wk).join(w, on=[G, "wk"], how="left")
    p = p.with_columns(
        usd_push=C("usd_beta") * C("usd_m20"),
        cu_push=C("cu_beta") * C("cu_m20"),
        pusd=(C("close") / C("usd_free")),
    )
    p = p.with_columns(
        usd_pctl=C("pusd").rolling_map(
            lambda s: float((s < s[-1]).mean()), window_size=750, min_samples=250
        ).over(G)
    )  # fmt: skip
    return p.select(G, "date", *NEW)


def single(p: pl.DataFrame) -> dict:
    d = p.filter(C("liquid") & C("x20").is_not_null())
    days = d["date"].unique().sort()
    d = d.filter(C("date").is_in(days.gather_every(5).implode()))
    mid = dt.date(2014, 6, 9)
    out = {}
    for f in NEW:
        e = d.drop_nulls(f)
        e = e.with_columns((C(f).rank() / pl.len()).over("date").alias("s"))
        out[f] = {
            "all": tsm.daily(e, "s"),
            "halves": [tsm.daily(e.filter(C("date") < mid), "s"),
                       tsm.daily(e.filter(C("date") >= mid), "s")],
        }  # fmt: skip
        a, h = out[f]["all"], out[f]["halves"]
        print(f"{f:9s} IC={a['ic']:+.3f} (t={a['ic_t']:+.1f}) top={a['top']:+.4f} "
              f"bot={a['bot']:+.4f} halves top={h[0]['top']:+.4f}/{h[1]['top']:+.4f}")  # fmt: skip
    return out


def walk(d: pl.DataFrame, feats: list[str]) -> pl.DataFrame:
    preds = []
    for y in range(2014, int(d["year"].max()) + 1):
        cut = dt.date(y, 1, 1) - dt.timedelta(days=30)
        tr = d.filter(C("date") < cut).drop_nulls(feats)
        te = d.filter(C("year") == y).drop_nulls(feats)
        if tr.height < 5000 or te.height == 0:
            continue
        m = xgb.XGBRegressor(n_estimators=300, learning_rate=0.03, max_depth=5,
                             min_child_weight=200, subsample=0.8, colsample_bytree=0.8,
                             tree_method="hist")  # fmt: skip
        m.fit(tr.select(feats).to_numpy(), tr["y"].to_numpy())
        preds.append(
            te.select("date", "x20").with_columns(
                s=pl.Series(m.predict(te.select(feats).to_numpy()))
            )
        )
    return pl.concat(preds)


def main() -> None:
    f = features()
    p = pl.read_parquet(SP + "/ts_panel.parquet").select(G, "date", "liquid", "x20")
    res = {"single": single(p.join(f, on=[G, "date"], how="left"))}
    d = tsm.load().join(f, on=[G, "date"], how="left")
    d = d.with_columns(*[(C(c).rank() / C(c).count()).over("date").alias(c) for c in NEW])
    # same rows for both models: only where the outside features exist (dollar from 2012)
    d = d.drop_nulls(NEW)
    mid = dt.date(2020, 6, 1)
    for name, feats in (("base", tsm.FEATS), ("base+macro", [*tsm.FEATS, *NEW])):
        pr = walk(d, feats)
        res[name] = {
            "all": tsm.daily(pr, "s"),
            "halves": [tsm.daily(pr.filter(C("date") < mid), "s"),
                       tsm.daily(pr.filter(C("date") >= mid), "s")],
        }  # fmt: skip
        a, h = res[name]["all"], res[name]["halves"]
        print(f"{name:11s} IC={a['ic']:+.3f} (t={a['ic_t']:+.1f}) top={a['top']:+.4f} "
              f"halves top={h[0]['top']:+.4f}/{h[1]['top']:+.4f} "
              f"IC={h[0]['ic']:+.3f}/{h[1]['ic']:+.3f}", flush=True)  # fmt: skip
    with open(SP + "/sd_model.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
