"""Does adding the filed statements to the v2 signals help, out of sample?  (docs/reports/fundamental-model-2026-11.md)

Universe: the 100-symbol basket (data/liquid-basket.json), eligible, not in a buy queue, with the four
v2 signals present. Fundamentals are as of the day after the publish day, never earlier (the statements
come from `financial_statements`, first publication per period). The cheap/growth score F is the mean
percentile rank of -P/E, net-profit growth, operating-margin change and -liabilities/assets.

Strategies (all pick the top 10 of the day's cross-section and are judged on the 20-day return from
the close of t+1, minus the mean of the whole cross-section, i.e. "excess"):
  V0 the v2 composite alone (four equal-weight signals)
  F  the fundamentals score alone
  V0+F  the mean of the two percentile ranks
  GBM  LightGBM regression of the day's rank of the 20-day return, walk-forward, retrained every 40
       trading days with a 22-day gap; GBM-p is the same model without fundamentals
Both halves of the test period are shown; "indep" uses every 20th day (non-overlapping holds) and is
the honest sample size. Round trip cost 1.75% is charged once per hold in the "net" columns.
Run from backend/ with the live env.  Output: results_model.json, today_ranking.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import universe as uv  # noqa: E402
from fundamentals_study import BASKET, DB, events  # noqa: E402

from tmon.backtest.signal_decay import SIGNALS, adjusted_close, build_panel  # noqa: E402
from tmon.core.db import session_scope  # noqa: E402
from tmon.core.engine_config import get_engine_config  # noqa: E402
from tmon.domain.rules import RuleBook  # noqa: E402
from tmon.features.builder import KEYS, build_features  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402

C = pl.col
G = "instrument_id"
H = 20
GAP = 22  # trading days between the last training day and the first test day
RETRAIN = 40
FIRST_TEST = "2024-07-01"
FROM = "2023-04-01"
COST = 0.0175
TOP = 10
FUND = ["pe", "pb", "ps", "rev_g", "net_g", "opm_chg", "liab_ratio"]
HERE = Path(__file__).parent


def pct(col: str) -> pl.Expr:
    return (C(col).rank("average").over("date") - 0.5) / C(col).count().over("date")


def build() -> tuple[pl.DataFrame, dict[int, str]]:
    """The panel of the universe chosen by TMON_UNIVERSE (universe.py). Statements exist only for
    the 100 basket names, so in the point-in-time universe the other members have no F score."""
    c = sqlite3.connect(DB, uri=True)
    pit = uv.mode() == "pit"
    if pit:
        ids = uv.stock_ids(DB)
    else:
        syms = json.loads(BASKET.read_text(encoding="utf-8"))["symbols"]
        ids = {}
        for iid, sym in c.execute(
            "select id, symbol_fa from instruments where instrument_type='stock' order by id"
        ):
            if sym in syms and sym not in ids.values():
                ids[iid] = sym
    ev = events(c, ids)
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
    feats = build_features(prices, clients, rules, sectors=sectors)
    panel = build_panel(feats, adjusted_close(prices), cfg, horizons=(H,))
    panel = panel.filter(C(G).is_in(list(ids)) & (C("queue_state") != "buy_queue"))
    panel = panel.with_columns(C("date").cast(pl.Date))
    if pit:
        panel = panel.join(uv.pit_members(prices, ids), on=["date", G], how="semi")
    raw = prices.select(*KEYS, "close").with_columns(C("date").cast(pl.Date))
    panel = panel.join(raw, on=list(KEYS), how="left").filter(
        C("date") >= pl.lit(FROM).str.to_date()
    )
    e = (
        pl.DataFrame(ev, infer_schema_length=None)
        .with_columns(avail=C("t").cast(pl.Date) + pl.duration(days=1))
        .sort("avail")
        .select(
            "iid",
            "avail",
            "eps_ttm",
            "rev_ttm",
            "net_ttm",
            "capital",
            "equity",
            "rev_g",
            "net_g",
            "opm",
            "opm_prev",
            "liab_ratio",
        )  # fmt: skip
    )
    panel = panel.sort("date").join_asof(
        e, left_on="date", right_on="avail", by_left=G, by_right="iid", strategy="backward"
    )
    sh = C("capital") * 1e6 / 1000
    panel = panel.with_columns(
        pe=pl.when(C("eps_ttm") > 0).then(C("close") / C("eps_ttm")),
        pb=pl.when(C("equity") > 0).then(C("close") * sh / (C("equity") * 1e6)),
        ps=pl.when(C("rev_ttm") > 0).then(C("close") * sh / (C("rev_ttm") * 1e6)),
        opm_chg=C("opm") - C("opm_prev"),
        age=(C("date") - C("avail")).dt.total_days(),
    )
    # a filing older than a year is stale: fundamentals unknown
    stale = C("age") > 400
    panel = panel.with_columns(*[pl.when(stale).then(None).otherwise(C(f)).alias(f) for f in FUND])
    panel = panel.with_columns(
        *[pct(f).alias(f"q_{f}") for f in FUND],
    ).with_columns(
        F=pl.mean_horizontal((1 - C("q_pe")), C("q_net_g"), C("q_opm_chg"), (1 - C("q_liab_ratio")))
    )
    # at least two of the four must be known, else no fundamentals score
    known = pl.sum_horizontal(
        C("q_pe").is_not_null(), C("q_net_g").is_not_null(), C("q_opm_chg").is_not_null(),
        C("q_liab_ratio").is_not_null(),
    )  # fmt: skip
    panel = panel.with_columns(F=pl.when(known >= 2).then(C("F")))
    panel = panel.with_columns(
        qF=pct("F"),
        qV=pct("composite"),
    ).with_columns(
        VF=pl.when(C("qF").is_not_null()).then((C("qV") + C("qF")) / 2),
        y=pct(f"fwd_{H}"),
        x=C(f"fwd_{H}") - C(f"fwd_{H}").mean().over("date"),
    )
    return panel.sort("date", G), ids


def fit_predict(train: pl.DataFrame, test: pl.DataFrame, cols: list[str]) -> np.ndarray:
    m = lgb.LGBMRegressor(
        n_estimators=200, learning_rate=0.03, num_leaves=8, min_child_samples=300,
        subsample=0.7, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1,
        random_state=7, n_jobs=4,
    )  # fmt: skip
    m.fit(train.select(cols).to_numpy(), train["y"].to_numpy())
    return m.predict(test.select(cols).to_numpy())


def walk_forward(p: pl.DataFrame) -> pl.DataFrame:
    dates = p["date"].unique().sort().to_list()
    start = next(i for i, d in enumerate(dates) if str(d) >= FIRST_TEST)
    base = [f"r_{s}" for s in SIGNALS]
    full = base + [f"q_{f}" for f in FUND] + ["age"]
    parts = []
    for i in range(start, len(dates), RETRAIN):
        cut = dates[i - GAP]
        tr = p.filter((C("date") <= cut) & C("y").is_not_null())
        te = p.filter(
            (C("date") >= dates[i]) & (C("date") <= dates[min(i + RETRAIN - 1, len(dates) - 1)])
        )
        if tr.height < 3000 or te.is_empty():
            continue
        parts.append(
            te.with_columns(
                pl.Series("gbm", fit_predict(tr, te, full)),
                pl.Series("gbm_p", fit_predict(tr, te, base)),
            )
        )
    return pl.concat(parts)


def judge(d: pl.DataFrame, col: str, name: str, mid, top: int = TOP) -> dict:
    """Top-10 by ``col`` each day: mean excess over the cross-section, overall and non-overlapping."""
    ok = d.filter(C(col).is_not_null() & C("x").is_not_null())
    ok = ok.with_columns(rk=C(col).rank("ordinal", descending=True).over("date"))
    per = (
        ok.filter(C("rk") <= top)
        .group_by("date")
        .agg(ex=C("x").mean(), raw=C(f"fwd_{H}").mean(), n=pl.len())
        .filter(C("n") >= top)
        .sort("date")
    )
    ic = (
        ok.filter(C(f"fwd_{H}").is_not_null())
        .with_columns(
            a=C(col).rank("average").over("date"), b=C(f"fwd_{H}").rank("average").over("date")
        )
        .group_by("date")
        .agg(ic=pl.corr("a", "b"))
        .drop_nulls()
        .filter(C("ic").is_finite())
    )
    out: dict = {"name": name}
    for hlf, sel in (("h1", C("date") < mid), ("h2", C("date") >= mid)):
        q = per.filter(sel)
        ind = q.gather_every(H)
        out[hlf] = {
            "days": q.height,
            "ex": q["ex"].mean(),
            "t": (q["ex"].mean() / (q["ex"].std() / (max(q.height / H, 1.0) ** 0.5)))
            if q.height > 1
            else None,
            "ex_indep": ind["ex"].mean(),
            "n_indep": ind.height,
            "win_indep": float((ind["ex"] > 0).mean()) if ind.height else None,
            "net_raw_indep": (ind["raw"].mean() - COST) if ind.height else None,
            "ic": ic.filter(sel)["ic"].mean(),
        }
    return out


def today(p: pl.DataFrame, ids: dict[int, str]) -> list[dict]:
    """Latest day: the V0+F ranking of the basket and which names pass the educator's screen."""
    day = p["date"].max()
    d = p.filter(C("date") == day).with_columns(
        s1=(C("age") <= 200)
        & (C("rev_g") > 0.2)
        & (C("net_g") > 0.3)
        & (C("q_pe").fill_null(1.0) <= 2 / 3)
        & (C("liab_ratio") < 0.6)
    )
    d = d.sort("VF", descending=True, nulls_last=True)
    out = []
    for r in d.iter_rows(named=True):
        out.append(
            {
                "symbol": ids.get(r[G]),
                "VF": r["VF"], "qV": r["qV"], "qF": r["qF"],
                "pe": r["pe"], "pb": r["pb"], "net_g": r["net_g"], "rev_g": r["rev_g"],
                "opm_chg": r["opm_chg"], "liab_ratio": r["liab_ratio"], "age_days": r["age"],
                "s1": bool(r["s1"]) if r["s1"] is not None else False,
            }
        )  # fmt: skip
    (HERE / f"today_ranking{uv.suffix()}.json").write_text(
        json.dumps({"date": str(day), "rows": out}, ensure_ascii=False, indent=1)
    )
    return out


