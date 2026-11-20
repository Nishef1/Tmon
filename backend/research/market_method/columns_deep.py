"""Deeper tests of the derived columns (features/extra.py, features/relative.py).

Report: docs/reports/columns-deep-2026-11.md. Four questions, each judged out of sample on both
halves of time, with the 1.75% round trip, and against a chance level that keeps the way days and
months cluster:

  market   do market-wide aggregates of the columns forecast the index 20 and 60 days ahead
           (direction, and a fall of more than 10%) better than "the trend continues" and better
           than the plain base rate?
  khak     at the «طلا تو خاک» ladder steps: does any column, or a small model, tell a real floor
           from a falling knife; and are the fixed 0.75/1/1.15/1.3 steps better than other ladders?
  rank     does a learned combination of the columns (ridge, IC-weighted, split by market trend)
           improve the top, middle and bottom deciles of the v2 four-signal score, after turnover?
  power    the book and fundamental columns, only where they exist (book from Esfand 1403), and how
           large an effect that sample could detect at all.

Universe: point in time (universe.pit_members: the day's 100 most traded by 20-day median value,
known at the previous close), not today's basket, so no survivorship. Main window: the last three
years (from 2023-11-20). Check: the whole history the panel covers.

Run from backend/ with the live env:
  python research/market_method/columns_deep.py build    # ~10 min, writes data/columns-deep/*
  python research/market_method/columns_deep.py market|khak|rank|power|all
Output: docs/data/columns-deep-<part>.json
"""

# ruff: noqa: N803, N806, B023
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import universe as uv

C = pl.col
G = "instrument_id"
ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "columns-deep"
OUT = ROOT / "docs" / "data"
DB = "file:" + str(ROOT / "data" / "tmon-live.sqlite3") + "?mode=ro"
COST = 0.0175
MAIN_FROM = "2023-11-20"  # the last three years
HISTORY_FROM = "2012-01-01"
STEP_GRID = (0.5, 0.75, 0.9, 1.0, 1.1, 1.15, 1.25, 1.3, 1.5, 1.75, 2.0)
LADDERS = {
    "current_0.75_1_1.15_1.3": (0.75, 1.0, 1.15, 1.3),
    "shallow_0.5_0.75_1_1.25": (0.5, 0.75, 1.0, 1.25),
    "deep_1_1.25_1.5_1.75": (1.0, 1.25, 1.5, 1.75),
    "wide_0.75_1_1.5_2": (0.75, 1.0, 1.5, 2.0),
    "single_1.0": (1.0,),
    "single_1.3": (1.3,),
    "single_0.75": (0.75,),
}
RNG = np.random.default_rng(11)
BOOT = 2000
LAMBDA = float(__import__("os").environ.get("DEEP_LAMBDA", "5"))


# ----------------------------------------------------------------------------- shared statistics


def month_key(dates: np.ndarray) -> np.ndarray:
    d = dates.astype("datetime64[M]")
    return d.astype(np.int64)


def block_boot(values: np.ndarray, blocks: np.ndarray, n: int = BOOT) -> dict[str, float | None]:
    """Mean of ``values`` with a block bootstrap over ``blocks`` (month or quarter keys): resample
    whole blocks, so days of one month move together and overlap does not fake precision."""
    ok = np.isfinite(values)
    v, b = values[ok], blocks[ok]
    if v.size < 20:
        return {"mean": None, "lo": None, "hi": None, "p_le_0": None, "n": int(v.size), "blocks": 0}
    keys, inv = np.unique(b, return_inverse=True)
    sums = np.bincount(inv, weights=v)
    cnts = np.bincount(inv).astype(float)
    k = keys.size
    draws = RNG.integers(0, k, size=(n, k))
    means = sums[draws].sum(1) / cnts[draws].sum(1)
    return {
        "mean": float(v.mean()),
        "lo": float(np.percentile(means, 2.5)),
        "hi": float(np.percentile(means, 97.5)),
        "p_le_0": float((means <= 0).mean()),
        "n": int(v.size),
        "blocks": int(k),
    }


