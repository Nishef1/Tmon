# ruff: noqa: N806
"""One-at-a-time sensitivity of every tunable parameter of the ranking, measured the same way.

Each experiment changes ONE thing against the production setting (four signals, equal weight,
percent ranks, liquid-or-not universe as the engine defines it) and reports, for the horizons 1, 5,
20, 60 and 120 trading days: the mean daily IC and the top-decile excess return, each with a
t-statistic (effective sample n/h), and the IC in the first and second half of the history. A change
counts only if it helps in both halves.

Groups: S1 signal definitions (window lengths), S2 rank transform, S3 the whole weight simplex,
S4 score smoothing over days, S5 universe by liquidity, S6 sector neutralisation, S7 top fraction,
S8 the portfolio rules (buy fraction, hold buffer, names, review interval, with cost).

``python -m tmon.backtest.parameter_study`` writes ``docs/data/parameter-study.json``. Nothing here
changes the production model.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from tmon.backtest.signal_decay import adjusted_close, forward_returns
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.builder import KEYS, build_features
from tmon.features.store import load_inputs

HS = (1, 5, 20, 60, 120)
MIN_N = 30
G = "instrument_id"


def _prank(col: str, by: list[str] | None = None) -> pl.Expr:
    keys = by or ["date"]
    r = pl.col(col).rank("average").over(keys)
    return (r - 0.5) / pl.col(col).count().over(keys) - 0.5


def build() -> tuple[pl.DataFrame, float]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    fwd = forward_returns(adj, HS).select(*KEYS, "mom_12_1", *[f"fwd_{h}" for h in HS])
    c = pl.col("adj_close")
    lr = (c / c.shift(1)).log().over(G)
    ex: list[pl.Expr] = []
    for w in (10, 20, 40, 60, 120):
        ex.append(lr.rolling_std(w).over(G).alias(f"rvw_{w}"))
    for w in (20, 60, 120, 252):
        ex.append((c / c.rolling_max(w, min_samples=w // 2) - 1.0).over(G).alias(f"dhw_{w}"))
    for sk, lb in ((0, 63), (5, 126), (21, 126), (21, 63), (63, 252)):
        ex.append((c.shift(sk) / c.shift(lb) - 1.0).over(G).alias(f"momw_{sk}_{lb}"))
    derived = adj.sort(KEYS).with_columns(*ex).select(*KEYS, *[e.meta.output_name() for e in ex])
    d = feats.filter(~pl.col("market_halt")).select(
        *KEYS,
        "eligible",
        "queue_state",
        "ind_buy_power",
        "rv_20",
        "dist_high_52w",
        "median_value_20",
    )
    d = d.sort(KEYS).with_columns(
        *[
            pl.col("ind_buy_power").rolling_mean(k, min_samples=k).over(G).alias(f"ibp_{k}")
            for k in (2, 3, 5, 10, 20)
        ],
        pl.col("ind_buy_power").alias("ibp_1"),
    )
    d = d.join(derived, on=list(KEYS), how="left").join(fwd, on=list(KEYS), how="left")
    sec = (
        sectors.select(G, pl.col(sectors.columns[1]).alias("sector")) if sectors.width > 1 else None
    )
    if sec is not None:
        d = d.join(sec.unique(G), on=G, how="left")
    d = d.filter(
        pl.col("eligible") & ~pl.col("queue_state").is_in(cfg.universe.exclude_queue_states)
    ).filter(
        pl.all_horizontal(
            [
                pl.col(x).is_not_null() & pl.col(x).is_finite()
                for x in ("ibp_1", "rv_20", "dist_high_52w", "mom_12_1")
            ]
        )
    )
    cost = CostModel.from_rules(
        rules, cast(date, d["date"].max()), cfg.costs.slippage_fraction
    ).round_trip
    d = d.with_columns(*[_prank(f"fwd_{h}").alias(f"y_{h}") for h in HS])
    return d.sort("date"), float(cost)


def sig_cols(
    ibp: str = "ibp_1",
    rv: str = "rv_20",
    dh: str = "dist_high_52w",
    mom: str = "mom_12_1",
    transform: str = "rank",
    neutral: str | None = None,
) -> list[tuple[str, pl.Expr]]:
    """The four signals as sign-adjusted, date-ranked columns."""
    out = []
    for nm, col, sign in (("a", ibp, 1), ("b", rv, -1), ("c", dh, 1), ("d", mom, 1)):
        by = ["date"] + ([neutral] if neutral else [])
        x = pl.col(col)
        if transform == "rank":
            e = _prank(col, by)
        elif transform == "z":
            e = (x - x.mean().over(by)) / x.std().over(by)
        elif transform == "zw":
            z = (x - x.mean().over(by)) / x.std().over(by)
            e = z.clip(-3, 3)
        else:
            raise ValueError(transform)
        out.append((nm, (e * sign).fill_null(0.0).fill_nan(0.0).alias(nm)))
    return out


def evaluate(df: pl.DataFrame, score: str, q: float = 0.1) -> dict[str, Any]:
    """IC and top-fraction excess per horizon, whole sample and the two halves."""
    d = df.with_columns(_prank(score).alias("_sr"))
    aggs: list[pl.Expr] = [pl.len().alias("n")]
    for h in HS:
        m = pl.col(f"y_{h}").is_not_null() & pl.col(f"fwd_{h}").is_finite()
        aggs.append(pl.corr(pl.col(score).filter(m), pl.col(f"y_{h}").filter(m)).alias(f"ic_{h}"))
        top = pl.col(f"fwd_{h}").filter(m & (pl.col("_sr") > 0.5 - q)).mean()
        aggs.append((top - pl.col(f"fwd_{h}").filter(m).median()).alias(f"ex_{h}"))
    per = d.group_by("date").agg(*aggs).filter(pl.col("n") >= MIN_N).sort("date")
    mid = per["date"][per.height // 2]
    early = (per["date"] < mid).to_numpy()
    out: dict[str, Any] = {"first": str(per["date"][0]), "dates": per.height}
    for h in HS:
        r: dict[str, Any] = {}
        for k in ("ic", "ex"):
            x = per[f"{k}_{h}"].to_numpy().astype(float)
            ok = np.isfinite(x)
            r[k] = _st(x[ok], h)
            r[f"{k}_early"] = float(x[ok & early].mean()) if (ok & early).any() else None
            r[f"{k}_late"] = float(x[ok & ~early].mean()) if (ok & ~early).any() else None
        out[str(h)] = r
    return out


def ic_series(df: pl.DataFrame, score: str) -> pl.DataFrame:
    """Per-date IC of ``score`` against the rank label of every horizon."""
    aggs = [pl.len().alias("n")]
    for h in HS:
        m = pl.col(f"y_{h}").is_not_null()
        aggs.append(pl.corr(pl.col(score).filter(m), pl.col(f"y_{h}").filter(m)).alias(f"ic_{h}"))
    return df.group_by("date").agg(*aggs).filter(pl.col("n") >= MIN_N).sort("date")


def paired(a: pl.DataFrame, b: pl.DataFrame) -> dict[str, Any]:
    """IC difference a - b per date: mean, t (effective n = n/h), early and late halves."""
    j = a.join(b, on="date", suffix="_b")
    mid = j["date"][j.height // 2]
    early = (j["date"] < mid).to_numpy()
    out: dict[str, Any] = {}
    for h in HS:
        d = (j[f"ic_{h}"] - j[f"ic_{h}_b"]).to_numpy().astype(float)
        ok = np.isfinite(d)
        st = _st(d[ok], h)
        out[str(h)] = {
            **st,
            "early": float(d[ok & early].mean()),
            "late": float(d[ok & ~early].mean()),
        }
    return out


def reuniverse(df: pl.DataFrame, keep: pl.Expr) -> pl.DataFrame:
    """Restrict to a sub-universe and re-rank the labels inside it."""
    d = df.filter(keep)
    return d.with_columns(*[_prank(f"fwd_{h}").alias(f"y_{h}") for h in HS])


def _st(v: np.ndarray, h: int) -> dict[str, float | None]:
    n = v.size
    if n < 20:
        return {"mean": None, "t": None}
    sd = float(v.std(ddof=1))
    t = float(v.mean() / (sd / math.sqrt(max(n / h, 1.0)))) if sd > 0 else None
    return {"mean": float(v.mean()), "t": t}


def composite(
    df: pl.DataFrame, cols: list[tuple[str, pl.Expr]], w: list[float] | None = None
) -> pl.DataFrame:
    d = df.with_columns(*[e for _, e in cols])
    ww = w or [0.25] * 4
    return d.with_columns(
        pl.sum_horizontal([pl.col(n) * x for (n, _), x in zip(cols, ww, strict=True)]).alias(
            "score"
        )
    )


def smooth(df: pl.DataFrame, k: int) -> pl.DataFrame:
    if k <= 1:
        return df
    return df.sort(KEYS).with_columns(
        pl.col("score").rolling_mean(k, min_samples=1).over(G).alias("score")
    )


def simplex(step: float = 0.05) -> list[tuple[float, ...]]:
    n = round(1 / step)
    return [
        tuple(c * step for c in comb)
        for comb in itertools.product(range(n + 1), repeat=4)
        if sum(comb) == n
    ]


def weight_grid(df: pl.DataFrame) -> dict[str, Any]:
    """IC of every weight vector on a 0.05 simplex via per-date moment matrices."""
    cols = sig_cols()
    d = df.with_columns(*[e for _, e in cols])
    parts = [p for p in d.partition_by("date", maintain_order=True) if p.height >= MIN_N]
    mid = parts[len(parts) // 2]["date"][0]
    grids = simplex(0.05)
    W = np.array(grids)
    res: dict[str, Any] = {"n_weights": len(grids), "mid": str(mid), "by_horizon": {}}
    for h in HS:
        ics = np.full((len(parts), len(grids)), np.nan)
        before = np.zeros(len(parts), dtype=bool)
        for i, p in enumerate(parts):
            if p.height < MIN_N:
                continue
            before[i] = p["date"][0] < mid
            y = p[f"y_{h}"].to_numpy().astype(float)
            m = np.isfinite(y)
            if m.sum() < MIN_N:
                continue
            X = p.select([n for n, _ in cols]).to_numpy().astype(float)[m]
            yy = y[m] - y[m].mean()
            Xc = X - X.mean(0)
            C = Xc.T @ Xc
            c = Xc.T @ yy
            vy = float(yy @ yy)
            num = W @ c
            den = np.sqrt(np.einsum("ki,ij,kj->k", W, C, W) * vy)
            with np.errstate(invalid="ignore", divide="ignore"):
                ics[i] = num / den
        ok = np.isfinite(ics).all(1)
        ics, bf = ics[ok], before[ok]
        mean_all, mean_e, mean_l = ics.mean(0), ics[bf].mean(0), ics[~bf].mean(0)
        eq = (
            next(i for i, g in enumerate(grids) if all(abs(x - 0.25) < 1e-9 for x in g))
            if any(all(abs(x - 0.25) < 1e-9 for x in g) for g in grids)
            else None
        )
        ord_all = np.argsort(-mean_all)[:5]
        # choose in one half, test in the other
        pick_e = int(np.argmax(mean_e))
        pick_l = int(np.argmax(mean_l))
        res["by_horizon"][str(h)] = {
            "best5": [
                {"w": [round(x, 2) for x in grids[i]], "ic": float(mean_all[i])} for i in ord_all
            ],
            "equal_ic": None if eq is None else float(mean_all[eq]),
            "equal_rank": None if eq is None else int((mean_all > mean_all[eq]).sum()) + 1,
            "chosen_early": {
                "w": [round(x, 2) for x in grids[pick_e]],
                "ic_early": float(mean_e[pick_e]),
                "ic_late": float(mean_l[pick_e]),
                "equal_late": None if eq is None else float(mean_l[eq]),
            },
            "chosen_late": {
                "w": [round(x, 2) for x in grids[pick_l]],
                "ic_late": float(mean_l[pick_l]),
                "ic_early": float(mean_e[pick_l]),
                "equal_early": None if eq is None else float(mean_e[eq]),
            },
        }
    return res


def simulate(
    d: pl.DataFrame, buy: float, hold: float, n_names: int, review: int, cost: float
) -> dict[str, Any]:
    """Equal-weight book: buy from the top ``buy`` fraction, keep a name while it stays inside the
    top ``hold`` fraction, review every ``review`` dates, pay half the round-trip per side.

    Uses the forward return of the horizon equal to the review interval (entry the next day)."""
    h = review
    dates = d["date"].unique().sort().to_list()
    held: set[int] = set()
    nets: list[float] = []
    mkts: list[float] = []
    turns: list[float] = []
    sel = d.select("date", G, "score", f"fwd_{h}").drop_nulls().partition_by("date", as_dict=True)
    for i in range(0, len(dates), review):
        p = sel.get((dates[i],))
        if p is None or p.height < MIN_N:
            continue
        ids = p[G].to_numpy()
        sc = p["score"].to_numpy()
        rk = 1.0 - (sc.argsort().argsort() + 0.5) / len(sc)  # 0 = best
        order = {int(x): float(r) for x, r in zip(ids, rk, strict=True)}
        keep = {x for x in held if order.get(x, 1.0) <= hold}
        cands = sorted(
            (x for x, r in order.items() if r <= buy and x not in keep), key=lambda x: order[x]
        )
        new = keep | set(cands[: max(n_names - len(keep), 0)])
        buys, sells = len(new - held), len(held - new)
        f = dict(zip(ids.tolist(), p[f"fwd_{h}"].to_numpy().tolist(), strict=True))
        r = [f[x] for x in new if x in f]
        if not r:
            continue
        nets.append(float(np.mean(r)) - cost / 2 * (buys + sells) / max(len(new), 1))
        mkts.append(float(np.median(p[f"fwd_{h}"].to_numpy())))
        turns.append((buys + sells) / (2 * max(len(new), 1)))
        held = new
    a = np.array(nets) - np.array(mkts)
    if a.size < 20:
        return {"n": int(a.size)}
    per_year = 250 / review
    return {
        "n": int(a.size),
        "net_excess_per_period": float(a.mean()),
        "net_excess_annual": float(a.mean() * per_year),
        "t": float(a.mean() / (a.std(ddof=1) / math.sqrt(a.size))) if a.std() > 0 else None,
        "pos": float((a > 0).mean()),
        "turnover": float(np.mean(turns)),
        "early": float(a[: a.size // 2].mean() * per_year),
        "late": float(a[a.size // 2 :].mean() * per_year),
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-parameter-study")
    ap.add_argument("--out", default=str(Path("docs/data/parameter-study.json")))
    args = ap.parse_args()
    df, cost = build()
    print("panel", df.shape, "round trip", cost, flush=True)
    res: dict[str, Any] = {
        "cost": cost,
        "horizons": list(HS),
        "first": str(df["date"].min()),
        "last": str(df["date"].max()),
    }
    exps: dict[str, dict[str, Any]] = {}

    def run(name: str, group: str, d: pl.DataFrame, **kw: Any) -> None:
        exps[name] = {"group": group, **evaluate(d, "score", **kw)}
        print(name, flush=True)

    base_cols = sig_cols()
    run("base", "S0", composite(df, base_cols))
    # S1 signal definitions
    for k in (2, 3, 5, 10, 20):
        run(f"ibp_smooth_{k}", "S1", composite(df, sig_cols(ibp=f"ibp_{k}")))
    for w in (10, 40, 60, 120):
        run(f"rv_window_{w}", "S1", composite(df, sig_cols(rv=f"rvw_{w}")))
    for w in (20, 60, 120):
        run(f"dist_high_{w}", "S1", composite(df, sig_cols(dh=f"dhw_{w}")))
    for sk, lb in ((0, 63), (5, 126), (21, 126), (21, 63), (63, 252)):
        run(f"momw_{sk}_{lb}", "S1", composite(df, sig_cols(mom=f"momw_{sk}_{lb}")))
    # S2 transforms
    for tr in ("z", "zw"):
        run(f"transform_{tr}", "S2", composite(df, sig_cols(transform=tr)))
    # S6 sector neutral
    if "sector" in df.columns:
        run("sector_neutral", "S6", composite(df, sig_cols(neutral="sector")))
    # S4 smoothing
    base = composite(df, base_cols)
    for k in (3, 5, 10, 20):
        run(f"score_smooth_{k}", "S4", smooth(base, k))
    # S5 universe by liquidity rank
    liq = df.with_columns(_prank("median_value_20").alias("_liq"))
    for frac in (0.1, 0.25, 0.5, 0.75):
        d2 = composite(reuniverse(liq, pl.col("_liq") > 0.5 - frac), base_cols)
        run(f"liquid_top_{int(frac * 100)}pct", "S5", d2)
    # S7 top fraction
    for q in (0.02, 0.05, 0.2, 0.3, 0.5):
        run(f"top_fraction_{q}", "S7", base, q=q)
    res["experiments"] = exps
    res["S3_weight_grid"] = weight_grid(df)
    print("grid done", flush=True)
    # S9 joint grid of the three window definitions (interactions between them)
    joint: dict[str, Any] = {}
    for rv, dh, mom in itertools.product(
        ("rv_20", "rvw_10", "rvw_40", "rvw_60", "rvw_120"),
        ("dist_high_52w", "dhw_20", "dhw_60", "dhw_120"),
        ("mom_12_1", "momw_0_63", "momw_21_63", "momw_21_126", "momw_5_126"),
    ):
        r = evaluate(composite(df, sig_cols(rv=rv, dh=dh, mom=mom)), "score")
        joint[f"{rv}|{dh}|{mom}"] = {
            h: {
                k: r[h]["ic"][k] if k in ("mean", "t") else r[h][f"ic_{k}"]
                for k in ("mean", "t", "early", "late")
            }
            for h in map(str, HS)
        }
    res["S9_joint_definitions"] = joint
    # S10 candidates against the base, paired per date; and the pick-early / test-late check
    base_ic = ic_series(composite(df, base_cols), "score")
    cands = {
        "long_horizon: rv120 + mom21_63": {"rv": "rvw_120", "mom": "momw_21_63"},
        "long_horizon: rv120 only": {"rv": "rvw_120"},
        "long_horizon: mom21_63 only": {"mom": "momw_21_63"},
        "short_horizon: rv10": {"rv": "rvw_10"},
        "short_horizon: rv10 + mom21_63": {"rv": "rvw_10", "mom": "momw_21_63"},
    }
    res["S10_paired_candidates"] = {
        name: paired(ic_series(composite(df, sig_cols(**kw)), "score"), base_ic)
        for name, kw in cands.items()
    }
    pick: dict[str, Any] = {}
    for h in map(str, HS):
        best = max(joint.items(), key=lambda kv: kv[1][h]["early"])
        pick[h] = {
            "choice": best[0],
            "early": best[1][h]["early"],
            "late": best[1][h]["late"],
            "base_late": joint["rv_20|dist_high_52w|mom_12_1"][h]["late"],
        }
    res["S10_pick_early_test_late"] = pick
    print("joint done", flush=True)
    # S8 portfolio rules, on the whole universe and on the 100 most liquid names per date
    port: dict[str, Any] = {}
    top100 = df.with_columns(
        pl.col("median_value_20").rank("ordinal", descending=True).over("date").alias("_lr")
    )
    for uni, frame in (("all", df), ("liquid100", top100.filter(pl.col("_lr") <= 100))):
        scored = smooth(composite(frame, base_cols), 1)
        for review in (5, 20):
            for buy, hold, n in itertools.product(
                (0.02, 0.05, 0.1, 0.2), (0.1, 0.3, 0.5), (10, 20, 40)
            ):
                if hold < buy:
                    continue
                port[f"{uni}_R{review}_buy{buy}_hold{hold}_n{n}"] = simulate(
                    scored, buy, hold, n, review, cost
                )
        print("portfolio", uni, flush=True)
    res["S8_portfolio"] = port
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
