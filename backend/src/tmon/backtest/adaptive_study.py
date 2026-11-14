# ruff: noqa: N803, N806  (X, Y, G, ... are matrix names)
"""Adaptive-weighting research on top of ``walkforward_study``: which way of letting the ranking
re-balance itself as the market changes works, and where it does not.

Every scheme is causal: the model used on date ``t`` is fit only on dates whose label (``1 + h``
dates ahead) was already known at ``t`` (purge gap), and is refit every ``REFIT`` dates. Schemes:

* ``equal``            production composite (four signals, equal weight); the baseline;
* ``ridge_x{hl}``      ridge on the four signals with exponentially forgotten history (half-life
                       ``hl`` dates; ``inf`` = expanding). Equivalent to a Kalman filter with
                       random-walk coefficients, so the weights drift with the market;
* ``ridgeall_x{hl}``   the same on all 18 candidate signals;
* ``icw_x{hl}``        weights from forgotten mean IC (clipped at zero);
* ``hedge_k{kappa}``   multiplicative weights (Hedge): softmax of kappa * forgotten mean IC;
* ``attn_t{tau}``      attention: past dates are weighted by how similar their market state
                       (trend, breadth, flows) is to today's, then a ridge is fit (a causal kernel
                       regression, the retrieval idea behind attention);
* ``step{m}``          forward stepwise selection of m signals on past data, then ridge;
* ``gbm``              LightGBM on signal ranks and market state, refit on a rolling window;
* ``mlp``              small neural network (sklearn MLP) the same way;
* ``ens``              meta-ensemble: standardised scores of the schemes above averaged with weights
                       from each scheme's recent out-of-sample IC (Hedge over models).

Reported per horizon (1, 5, 20, 60, 120 trading days): out-of-sample IC, top-decile excess, paired
difference against ``equal`` with t, and the same in the early and late halves of the out-of-sample
period so a result must hold in both. ``python -m tmon.backtest.adaptive_study`` writes
``docs/data/adaptive-study.json``. Nothing here changes the production model.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from tmon.backtest.walkforward_study import (
    BASE,
    CANDS,
    HORIZONS,
    MIN_N,
    REFIT,
    WARMUP,
    Panel,
    build_panel,
    paired,
    summ,
)

Predict = Callable[[np.ndarray, np.ndarray], np.ndarray]  # (X, state_row) -> score
RIDGE = 0.5
HALF_LIVES = (60, 120, 250, 500, math.inf)
K = len(CANDS)
B_IDX = [CANDS.index(c) for c in BASE]


class Ctx:
    """Precomputed exponentially forgotten sums per half-life."""

    def __init__(self, p: Panel):
        self.p = p
        self.G: dict[float, np.ndarray] = {}
        self.b: dict[float, np.ndarray] = {}
        self.ic: dict[float, np.ndarray] = {}
        z = np.nan_to_num(p.ic)
        for hl in HALF_LIVES:
            lam = 1.0 if math.isinf(hl) else 0.5 ** (1.0 / hl)
            G = np.zeros_like(p.G)
            b = np.zeros_like(p.b)
            ic = np.zeros_like(z)
            wsum = np.zeros(1)
            wsums = np.zeros(p.D)
            for t in range(p.D):
                if t == 0:
                    G[t], b[t], ic[t] = p.G[t], p.b[t], z[t]
                    wsum = np.ones(1)
                else:
                    G[t] = lam * G[t - 1] + p.G[t]
                    b[t] = lam * b[t - 1] + p.b[t]
                    ic[t] = lam * ic[t - 1] + z[t]
                    wsum = lam * wsum + 1.0
                wsums[t] = wsum[0]
            self.G[hl], self.b[hl], self.ic[hl] = G, b, ic / wsums[:, None, None]
        self.state_sd = np.maximum(
            np.array(
                [
                    p.state[: t + 1].std(0) if t > 30 else np.ones(p.state.shape[1])
                    for t in range(p.D)
                ]
            ),
            1e-9,
        )


def _lin(w: np.ndarray) -> Predict:
    return lambda X, _s: X @ w


def _ridge_w(G: np.ndarray, b: np.ndarray, idx: list[int]) -> np.ndarray:
    ix = np.array(idx)
    Gs = G[np.ix_(ix, ix)]
    lam = RIDGE * float(np.mean(np.diag(Gs)))
    w = np.zeros(K)
    w[ix] = np.linalg.solve(Gs + lam * np.eye(len(ix)), b[ix])
    return w


Scheme = Callable[[Ctx, int, int], Predict | None]


def equal4() -> Scheme:
    w = np.zeros(K)
    w[B_IDX] = 0.25
    return lambda _c, _t, _h: _lin(w)


def ridge_x(hl: float, idx: list[int]) -> Scheme:
    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        j = t - HORIZONS[hi] - 1
        if j < 50:
            return None
        return _lin(_ridge_w(c.G[hl][j, hi], c.b[hl][j, hi], idx))

    return fn


def icw_x(hl: float) -> Scheme:
    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        j = t - HORIZONS[hi] - 1
        if j < 50:
            return None
        m = np.clip(c.ic[hl][j, hi, B_IDX], 0.0, None)
        w = np.zeros(K)
        w[B_IDX] = m / m.sum() if m.sum() > 0 else 0.25
        return _lin(w)

    return fn


def hedge_k(kappa: float, hl: float = 120) -> Scheme:
    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        j = t - HORIZONS[hi] - 1
        if j < 50:
            return None
        m = c.ic[hl][j, hi, B_IDX]
        e = np.exp(kappa * (m - m.max()))
        w = np.zeros(K)
        w[B_IDX] = e / e.sum()
        return _lin(w)

    return fn


def attn_t(tau: float, hl: float = 500) -> Scheme:
    """Weight past dates by the similarity of their market state to today's, then ridge."""

    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        p = c.p
        j = t - HORIZONS[hi] - 1
        if j < 100:
            return None
        sd = c.state_sd[j]
        d2 = (((p.state[: j + 1] - p.state[t]) / sd) ** 2).sum(1)
        decay = 0.5 ** ((t - np.arange(j + 1)) / hl)
        a = np.exp(-d2 / (2 * tau**2)) * decay
        a /= a.sum() + 1e-12
        G = np.tensordot(a, p.G[: j + 1, hi], axes=1)
        b = np.tensordot(a, p.b[: j + 1, hi], axes=1)
        return _lin(_ridge_w(G, b, list(range(K))))

    return fn