def halves(dates: np.ndarray) -> np.datetime64:
    s = np.sort(dates)
    return s[s.size // 2]


def rank01(x: np.ndarray) -> np.ndarray:
    out = np.full(x.shape, np.nan)
    ok = np.isfinite(x)
    if ok.sum() > 1:
        out[ok] = (pl.Series(x[ok]).rank("average").to_numpy() - 0.5) / ok.sum()
    return out


def auc(score: np.ndarray, y: np.ndarray) -> float | None:
    ok = np.isfinite(score) & np.isfinite(y)
    s, t = score[ok], y[ok]
    n1 = int(t.sum())
    n0 = t.size - n1
    if n1 < 10 or n0 < 10:
        return None
    r = pl.Series(s).rank("average").to_numpy()
    return float((r[t == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def shuffle_within(y: np.ndarray, blocks: np.ndarray) -> np.ndarray:
    """Permute ``y`` inside each block (month): what chance gives when events of one month share
    their market move."""
    out = y.copy()
    for k in np.unique(blocks):
        idx = np.flatnonzero(blocks == k)
        out[idx] = y[RNG.permutation(idx)]
    return out


# ----------------------------------------------------------------------------- build


def build() -> None:
    """Every input, point in time, saved to data/columns-deep/ so the parts run fast."""
    from tmon.backtest.extra_columns_study import load_columns
    from tmon.backtest.signal_decay import SIGNALS, build_panel
    from tmon.core.engine_config import get_engine_config
    from tmon.features.adjustment import apply_adjustments
    from tmon.features.builder import build_features
    from tmon.features.extra import EXTRA_COLUMNS
    from tmon.features.relative import REL_COLUMNS, build_relative

    CACHE.mkdir(parents=True, exist_ok=True)
    w = load_columns()
    prices = w["prices"]
    ids = uv.stock_ids(DB)
    pit = uv.pit_members(prices, ids).with_columns(pit=pl.lit(True))
    adj = (
        apply_adjustments(prices.sort("instrument_id", "date"))
        .filter(C(G).is_in(list(ids)) & (C("close") > 0))
        .select(G, C("date").cast(pl.Date), "adj_close", "close", "value")
        .sort(G, "date")
    )
    adj.write_parquet(CACHE / "adj.parquet")
    w["ix"].with_columns(C("date").cast(pl.Date)).write_parquet(CACHE / "index.parquet")
    pit.write_parquet(CACHE / "pit.parquet")

    rel = build_relative(
        prices, w["clients"], w["extra"], sectors=w["sectors"], index_close=w["ix"]
    )
    cols = w["extra"].join(rel, on=[G, "date"], how="left").with_columns(C("date").cast(pl.Date))
    cols = cols.filter(C(G).is_in(list(ids)))
    # trend flags for market breadth, from the adjusted close of every stock
    c = C("adj_close")
    flags = adj.with_columns(
        above50=(c > c.rolling_mean(50, min_samples=40)).over(G),
        above200=(c > c.rolling_mean(200, min_samples=150)).over(G),
        ret20=(c / c.shift(20) - 1).over(G),
        ret60=(c / c.shift(60) - 1).over(G),
    ).select(G, "date", "above50", "above200", "ret20", "ret60")
    sectors = w["sectors"].select(G, "sector_code")
    keep = [*EXTRA_COLUMNS, *REL_COLUMNS]
    panel = (
        pit.join(cols.select(G, "date", *keep), on=["date", G], how="left")
        .join(flags, on=["date", G], how="left")
        .join(sectors, on=G, how="left")
    )

    cfg = get_engine_config()
    from tmon.core.db import session_scope
    from tmon.domain.rules import RuleBook
    from tmon.features.store import load_inputs

    with session_scope() as s:
        pr2, clients, sec2 = load_inputs(s)
        rules = RuleBook.from_session(s)
    feats = build_features(pr2, clients, rules, sectors=sec2)
    from tmon.backtest.signal_decay import adjusted_close

    v2 = build_panel(feats, adjusted_close(pr2), cfg, horizons=(20, 60)).with_columns(
        C("date").cast(pl.Date)
    )
    v2 = v2.select(G, "date", *[f"r_{s}" for s in SIGNALS], "composite", "fwd_20", "fwd_60")
    panel = panel.join(v2, on=["date", G], how="left").with_columns(
        v2_ok=C("composite").is_not_null()
    )
    panel.sort("date", G).write_parquet(CACHE / "panel.parquet")

    # khak events need the columns on any stock's step day, not only pit members
    ev = khak_events(adj)
    ev.write_parquet(CACHE / "events_raw.parquet")
    evc = (
        ev.select(G, "date")
        .unique()
        .join(cols.select(G, "date", *keep), on=[G, "date"], how="left")
    )
    evc.write_parquet(CACHE / "event_columns.parquet")
    print("panel", panel.shape, "events", ev.shape)


# ----------------------------------------------------------------------------- khak events


def _episodes(close: np.ndarray, min_depth: float = -0.20) -> list[tuple[int, int, float]]:
    out = []
    peak, start, low, low_i = close[0], 0, close[0], 0
    for i in range(1, len(close)):
        if close[i] > peak:
            d = low / peak - 1
            if i > start + 1 and d <= min_depth:
                out.append((low_i, i, d))
            peak, start, low, low_i = close[i], i, close[i], i
        elif close[i] < low:
            low, low_i = close[i], i
    return out


def khak_events(adj: pl.DataFrame) -> pl.DataFrame:
    """Every day a stock first crosses m x its usual depth (m in STEP_GRID) inside a drawdown, as in
    drawdown_floor.scan (usual = median of its completed past episodes, at least two). Labels: entry
    at the next close; ret60/ret250 net of cost; MAE over 60 days; days until the price is back
    above entry plus cost; whether the episode ended in a new high."""
    rows: list[dict[str, Any]] = []
    for (iid,), g in adj.group_by(G, maintain_order=True):
        cl = g["adj_close"].to_numpy().astype(float)
        dts = g["date"].to_numpy().astype("datetime64[D]")
        n = cl.size
        if n < 300:
            continue
        eps = _episodes(cl)
        done: list[float] = []
        k = 0
        peak, fired, ep_id = cl[0], set(), 0
        for i in range(1, n):
            while k < len(eps) and eps[k][1] <= i:
                done.append(eps[k][2])
                k += 1
            if cl[i] > peak:
                peak, fired = cl[i], set()
                ep_id += 1
                continue
            if len(done) < 2 or i + 1 >= n:
                continue
            usual = float(np.median(done))
            dd = cl[i] / peak - 1
            for m in STEP_GRID:
                if m in fired or dd > m * usual:
                    continue
                fired.add(m)
                e = cl[i + 1]
                fut = cl[i + 2 : i + 252]
                r60 = cl[i + 61] / e - 1 - COST if i + 61 < n else None
                r250 = cl[i + 251] / e - 1 - COST if i + 251 < n else None
                mae = float(fut[:60].min() / e - 1) if fut.size >= 60 else None
                back = np.flatnonzero(fut >= e * (1 + COST))
                rec = int(back[0]) + 1 if back.size else None
                newhigh = np.flatnonzero(cl[i + 1 :] > peak)
                rows.append(
                    {
                        G: iid, "date": dts[i].astype(object), "m": m, "usual": usual, "dd": dd,
                        "ep": f"{iid}-{ep_id}", "ret60": r60, "ret250": r250, "mae60": mae,
                        "rec_days": rec, "rec_cens": int(fut.size),
                        "days_to_high": int(newhigh[0]) + 1 if newhigh.size else None,
                    }
                )  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(C("date").cast(pl.Date))


# ----------------------------------------------------------------------------- part: market


def market() -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    p = pl.read_parquet(CACHE / "panel.parquet")
    ix = pl.read_parquet(CACHE / "index.parquet").sort("date")
    agg = (
        p.group_by("date")
        .agg(
            breadth50=C("above50").mean(),
            breadth200=C("above200").mean(),
            real_pos=(C("real_net_pct") > 0).mean(),
            med_vol=C("vol_vs_30").median(),
            disp20=C("ret20").std(),
            book=C("net_order_pct").mean(),
            book_n=C("net_order_pct").count(),
            n=pl.len(),
        )
        .sort("date")
    )
    ind = (
        p.group_by("date", "sector_code")
        .agg(C("ret60").median().alias("r"))
        .group_by("date")
        .agg(ind_disp=C("r").std())
    )
    x = ix.with_columns(
        ix_trend=C("close") / C("close").rolling_mean(100, min_samples=60) - 1,
        ix_ma200=C("close") / C("close").rolling_mean(200, min_samples=150) - 1,
        ix_slope=C("close").rolling_mean(20, min_samples=15)
        / C("close").shift(20).rolling_mean(20, min_samples=15)
        - 1,
        ix_r20=C("close") / C("close").shift(20) - 1,
        ix_r60=C("close") / C("close").shift(60) - 1,
    )
    cl = x["close"].to_numpy().astype(float)
    n = cl.size
    for h in (20, 60):
        fwd = np.full(n, np.nan)
        fall = np.full(n, np.nan)
        for i in range(n - 1 - h):
            e = cl[i + 1]
            fwd[i] = cl[i + 1 + h] / e - 1
            fall[i] = float(cl[i + 2 : i + 2 + h].min() / e - 1 <= -0.10)
        x = x.with_columns(pl.Series(f"f{h}", fwd), pl.Series(f"fall{h}", fall))
    x = x.join(agg, on="date", how="left").join(ind, on="date", how="left")
    x = x.with_columns(
        real_pos5=C("real_pos").rolling_mean(5, min_samples=3),
        breadth50_chg=C("breadth50") - C("breadth50").shift(20),
    ).filter(C("n") >= 50)
    feats = ["breadth50", "breadth200", "breadth50_chg", "real_pos5", "med_vol", "disp20",
             "ind_disp", "ix_trend", "ix_ma200", "ix_slope", "ix_r20", "ix_r60"]  # fmt: skip
    dates = x["date"].to_numpy().astype("datetime64[D]")
    X = x.select(feats).to_numpy().astype(float)
    out: dict[str, Any] = {"features": feats, "first_date": str(dates[0]), "results": {}}

    def fit_pred(cols: list[int], ytr: np.ndarray, Xtr: np.ndarray, Xte: np.ndarray) -> np.ndarray:
        mu, sd = np.nanmean(Xtr[:, cols], 0), np.nanstd(Xtr[:, cols], 0) + 1e-12
        a = np.nan_to_num((Xtr[:, cols] - mu) / sd)
        b = np.nan_to_num((Xte[:, cols] - mu) / sd)
        if len(np.unique(ytr)) < 2:
            return np.full(len(Xte), float(ytr.mean()))
        m = LogisticRegression(C=0.3, max_iter=500).fit(a, ytr)
        return m.predict_proba(b)[:, 1]

    for h in (20, 60):
        for target in ("up", "fall"):
            raw = x[f"f{h}"].to_numpy() if target == "up" else x[f"fall{h}"].to_numpy()
            y = (raw > 0).astype(float) if target == "up" else raw.copy()
            y[~np.isfinite(raw)] = np.nan
            for window, start in (("main", MAIN_FROM), ("history", "2016-01-01")):
                s0 = int(np.searchsorted(dates, np.datetime64(start)))
                preds = {k: np.full(len(y), np.nan) for k in ("model", "trend", "base")}
                for t in range(s0, len(y), 21):
                    j = t - h - 1  # last training row whose label is known at t
                    tr = np.arange(0, j + 1)
                    tr = tr[np.isfinite(y[tr]) & np.all(np.isfinite(X[tr][:, [7, 10]]), 1)]
                    if tr.size < 250:
                        continue
                    te = np.arange(t, min(t + 21, len(y)))
                    ytr = y[tr]
                    preds["model"][te] = fit_pred(list(range(len(feats))), ytr, X[tr], X[te])
                    preds["trend"][te] = fit_pred([feats.index(f"ix_r{h}")], ytr, X[tr], X[te])
                    preds["base"][te] = float(ytr.mean())
                ok = np.isfinite(y) & np.isfinite(preds["model"]) & (np.arange(len(y)) >= s0)
                if ok.sum() < 40:
                    continue
                dd, yy = dates[ok], y[ok]
                cut = halves(dd)
                blk = month_key(dd) // (3 if h == 60 else 1)
                res: dict[str, Any] = {"n_days": int(ok.sum()), "split": str(cut),
                                       "base_rate": float(yy.mean())}  # fmt: skip
                for name, pr in preds.items():
                    pp = pr[ok]
                    brier = (pp - yy) ** 2
                    hit = ((pp > 0.5) == (yy > 0.5)).astype(float)
                    res[name] = {
                        "brier": float(brier.mean()),
                        "hit": float(hit.mean()),
                        "auc": auc(pp, yy),
                        "brier_1": float(brier[dd < cut].mean()),
                        "brier_2": float(brier[dd >= cut].mean()),
                        "auc_1": auc(pp[dd < cut], yy[dd < cut]),
                        "auc_2": auc(pp[dd >= cut], yy[dd >= cut]),
                    }
                bm = (preds["model"][ok] - yy) ** 2
                for ref in ("trend", "base"):
                    gain = (preds[ref][ok] - yy) ** 2 - bm  # > 0: the model is better
                    res[f"gain_vs_{ref}"] = {
                        "all": block_boot(gain, blk),
                        "first": block_boot(gain[dd < cut], blk[dd < cut]),
                        "second": block_boot(gain[dd >= cut], blk[dd >= cut]),
                    }
                # independent windows: how many non-overlapping h-day periods the test has
                res["independent_periods"] = int(ok.sum() // h)
                out["results"][f"{target}{h}_{window}"] = res
    # the book aggregate alone, where it exists (from Esfand 1403)
    bk = x.filter(C("book_n") >= 30)
    if bk.height > 60:
        b = bk["book"].to_numpy()
        f20 = bk["f20"].to_numpy()
        ok = np.isfinite(b) & np.isfinite(f20)
        out["book_aggregate"] = {
            "days": int(ok.sum()),
            "first": str(bk["date"][0]),
            "spearman_f20": float(np.corrcoef(rank01(b[ok]), rank01(f20[ok]))[0, 1]),
            "independent_periods": int(ok.sum() // 20),
        }
    # regime: how much of the main window was a falling market
    m = x.filter(C("date") >= pl.lit(MAIN_FROM).str.to_date())
    out["regime_main"] = {
        "days": m.height,
        "share_ix_above_ma100": float((m["ix_trend"] > 0).mean()),
        "ix_return": float(m["close"][-1] / m["close"][0] - 1),
    }
    return out


# ----------------------------------------------------------------------------- part: khak


def _khak_frame(sound_only: bool = False) -> pl.DataFrame:
    ev = pl.read_parquet(CACHE / "events_raw.parquet")
    pit = pl.read_parquet(CACHE / "pit.parquet")
    adj = pl.read_parquet(CACHE / "adj.parquet")
    # benchmark: equal-weight mean of pit members' next-close-to-h return on the same day
    c = C("adj_close")
    bench = (
        adj.with_columns(
            b60=(c.shift(-61) / c.shift(-1) - 1).over(G),
            b250=(c.shift(-251) / c.shift(-1) - 1).over(G),
        )
        .join(pit, on=["date", G], how="semi")
        .group_by("date")
        .agg(C("b60").mean(), C("b250").mean())
    )
    ev = ev.join(pit, on=["date", G], how="semi").join(bench, on="date", how="left")
    ev = ev.with_columns(x60=C("ret60") - C("b60"), x250=C("ret250") - C("b250"))
    cols = pl.read_parquet(CACHE / "event_columns.parquet")
    ev = ev.join(cols, on=[G, "date"], how="left").with_columns(depth_vs_usual=C("dd") / C("usual"))
    sound = (C("net_margin") > 0) & (C("debt_to_assets") < 0.7)
    ev = ev.with_columns(sound=sound)
    return ev.filter(C("sound")) if sound_only else ev


def _col_list() -> list[str]:
    from tmon.features.extra import EXTRA_COLUMNS
    from tmon.features.relative import REL_COLUMNS

    return [*EXTRA_COLUMNS, *REL_COLUMNS, "depth_vs_usual"]


def _agree_test(
    e: pl.DataFrame, cols: list[str], y: str, perms: int = 200, min_n: int = 150
) -> dict[str, Any]:
    """Columns whose Spearman IC with ``y`` has the same sign and |IC| >= 0.05 in both halves;
    the chance count shuffles outcomes inside each month."""
    e = e.filter(C(y).is_not_null()).sort("date")
    d = e["date"].to_numpy().astype("datetime64[D]")
    cut = halves(d)
    blk = month_key(d)
    yv = e[y].to_numpy().astype(float)
    m1, m2 = d < cut, d >= cut
    xs = {c: rank01(e[c].to_numpy().astype(float)) for c in cols}

    def ic(xr: np.ndarray, yr: np.ndarray) -> float | None:
        ok = np.isfinite(xr) & np.isfinite(yr)
        if ok.sum() < min_n or np.nanstd(xr[ok]) == 0:
            return None
        return float(np.corrcoef(rank01(xr[ok]), rank01(yr[ok]))[0, 1])

    def count(yy: np.ndarray) -> tuple[int, dict[str, Any]]:
        k, tab = 0, {}
        for c in cols:
            a, b = ic(xs[c][m1], yy[m1]), ic(xs[c][m2], yy[m2])
            ok = a is not None and b is not None and a * b > 0 and min(abs(a), abs(b)) >= 0.05
            tab[c] = {"ic1": a, "ic2": b, "agree": ok}
            k += ok
        return k, tab

    k, tab = count(yv)
    null = [count(shuffle_within(yv, blk))[0] for _ in range(perms)]
    return {
        "events": int(e.height), "split": str(cut), "agree": k, "min_n_per_half": min_n,
        "columns_judged": sum(
            1 for v in tab.values() if v["ic1"] is not None and v["ic2"] is not None
        ),
        "chance_mean": float(np.mean(null)), "chance_p95": float(np.percentile(null, 95)),
        "p_value": float((np.array(null) >= k).mean()),
        "agreeing": {c: v for c, v in tab.items() if v["agree"]},
    }  # fmt: skip


def _model_test(e: pl.DataFrame, cols: list[str], start: str) -> dict[str, Any]:
    """Logistic and a depth-3 tree on the columns, trained on events before each quarter and tested
    on that quarter (label: x60 > 0). AUC per half against a within-month shuffle, and the mean
    x60 of the model's top third against all events."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier

    e = e.filter(C("x60").is_not_null()).sort("date")
    d = e["date"].to_numpy().astype("datetime64[D]")
    X = e.select(cols).to_numpy().astype(float)
    y = (e["x60"].to_numpy() > 0).astype(float)
    x60 = e["x60"].to_numpy().astype(float)
    q = d.astype("datetime64[M]").astype(np.int64) // 3
    preds = {"logit": np.full(len(y), np.nan), "tree": np.full(len(y), np.nan)}
    s0 = np.datetime64(start)
    for qq in np.unique(q[d >= s0]):
        te = np.flatnonzero(q == qq)
        # a 60-day label must have ended before the test quarter starts
        tr = np.flatnonzero(d < d[te[0]] - np.timedelta64(90, "D"))
        if tr.size < 500:
            continue
        med = np.nanmedian(X[tr], 0)
        a = np.where(np.isfinite(X[tr]), X[tr], med)
        b = np.where(np.isfinite(X[te]), X[te], med)
        mu, sd = a.mean(0), a.std(0) + 1e-12
        a, b = np.nan_to_num((a - mu) / sd), np.nan_to_num((b - mu) / sd)
        preds["logit"][te] = (
            LogisticRegression(C=0.05, max_iter=1000).fit(a, y[tr]).predict_proba(b)[:, 1]
        )
        tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=200, random_state=0)
        preds["tree"][te] = tree.fit(a, y[tr]).predict_proba(b)[:, 1]
    res: dict[str, Any] = {}
    for name, pr in preds.items():
        ok = np.isfinite(pr)
        if ok.sum() < 200:
            continue
        dd, pp, yy, xx = d[ok], pr[ok], y[ok], x60[ok]
        cut = halves(dd)
        blk = month_key(dd)
        r: dict[str, Any] = {"n": int(ok.sum()), "split": str(cut)}
        for half, m in (("first", dd < cut), ("second", dd >= cut)):
            a_obs = auc(pp[m], yy[m])
            null = [auc(pp[m], shuffle_within(yy[m], blk[m])) for _ in range(200)]
            null_v = np.array([v for v in null if v is not None])
            thr = np.quantile(pp[m], 2 / 3)
            top = m & (pp >= thr)
            r[half] = {
                "auc": a_obs,
                "auc_chance_p95": float(np.percentile(null_v, 95)) if null_v.size else None,
                "p_value": float((null_v >= (a_obs or 0)).mean()) if null_v.size else None,
                "x60_all": float(xx[m].mean()),
                "x60_top_third": float(xx[top].mean()),
                "top_minus_all": block_boot(xx[top] - xx[m].mean(), blk[top]),
            }
        res[name] = r
    return res


def _ladder_test(e: pl.DataFrame) -> dict[str, Any]:
    """Each ladder buys one equal unit at each of its steps an episode reaches, holds every unit
    250 days. Per episode: mean unit x250 (net of cost, minus the pit universe). Per half and with
    a block bootstrap over the month of the first buy."""
    out: dict[str, Any] = {}
    base = e.filter(C("x250").is_not_null())
    for name, steps in LADDERS.items():
        u = base.filter(C("m").is_in(list(steps)))
        ep = (
            u.group_by("ep")
            .agg(
                first=C("date").min(),
                units=pl.len(),
                x250=C("x250").mean(),
                x60=C("x60").mean(),
                mae=C("mae60").min(),
            )
            .sort("first")
        )
        if ep.height < 50:
            continue
        d = ep["first"].to_numpy().astype("datetime64[D]")
        cut = halves(d)
        blk = month_key(d)
        xv = ep["x250"].to_numpy().astype(float)
        out[name] = {
            "episodes": ep.height, "mean_units": float(ep["units"].mean()), "split": str(cut),
            "first": block_boot(xv[d < cut], blk[d < cut]),
            "second": block_boot(xv[d >= cut], blk[d >= cut]),
            "worst_mae_median": float(ep["mae"].median()),
        }  # fmt: skip
    return out


def _step_table(e: pl.DataFrame) -> dict[str, Any]:
    """Per depth multiple: how events turned out (x60, MAE, recovery), per half."""
    out: dict[str, Any] = {}
    e = e.filter(C("x60").is_not_null())
    d = e["date"].to_numpy().astype("datetime64[D]")
    cut = halves(d)
    for m in STEP_GRID:
        s = e.filter(C("m") == m)
        if s.height < 30:
            continue
        sd = s["date"].to_numpy().astype("datetime64[D]")
        row: dict[str, Any] = {"n": s.height}
        for half, msk in (("first", sd < cut), ("second", sd >= cut)):
            ss = s.filter(pl.Series(msk))
            rec = ss["rec_days"].to_numpy().astype(float)
            row[half] = {
                "n": ss.height,
                "x60": block_boot(ss["x60"].to_numpy().astype(float), month_key(sd[msk])),
                "mae60_median": float(ss["mae60"].median()) if ss.height else None,
                "recovered_60d": (
                    float(np.mean(np.isfinite(rec) & (rec <= 60))) if rec.size else None
                ),
                "new_high_250d": float(
                    (ss["days_to_high"].fill_null(10**6) <= 250).mean()
                ) if ss.height else None,
            }  # fmt: skip
        out[str(m)] = row
    return out


def khak() -> dict[str, Any]:
    cols = _col_list()
    out: dict[str, Any] = {}
    for label, sound in (("all", False), ("sound", True)):
        e = _khak_frame(sound)
        for window, start in (("main", MAIN_FROM), ("history", HISTORY_FROM)):
            w = e.filter(C("date") >= pl.lit(start).str.to_date())
            cur = w.filter(C("m").is_in([0.75, 1.0, 1.15, 1.3]))
            key = f"{label}_{window}"
            out[key] = {
                "events_current_steps": cur.height,
                "steps": _step_table(w),
                "ladders": _ladder_test(w),
                "agree_x60_current_steps": _agree_test(
                    cur, cols, "x60", min_n=100 if window == "main" else 150
                ),
            }
            if window == "history":
                # train on every depth since 2012, test quarter by quarter from the main window
                out[key]["model_x60"] = _model_test(
                    e.filter(C("date") >= pl.lit(start).str.to_date()), cols, MAIN_FROM
                )
                out[key]["model_x60_history"] = _model_test(
                    e.filter(C("date") >= pl.lit(start).str.to_date()), cols, "2017-01-01"
                )
            print(key, "done", flush=True)
    return out


# ----------------------------------------------------------------------------- part: rank


def rank() -> dict[str, Any]:
    from tmon.backtest.signal_decay import SIGNALS

    p = pl.read_parquet(CACHE / "panel.parquet").filter(C("v2_ok"))
    cols = [c for c in _col_list() if c != "depth_vs_usual"]
    base = [f"r_{s}" for s in SIGNALS]
    regime = p.group_by("date").agg(C("market_trend").mean().alias("mraw"))
    # cross-sectional percentile rank of every column inside the day's pit members, centred
    p = p.with_columns(
        *[((C(c).rank("average").over("date") - 0.5) / C(c).count().over("date") - 0.5).alias(c)
          for c in cols],
        *[(C(b) - 0.5).alias(b) for b in base],
    )  # fmt: skip
    dates = np.sort(p["date"].unique().to_numpy().astype("datetime64[D]"))
    D = dates.size
    di = {d: i for i, d in enumerate(dates)}
    out: dict[str, Any] = {"columns": len(cols), "lambda": LAMBDA}
    k = len(cols)
    for h in (20, 60):
        fy = f"fwd_{h}"
        q = p.filter(C(fy).is_not_null())
        q = q.with_columns(
            y=(C(fy).rank("average").over("date") - 0.5) / C(fy).count().over("date") - 0.5,
            ex=C(fy) - C(fy).mean().over("date"),
        )
        idx = np.array([di[d] for d in q["date"].to_numpy().astype("datetime64[D]")])
        Xe = np.nan_to_num(q.select(cols).to_numpy().astype(float))
        Xb = np.nan_to_num(q.select(base).to_numpy().astype(float))
        yv = q["y"].to_numpy().astype(float)
        exv = q["ex"].to_numpy().astype(float)
        iid = q[G].to_numpy()
        bscore = Xb.mean(1)
        # per-date sufficient statistics: residual of y on the base score, against each column
        resid = yv.copy()
        Gm = np.zeros((D, k, k))
        bv = np.zeros((D, k))
        rg = np.zeros(D, dtype=int)  # regime of the date: market above its 100-day average or not
        mraw = (
            pl.DataFrame({"date": dates}).with_columns(C("date").cast(pl.Date))
            .join(regime, on="date", how="left")["mraw"].fill_null(0).to_numpy()
        )  # fmt: skip
        for t in np.unique(idx):
            m = idx == t
            bs = bscore[m]
            beta = (bs @ yv[m]) / max(bs @ bs, 1e-12)
            resid[m] = yv[m] - beta * bs
            Xt = Xe[m]
            Gm[t] = Xt.T @ Xt
            bv[t] = Xt.T @ resid[m]
        rg = (mraw > 0).astype(int)
        cG, cb = np.cumsum(Gm, 0), np.cumsum(bv, 0)
        # regime-split sums
        cGr = [np.cumsum(Gm * (rg == r)[:, None, None], 0) for r in (0, 1)]
        cbr = [np.cumsum(bv * (rg == r)[:, None], 0) for r in (0, 1)]
        ncount = np.cumsum(np.bincount(idx, minlength=D))

        def weights(t: int, scheme: str) -> np.ndarray | None:
            j = t - h - 1
            if j < 250:
                return None
            if scheme == "ridge":
                Gj, bj = cG[j], cb[j]
            elif scheme == "regime":
                r = rg[t]
                Gj, bj = cGr[r][j], cbr[r][j]
            else:  # ic: sign and size from the past mean covariance with the residual
                return cb[j] / max(ncount[j], 1)
            lam = LAMBDA * float(np.mean(np.diag(Gj))) + 1e-9
            return np.linalg.solve(Gj + lam * np.eye(k), bj)

        schemes = ("base", "ridge", "ic", "regime")
        res_rows: dict[str, list[tuple[int, float, float, float, float, set]]] = {
            s: [] for s in schemes
        }
        start = int(np.searchsorted(dates, np.datetime64("2016-01-01")))
        W: dict[str, np.ndarray | None] = dict.fromkeys(schemes)
        for t in range(start, D):
            m = np.flatnonzero(idx == t)
            if m.size < 50:
                continue
            if (t - start) % 21 == 0:
                for s in schemes[1:]:
                    W[s] = weights(t, s)
            bs = bscore[m]
            for s in schemes:
                if s == "base":
                    sc = bs
                else:
                    w = W[s]
                    if w is None:
                        continue
                    add = Xe[m] @ w
                    # same scale as the base score, then the base keeps half the weight
                    sc = bs / (bs.std() + 1e-12) + add / (add.std() + 1e-12)
                order = np.argsort(sc)
                nd = max(m.size // 10, 5)
                top, bot = order[-nd:], order[:nd]
                mid = order[m.size // 2 - nd // 2 : m.size // 2 + nd // 2]
                ic = float(np.corrcoef(sc, yv[m])[0, 1])
                res_rows[s].append(
                    (t, float(exv[m][top].mean()), float(exv[m][mid].mean()),
                     float(exv[m][bot].mean()), ic, set(iid[m][top].tolist()))
                )  # fmt: skip
        # turnover: share of the top decile that is new against h days earlier
        summary: dict[str, Any] = {}
        base_rows = {r[0]: r for r in res_rows["base"]}
        for s in schemes:
            rows = res_rows[s]
            byt = {r[0]: r for r in rows}
            turn = np.array(
                [1 - len(r[5] & byt[r[0] - h][5]) / max(len(r[5]), 1) if r[0] - h in byt else np.nan
                 for r in rows]
            )  # fmt: skip
            tv = np.array([r[0] for r in rows])
            dd = dates[tv]
            top = np.array([r[1] for r in rows])
            mid = np.array([r[2] for r in rows])
            bot = np.array([r[3] for r in rows])
            ic = np.array([r[4] for r in rows])
            net = top - np.nan_to_num(turn, nan=1.0) * COST
            blk = month_key(dd) // (3 if h == 60 else 1)
            entry: dict[str, Any] = {"mean_turnover": float(np.nanmean(turn))}
            for window, s0 in (("main", MAIN_FROM), ("history", "2016-01-01")):
                w = dd >= np.datetime64(s0)
                cut = halves(dd[w])
                e: dict[str, Any] = {"split": str(cut), "dates": int(w.sum())}
                for half, mm in (("first", w & (dd < cut)), ("second", w & (dd >= cut))):
                    b = blk[mm]
                    e[half] = {
                        "ic": float(np.nanmean(ic[mm])),
                        "top_gross": float(np.nanmean(top[mm])),
                        "top_net": block_boot(net[mm], b),
                        "mid": float(np.nanmean(mid[mm])),
                        "bottom": block_boot(bot[mm], b),
                        "spread": block_boot(top[mm] - bot[mm], b),
                    }
                    if s != "base":
                        bt = np.array(
                            [base_rows[t][1] if t in base_rows else np.nan for t in tv[mm]]
                        )
                        bb = np.array(
                            [base_rows[t][3] if t in base_rows else np.nan for t in tv[mm]]
                        )
                        e[half]["top_gain_vs_base"] = block_boot(top[mm] - bt, b)
                        e[half]["bottom_gain_vs_base"] = block_boot(bb - bot[mm], b)
                entry[window] = e
            summary[s] = entry
        # the ridge weights fitted on everything known at the start of the main window
        t0 = int(np.searchsorted(dates, np.datetime64(MAIN_FROM)))
        w0 = weights(t0, "ridge")
        if w0 is not None:
            top_w = np.argsort(-np.abs(w0))[:15]
            summary["ridge_top_weights"] = {cols[i]: float(w0[i]) for i in top_w}
        out[f"h{h}"] = summary
        print("rank h", h, "done", flush=True)
    return out


# ----------------------------------------------------------------------------- part: power


def power() -> dict[str, Any]:
    from tmon.features.extra import BOOK_COLUMNS, FUND_COLUMNS
    from tmon.features.relative import REL_FUND_COLUMNS

    p = pl.read_parquet(CACHE / "panel.parquet").filter(C("v2_ok"))
    out: dict[str, Any] = {}
    for group, cols, start in (
        ("book", BOOK_COLUMNS, "2025-03-10"),
        ("fund", (*FUND_COLUMNS, *REL_FUND_COLUMNS), MAIN_FROM),
    ):
        g = p.filter(C("date") >= pl.lit(start).str.to_date())
        res: dict[str, Any] = {}
        for h in (20, 60):
            fy = f"fwd_{h}"
            for c in cols:
                q = g.filter(C(c).is_not_null() & C(fy).is_not_null())
                daily = (
                    q.with_columns(
                        a=C(c).rank().over("date"),
                        b=C(fy).rank().over("date"),
                        n=pl.len().over("date"),
                    )
                    .filter(C("n") >= 20)
                    .group_by("date")
                    .agg(ic=pl.corr("a", "b"), n=pl.len())
                    .sort("date")
                    .drop_nulls("ic")
                )
                if daily.height < 40:
                    res[f"{c}_h{h}"] = {"days": daily.height}
                    continue
                d = daily["date"].to_numpy().astype("datetime64[D]")
                icv = daily["ic"].to_numpy()
                cut = halves(d)
                blk = month_key(d) // (3 if h == 60 else 1)
                # independent periods: non-overlapping h-day windows; the smallest |IC| the sample
                # can tell from zero 80% of the time at 5%: (1.96 + 0.84) x sd / sqrt(periods)
                periods = max(daily.height // h, 1)
                sd_period = float(np.nanstd(icv)) * 1.0  # daily IC sd ~ per-window sd (overlap)
                res[f"{c}_h{h}"] = {
                    "days": daily.height,
                    "stocks_per_day": float(daily["n"].mean()),
                    "ic_first": float(icv[d < cut].mean()),
                    "ic_second": float(icv[d >= cut].mean()),
                    "ic": block_boot(icv, blk),
                    "independent_periods": periods,
                    "min_detectable_ic": float(2.8 * sd_period / math.sqrt(periods)),
                }
        out[group] = res
    return out


# ----------------------------------------------------------------------------- main


def _dump(name: str, obj: dict[str, Any]) -> None:
    tag = "" if name != "rank" or LAMBDA == 5 else f"-lambda{LAMBDA:g}"
    path = OUT / f"columns-deep-{name}{tag}.json"
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", path)


def main(argv: list[str]) -> None:
    what = argv[0] if argv else "all"
    if what == "build":
        build()
        return
    parts = {"market": market, "khak": khak, "rank": rank, "power": power}
    for name, fn in parts.items():
        if what in (name, "all"):
            _dump(name, fn())


if __name__ == "__main__":
    main(sys.argv[1:])
