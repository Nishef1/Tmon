"""Combined multi-signal strategy, walk-forward, on the tradable universe.

Universe per date: top 100 by 20-day median traded value, no buy-queue names. Every H trading days
(non-overlapping) the strategy buys the TOP_K names with the best score and holds H days; each
rebalance pays the full round-trip cost (conservative: no credit for names kept). Benchmark = mean
return of the same 100 names, no cost (buy-and-hold proxy). Weighted scores are fitted with an
expanding window on rows that ended at least H days before the rebalance date (embargo)."""

import math

import numpy as np
import polars as pl

from tmon.backtest.signal_decay import SIGNALS, adjusted_close, build_panel
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import build_features
from tmon.features.store import load_inputs

COST, TOP_K, UNIVERSE = 0.0175, 10, 100
HS = (5, 20, 60)
MIN_TRAIN_DAYS = 250

cfg = get_engine_config()
with session_scope() as s:
    prices, clients, sectors = load_inputs(s)
    rules = RuleBook.from_session(s)
feats = build_features(prices, clients, rules, sectors=sectors)
adj = adjusted_close(prices)
panel = build_panel(feats, adj, cfg, horizons=HS)
mv = feats.select("instrument_id", "date", "median_value_20")
p = panel.join(mv, on=["instrument_id", "date"], how="left").filter(pl.col("median_value_20").is_not_null())
p = p.with_columns(pl.col("median_value_20").rank("ordinal", descending=True).over("date").alias("liq"))
p = p.filter((pl.col("liq") <= UNIVERSE) & (pl.col("queue_state") != "buy_queue"))
names = [f"r_{x}" for x in SIGNALS]
dates = sorted(p["date"].unique().to_list())
print("signals", names, "dates", len(dates), dates[0], dates[-1])


def fit(train: pl.DataFrame, h: int, ridge: float = 50.0) -> np.ndarray:
    f = f"fwd_{h}"
    d = train.filter(pl.col(f).is_finite()).with_columns((pl.col(f) - pl.col(f).mean().over("date")).alias("y"))
    x = d.select(names).to_numpy() - 0.5
    y = d["y"].to_numpy()
    w = np.linalg.solve(x.T @ x + ridge * np.eye(len(names)), x.T @ y)
    return w


def t_of(x: np.ndarray) -> float:
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else float("nan")


for h in HS:
    f = f"fwd_{h}"
    reb = dates[MIN_TRAIN_DAYS::h]
    cands: dict[str, list[tuple[float, float]]] = {k: [] for k in ["composite", *names, "fitted_wf", "fitted_wf_top10pct", "random"]}
    rng = np.random.default_rng(1)
    for i, d in enumerate(reb):
        day = p.filter((pl.col("date") == d) & pl.col(f).is_finite())
        if day.height < 50:
            continue
        bench = float(day[f].mean())
        # embargo: train rows whose forward window ended before d
        cut = dates[max(0, dates.index(d) - h - 1)]
        train = p.filter(pl.col("date") <= cut)
        w = fit(train, h)
        score = {"composite": day["composite"].to_numpy(), "fitted_wf": (day.select(names).to_numpy() - 0.5) @ w}
        for n in names:
            score[n] = day[n].to_numpy()
        rets = day[f].to_numpy()
        for k, sc in score.items():
            idx = np.argsort(-sc)[:TOP_K]
            cands[k].append((float(rets[idx].mean()) - COST, bench))
        idx = rng.choice(len(rets), TOP_K, replace=False)
        cands["random"].append((float(rets[idx].mean()) - COST, bench))
        cands["fitted_wf_top10pct"].append((float(rets[np.argsort(-score["fitted_wf"])[: max(TOP_K, day.height // 10)]].mean()) - COST, bench))
    print(f"\n=== horizon {h}d, rebalances {len(cands['composite'])}, top {TOP_K}, cost {COST:.2%}/round trip ===")
    for k, v in cands.items():
        a = np.array(v)
        ex = a[:, 0] - a[:, 1]
        half = len(ex) // 2
        per_year = 245 / h
        print(f"{k:20s} net/period {a[:,0].mean()*100:6.2f}%  bench {a[:,1].mean()*100:5.2f}%  excess {ex.mean()*100:6.2f}% t={t_of(ex):5.2f}  "
              f"halves {ex[:half].mean()*100:5.2f}/{ex[half:].mean()*100:5.2f}  win {np.mean(ex>0):.2f}  ann net {((1+a[:,0]).prod())**(per_year/len(a))-1:6.1%} ann bench {((1+a[:,1]).prod())**(per_year/len(a))-1:6.1%}")