def step_m(m: int, hl: float = 250) -> Scheme:
    """Forward stepwise selection (explained variance on past data), then ridge on the chosen."""

    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        j = t - HORIZONS[hi] - 1
        if j < 50:
            return None
        G, b = c.G[hl][j, hi], c.b[hl][j, hi]
        chosen: list[int] = []
        for _ in range(m):
            best, best_gain = -1, -1.0
            for i in range(K):
                if i in chosen:
                    continue
                ix = [*chosen, i]
                Gs = G[np.ix_(ix, ix)] + RIDGE * float(np.mean(np.diag(G))) * np.eye(len(ix))
                gain = float(b[ix] @ np.linalg.solve(Gs, b[ix]))
                if gain > best_gain:
                    best, best_gain = i, gain
            chosen.append(best)
        return _lin(_ridge_w(G, b, chosen))

    return fn


def _train_rows(
    p: Panel, hi: int, lo: int, j: int, frac: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for t in range(max(lo, 0), j + 1):
        Y = p.Y[t][:, hi]
        m = np.isfinite(Y)
        if m.sum() < MIN_N:
            continue
        pick = m & (rng.random(m.size) < frac)
        st = np.repeat(p.state[t][None, :], pick.sum(), axis=0)
        xs.append(np.hstack([p.X[t][pick], st]))
        ys.append(Y[pick])
    return np.vstack(xs), np.concatenate(ys)


def model_scheme(kind: str, window: int = 750, every: int = 63) -> Scheme:
    cache: dict[tuple[int, int], Predict | None] = {}

    def fn(c: Ctx, t: int, hi: int) -> Predict | None:
        p = c.p
        j = t - HORIZONS[hi] - 1
        if j < 150:
            return None
        key = (hi, t // every)
        if key in cache:
            return cache[key]
        rng = np.random.default_rng(7)
        X, y = _train_rows(p, hi, j - window, j, 0.15 if kind == "gbm" else 0.08, rng)
        if kind == "gbm":
            import lightgbm as lgb

            mdl = lgb.LGBMRegressor(
                n_estimators=120,
                learning_rate=0.05,
                num_leaves=8,
                min_child_samples=400,
                subsample=0.7,
                subsample_freq=1,
                colsample_bytree=0.7,
                reg_lambda=10.0,
                verbose=-1,
                n_jobs=4,
            )
            mdl.fit(X, y)
        else:
            from sklearn.neural_network import MLPRegressor

            mdl = MLPRegressor(
                hidden_layer_sizes=(32, 16),
                alpha=1e-2,
                early_stopping=True,
                n_iter_no_change=5,
                max_iter=60,
                random_state=7,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mdl.fit(X, y)

        def predict(Xd: np.ndarray, st: np.ndarray) -> np.ndarray:
            Z = np.hstack([Xd, np.repeat(st[None, :], Xd.shape[0], axis=0)])
            return np.asarray(mdl.predict(Z))

        cache[key] = predict
        return predict

    return fn


def run(
    c: Ctx, scheme: Scheme, hi: int, start: int
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray | None]]:
    p = c.p
    ics = np.full(p.D, np.nan)
    exs = np.full(p.D, np.nan)
    scores: list[np.ndarray | None] = [None] * p.D
    pred: Predict | None = None
    for t in range(start, p.D):
        if (t - start) % REFIT == 0:
            pred = scheme(c, t, hi)
        if pred is None:
            continue
        s = pred(p.X[t], p.state[t])
        Y = p.Y[t][:, hi]
        m = np.isfinite(Y)
        if m.sum() < MIN_N or not np.any(s[m] != s[m][0]):
            continue
        scores[t] = s
        ics[t] = float(np.corrcoef(s[m], Y[m])[0, 1])
        f = p.F[t][m, hi]
        top = f[s[m] > np.quantile(s[m], 0.9)]
        exs[t] = float(top.mean() - np.median(f)) if top.size else math.nan
    return ics, exs, scores


def ensemble(
    c: Ctx,
    runs: dict[str, tuple[np.ndarray, np.ndarray, list[np.ndarray | None]]],
    hi: int,
    start: int,
    window: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    """Hedge over the models: weight each by its own recent IC (known with the purge gap)."""
    p = c.p
    h = HORIZONS[hi]
    names = [n for n in runs if n != "equal"]
    ics = np.full(p.D, np.nan)
    exs = np.full(p.D, np.nan)
    for t in range(start + 150, p.D):
        j = t - h - 1
        w = []
        for n in names:
            seg = runs[n][0][max(start, j - window) : j + 1]
            seg = seg[np.isfinite(seg)]
            w.append(max(float(seg.mean()), 0.0) if seg.size >= 20 else 0.0)
        if sum(w) <= 0:
            continue
        Y = p.Y[t][:, hi]
        m = np.isfinite(Y)
        if m.sum() < MIN_N:
            continue
        tot = np.zeros(int(m.sum()))
        for wi, n in zip(w, names, strict=True):
            sc = runs[n][2][t]
            if sc is None or wi == 0:
                continue
            v = sc[m]
            sd = v.std()
            if sd > 0:
                tot += wi * (v - v.mean()) / sd
        if not np.any(tot != tot[0]):
            continue
        ics[t] = float(np.corrcoef(tot, Y[m])[0, 1])
        f = p.F[t][m, hi]
        top = f[tot > np.quantile(tot, 0.9)]
        exs[t] = float(top.mean() - np.median(f)) if top.size else math.nan
    return ics, exs


def schemes() -> dict[str, Scheme]:
    out: dict[str, Scheme] = {"equal": equal4()}
    for hl in HALF_LIVES:
        tag = "inf" if math.isinf(hl) else str(int(hl))
        out[f"ridge4_x{tag}"] = ridge_x(hl, B_IDX)
        out[f"ridgeall_x{tag}"] = ridge_x(hl, list(range(K)))
        out[f"icw_x{tag}"] = icw_x(hl)
    for kappa in (10, 30, 60):
        out[f"hedge_k{kappa}"] = hedge_k(kappa)
    for tau in (0.7, 1.5):
        out[f"attn_t{tau}"] = attn_t(tau)
    for m in (4, 6, 8):
        out[f"step{m}"] = step_m(m)
    out["gbm"] = model_scheme("gbm")
    out["mlp"] = model_scheme("mlp", every=126)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-adaptive-study")
    ap.add_argument("--out", default=str(Path("docs/data/adaptive-study.json")))
    ap.add_argument("--quick", action="store_true", help="skip gbm and mlp")
    args = ap.parse_args()
    p = Panel(build_panel())
    c = Ctx(p)
    sch = schemes()
    if args.quick:
        sch.pop("gbm")
        sch.pop("mlp")
    mid = WARMUP + (p.D - WARMUP) // 2
    res: dict[str, Any] = {
        "first": str(p.dates[0]),
        "last": str(p.dates[-1]),
        "oos_from": str(p.dates[WARMUP]),
        "mid": str(p.dates[mid]),
        "n_schemes": len(sch) + 1,
        "horizons": list(HORIZONS),
        "results": {},
    }
    for hi, h in enumerate(HORIZONS):
        runs = {n: run(c, fn, hi, WARMUP) for n, fn in sch.items()}
        e_ic, e_ex = ensemble(c, runs, hi, WARMUP)
        runs["ens"] = (e_ic, e_ex, [None] * p.D)
        base_ic, base_ex = runs["equal"][0], runs["equal"][1]
        r: dict[str, Any] = {}
        for n, (ic, ex, _s) in runs.items():
            r[n] = {
                "ic": summ(ic, h),
                "ex": summ(ex, h),
                "d_ic": paired(ic, base_ic, h) if n != "equal" else None,
                "d_ex": paired(ex, base_ex, h) if n != "equal" else None,
                "d_ic_early": paired(ic[:mid], base_ic[:mid], h) if n != "equal" else None,
                "d_ic_late": paired(ic[mid:], base_ic[mid:], h) if n != "equal" else None,
            }
        res["results"][str(h)] = r
        print("horizon", h, "done", flush=True)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