def main() -> int:
    p, ids = build()
    print(
        "panel",
        p.height,
        "days",
        p["date"].n_unique(),
        "with F",
        p.filter(C("F").is_not_null()).height,
    )
    wf = walk_forward(p)
    dates = wf["date"].unique().sort()
    mid = dates[len(dates) // 2]
    print("test", dates[0], "->", dates[-1], "split", mid)
    rows = [
        judge(wf, "composite", "V0 v2 composite", mid),
        judge(wf, "F", "F fundamentals score", mid),
        judge(wf, "VF", "V0+F mean of ranks", mid),
        judge(wf, "gbm_p", "GBM price signals only", mid),
        judge(wf, "gbm", "GBM with fundamentals", mid),
        judge(
            wf.with_columns(rnd=pl.Series(np.random.default_rng(1).random(wf.height))),
            "rnd",
            "random",
            mid,
        ),
    ]
    tr = today(p, ids)
    print("today", p["date"].max(), "ranked", sum(r["VF"] is not None for r in tr), "of", len(tr))
    for r in tr[:20]:
        print(
            f"  {r['symbol']:8s} VF {r['VF']:.2f} V {r['qV']:.2f} F {r['qF']:.2f} pe {r['pe'] or 0:5.1f} "
            f"net_g {100 * (r['net_g'] or 0):+5.0f}% opm {100 * (r['opm_chg'] or 0):+5.1f}pt "
            f"liab {100 * (r['liab_ratio'] or 0):3.0f}% age {r['age_days']}d S1={r['s1']}"
        )
    sizes = {}
    for k in (5, 20):
        sizes[k] = [
            judge(wf, c, n, mid, k) for c, n in (("composite", "V0"), ("F", "F"), ("VF", "V0+F"))
        ]
        for r in sizes[k]:
            print(
                f"top {k:2d} {r['name']:5s} H1 ex {100 * r['h1']['ex']:+5.2f}% (t {r['h1']['t']:+.1f})"
                f" | H2 ex {100 * r['h2']['ex']:+5.2f}% (t {r['h2']['t']:+.1f})"
            )
    res = {
        "split": str(mid),
        "first": str(dates[0]),
        "last": str(dates[-1]),
        "rows": rows,
        "sizes": sizes,
    }
    (HERE / f"results_model{uv.suffix()}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    f = lambda r: (  # noqa: E731
        f"ex {100 * r['ex']:+5.2f}% (t {r['t']:+.1f}) indep {100 * r['ex_indep']:+5.2f}% (n={r['n_indep']}, win {100 * r['win_indep']:3.0f}%) "
        f"net {100 * r['net_raw_indep']:+5.1f}% IC {r['ic']:+.3f}"
    )
    for r in rows:
        print(f"{r['name']:26s} H1 {f(r['h1'])}\n{'':26s} H2 {f(r['h2'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
