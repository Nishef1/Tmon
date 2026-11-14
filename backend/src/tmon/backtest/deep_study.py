# ruff: noqa: N803, N806  (X, Y, V, ... are matrix names)
"""Deep, autoregressive and diffusion ranking models, tested the same causal way as the linear ones
in ``adaptive_study`` (no transformer).

Every model for date ``t`` is fit only on dates whose label was already known (``j = t - h - 1``),
refit every ``EVERY`` dates, and judged out of sample against equal weights with the same paired
statistic, in both halves. Methods:

* ``dmlp``     torch MLP with dropout and weight decay on the signal ranks and the market state;
* ``gru``      autoregressive GRU over each stock's last ``SEQ`` days of signal ranks, market state
               and its own lagged return rank (lag >= 2, what was already known);
* ``tcn``      causal dilated-convolution network on the same sequences;
* ``diff``     conditional diffusion: a denoiser learns to recover the future return rank from noise
               given the signals; the score is the mean of posterior samples;
* ``resid``    residual learning: equal weights plus a shrunk network that corrects them;
* combinations: ``gbm_gru`` (standardised mean of LightGBM and the GRU), ``deep_avg`` (mean of the
  four deep models), ``hedge_all`` (Hedge over every model by its own recent IC).

Each deep model is trained with several seeds; its score is the standardised mean over the seeds and
the per-seed mean ICs are kept so the spread is visible. ``python -m tmon.backtest.deep_study``
writes ``docs/data/deep-study.json``. Nothing here changes the production model.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from tmon.backtest.adaptive_study import (
    B_IDX,
    Ctx,
    K,
    ensemble,
    icw_x,
    model_scheme,
    ridge_x,
)
from tmon.backtest.walkforward_study import (
    HORIZONS,
    MIN_N,
    WARMUP,
    Panel,
    build_panel,
    paired,
    summ,
)

SEQ = 16  # days of history per stock for the sequence models
LAG_Y = 2  # the stock's own return rank enters with this lag (label of date d is known at d + 2)
EVERY = 126  # dates between refits of a deep model
WINDOW = 750  # training dates
FRAC = 0.2  # share of a date's stocks used per training date
VAL_DATES = 60
EPOCHS = 14
PATIENCE = 3
BATCH = 2048
STATE_DIM = 3
T_STEPS = 20  # diffusion steps
N_SAMPLES = 12  # posterior samples per stock

PredT = Callable[[int], np.ndarray]  # date index -> score of every stock of that date
KINDS = ("dmlp", "gru", "tcn", "diff", "resid")


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Seq:
    """Dense (date, stock, feature) history on the device, so a stock's last days can be read."""

    def __init__(self, p: Panel, dev: torch.device):
        self.dev = dev
        ids = np.unique(np.concatenate(p.ids))
        pos = {int(i): k for k, i in enumerate(ids)}
        D, N = p.D, len(ids)
        V = np.zeros((D, N, K + 2), dtype=np.float32)  # K signals, lagged y1, "present"
        y1 = np.full((D, N), np.nan, dtype=np.float32)
        self.rows: list[np.ndarray] = []
        for t in range(D):
            r = np.array([pos[int(i)] for i in p.ids[t]])
            self.rows.append(r)
            V[t, r, :K] = np.nan_to_num(p.X[t])
            V[t, r, K + 1] = 1.0
            y1[t, r] = p.Y[t][:, 0]
        lag = np.full((D, N), np.nan, dtype=np.float32)
        lag[LAG_Y:] = y1[:-LAG_Y]
        V[:, :, K] = np.nan_to_num(lag)
        self.V = torch.tensor(V, device=dev)
        self.state = torch.tensor(p.state, dtype=torch.float32, device=dev)
        self.D = D

    def gather(
        self, t: torch.Tensor, r: torch.Tensor, steps: int, mu: torch.Tensor, sd: torch.Tensor
    ) -> torch.Tensor:
        """(n, steps, K + 2 + STATE_DIM) features for stocks ``r`` of dates ``t``, oldest first."""
        back = torch.arange(steps - 1, -1, -1, device=self.dev)
        tt = (t[:, None] - back[None, :]).clamp(min=0)
        v = self.V[tt, r[:, None]]
        st = (self.state[tt] - mu) / sd
        return torch.cat([v, st], dim=2)


class MLPNet(nn.Module):
    def __init__(self, d_in: int, hidden: Sequence[int] = (128, 64), drop: float = 0.2):
        super().__init__()
        layers: list[nn.Module] = []
        d = d_in
        for h in hidden:
            layers += [nn.Linear(d, h), nn.GELU(), nn.Dropout(drop)]
            d = h
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (n, steps, f) -> last day only
        out: torch.Tensor = self.net(_dense_cond(x)).squeeze(-1)
        return out


class GRUNet(nn.Module):
    def __init__(self, d_in: int, hidden: int = 32, drop: float = 0.1):
        super().__init__()
        self.rnn = nn.GRU(d_in, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Dropout(drop), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, h = self.rnn(x)
        out: torch.Tensor = self.head(h[-1]).squeeze(-1)
        return out


class TCNNet(nn.Module):
    """Causal dilated convolutions (dilations 1, 2, 4: receptive field 15 days)."""

    def __init__(self, d_in: int, ch: int = 32, drop: float = 0.1):
        super().__init__()
        self.convs = nn.ModuleList()
        c = d_in
        for dil in (1, 2, 4):
            self.convs.append(nn.Conv1d(c, ch, kernel_size=3, dilation=dil))
            c = ch
        self.dil = (1, 2, 4)
        self.head = nn.Sequential(nn.Dropout(drop), nn.Linear(ch, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = x.transpose(1, 2)
        for conv, dil in zip(self.convs, self.dil, strict=True):
            h = nn.functional.gelu(conv(nn.functional.pad(h, (2 * dil, 0))))
        out: torch.Tensor = self.head(h[:, :, -1]).squeeze(-1)
        return out


class Denoiser(nn.Module):
    """epsilon(y_t, step | features): the network of the conditional diffusion model."""

    def __init__(self, d_cond: int, hidden: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_cond + 1 + 8, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, 1),
        )

    @staticmethod
    def embed(step: torch.Tensor) -> torch.Tensor:
        f = torch.arange(1, 5, device=step.device, dtype=torch.float32)
        a = step[:, None].float() / T_STEPS * math.pi * f[None, :]
        return torch.cat([a.sin(), a.cos()], dim=1)

    def forward(self, cond: torch.Tensor, y_t: torch.Tensor, step: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(
            torch.cat([cond, y_t[:, None], self.embed(step)], dim=1)
        ).squeeze(-1)
        return out


def _alphas(dev: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    beta = torch.linspace(1e-3, 0.25, T_STEPS, device=dev)
    alpha = 1.0 - beta
    return beta, alpha, torch.cumprod(alpha, 0)


def _dense_cond(x: torch.Tensor) -> torch.Tensor:
    """Signals and market state of the last day (the lag column and presence flag left out)."""
    return torch.cat([x[:, -1, :K], x[:, -1, K + 2 :]], dim=1)


class Lab:
    """Panel, device data, the adaptive-study context and the cache of fitted models."""

    def __init__(self, p: Panel, dev: torch.device | None = None):
        self.p = p
        self.dev = dev or device()
        self.seq = Seq(p, self.dev)
        self.c = Ctx(p)
        self.cache: dict[tuple[Any, ...], PredT | None] = {}

    # ------------------------------------------------------------------ data

    def _rows(
        self, hi: int, lo: int, j: int, rng: np.random.Generator
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Training (date, stock-row, label) triples of dates lo..j with a known label."""
        ts, rs, ys = [], [], []
        for t in range(max(lo, SEQ), j + 1):
            Y = self.p.Y[t][:, hi]
            m = np.isfinite(Y)
            if m.sum() < MIN_N:
                continue
            pick = np.flatnonzero(m & (rng.random(m.size) < FRAC))
            ts.append(np.full(pick.size, t))
            rs.append(self.seq.rows[t][pick])
            ys.append(Y[pick])
        return np.concatenate(ts), np.concatenate(rs), np.concatenate(ys).astype(np.float32)

    # ----------------------------------------------------------------- models

    def _net(self, kind: str, d_in: int) -> nn.Module:
        if kind in ("dmlp", "resid"):
            return MLPNet(d_in)
        if kind == "gru":
            return GRUNet(d_in)
        if kind == "tcn":
            return TCNNet(d_in)
        raise ValueError(kind)

    def fit(self, kind: str, seed: int, hi: int, j: int) -> PredT | None:
        """Fit on dates <= ``j`` (labels known) and return the scorer of a date."""
        h = HORIZONS[hi]
        if j < 150:
            return None
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        dev = self.dev
        T, R, y = self._rows(hi, j - WINDOW, j, rng)
        if T.size < 2000:
            return None
        steps = 1 if kind in ("dmlp", "resid", "diff") else SEQ
        st = self.p.state[: j + 1]
        mu = torch.tensor(st.mean(0), dtype=torch.float32, device=dev)
        sd = torch.tensor(np.maximum(st.std(0), 1e-9), dtype=torch.float32, device=dev)
        tt = torch.tensor(T, device=dev)
        rr = torch.tensor(R, device=dev)
        yy = torch.tensor(y, device=dev)
        cut = T.max() - VAL_DATES
        tr = torch.tensor(np.flatnonzero(cut - h - 1 >= T), device=dev)  # purge: no label overlap
        va = torch.tensor(np.flatnonzero(cut < T), device=dev)
        if tr.numel() < 1000 or va.numel() < 200:
            return None
        sample = self.seq.gather(tt[:2], rr[:2], steps, mu, sd)
        d_in = K + STATE_DIM if steps == 1 else sample.shape[2]
        # residual learning: equal weights (mean of the four production signals) are the base
        eq_coef = 0.0
        if kind == "resid":
            eq_all = self.seq.V[tt, rr][:, B_IDX].mean(1)
            eq_coef = float((eq_all[tr] * yy[tr]).sum() / (eq_all[tr] ** 2).sum().clamp_min(1e-9))
            yy = yy - eq_coef * eq_all

        if kind == "diff":
            return self._fit_diff(tt, rr, yy, tr, va, mu, sd, seed)

        net = self._net(kind, d_in).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
        best, best_state, bad = math.inf, None, 0
        for _ in range(EPOCHS):
            net.train()
            perm = tr[torch.randperm(tr.numel(), device=dev)]
            for b in range(0, perm.numel(), BATCH):
                ix = perm[b : b + BATCH]
                xb = self.seq.gather(tt[ix], rr[ix], steps, mu, sd)
                loss = nn.functional.mse_loss(net(xb), yy[ix])
                opt.zero_grad(set_to_none=True)
                loss.backward()  # type: ignore[no-untyped-call]
                opt.step()
            net.eval()
            with torch.no_grad():
                v = float(
                    nn.functional.mse_loss(
                        net(self.seq.gather(tt[va], rr[va], steps, mu, sd)), yy[va]
                    )
                )
            if v < best - 1e-6:
                best, bad = v, 0
                best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
            else:
                bad += 1
                if bad >= PATIENCE:
                    break
        if best_state is not None:
            net.load_state_dict(best_state)
        net.eval()
        shrink = 0.5

        def score(t: int) -> np.ndarray:
            r = torch.tensor(self.seq.rows[t], device=dev)
            tv = torch.full_like(r, t)
            with torch.no_grad():
                x = self.seq.gather(tv, r, steps, mu, sd)
                out = net(x)
                if kind == "resid":
                    out = eq_coef * self.seq.V[tv, r][:, B_IDX].mean(1) + shrink * out
            arr: np.ndarray = out.cpu().numpy().astype(np.float64)
            return arr

        return score

    def _fit_diff(
        self,
        tt: torch.Tensor,
        rr: torch.Tensor,
        yy: torch.Tensor,
        tr: torch.Tensor,
        va: torch.Tensor,
        mu: torch.Tensor,
        sd: torch.Tensor,
        seed: int,
    ) -> PredT:
        dev = self.dev
        beta, alpha, abar = _alphas(dev)
        net = Denoiser(K + STATE_DIM).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
        gen = torch.Generator(device=dev)
        gen.manual_seed(seed)

        def loss_on(ix: torch.Tensor) -> torch.Tensor:
            cond = _dense_cond(self.seq.gather(tt[ix], rr[ix], 1, mu, sd))
            y0 = (2.0 * yy[ix]).clamp(-1, 1)
            s = torch.randint(0, T_STEPS, (ix.numel(),), device=dev, generator=gen)
            eps = torch.randn(ix.numel(), device=dev, generator=gen)
            ab = abar[s]
            y_t = ab.sqrt() * y0 + (1 - ab).sqrt() * eps
            return nn.functional.mse_loss(net(cond, y_t, s), eps)

        best, best_state, bad = math.inf, None, 0
        for _ in range(EPOCHS + 6):
            net.train()
            perm = tr[torch.randperm(tr.numel(), device=dev)]
            for b in range(0, perm.numel(), BATCH):
                loss = loss_on(perm[b : b + BATCH])
                opt.zero_grad(set_to_none=True)
                loss.backward()  # type: ignore[no-untyped-call]
                opt.step()
            net.eval()
            with torch.no_grad():
                v = float(loss_on(va))
            if v < best - 1e-6:
                best, bad = v, 0
                best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
            else:
                bad += 1
                if bad >= PATIENCE:
                    break
        if best_state is not None:
            net.load_state_dict(best_state)
        net.eval()

        def score(t: int) -> np.ndarray:
            r = torch.tensor(self.seq.rows[t], device=dev)
            tv = torch.full_like(r, t)
            with torch.no_grad():
                cond0 = _dense_cond(self.seq.gather(tv, r, 1, mu, sd))
                n = cond0.shape[0]
                cond = cond0.repeat_interleave(N_SAMPLES, dim=0)
                y = torch.randn(n * N_SAMPLES, device=dev, generator=gen)
                for s in range(T_STEPS - 1, -1, -1):
                    sv = torch.full((y.numel(),), s, device=dev)
                    eps = net(cond, y, sv)
                    y0 = ((y - (1 - abar[s]).sqrt() * eps) / abar[s].sqrt()).clamp(-1, 1)
                    if s > 0:
                        mean = (abar[s - 1].sqrt() * beta[s] / (1 - abar[s])) * y0 + (
                            alpha[s].sqrt() * (1 - abar[s - 1]) / (1 - abar[s])
                        ) * y
                        var = beta[s] * (1 - abar[s - 1]) / (1 - abar[s])
                        y = mean + var.sqrt() * torch.randn(y.shape, device=dev, generator=gen)
                    else:
                        y = y0
                out = y.view(n, N_SAMPLES).mean(1)
            return out.cpu().numpy().astype(np.float64)

        return score

    def predictor(self, kind: str, seed: int, hi: int, t: int) -> PredT | None:
        j = t - HORIZONS[hi] - 1
        key = (kind, seed, hi, t // EVERY)
        if key not in self.cache:
            self.cache[key] = self.fit(kind, seed, hi, j)
        return self.cache[key]


def _zmean(parts: list[np.ndarray], w: Sequence[float] | None = None) -> np.ndarray:
    out = np.zeros(parts[0].size)
    for i, v in enumerate(parts):
        sd = v.std()
        out += (1.0 if w is None else w[i]) * ((v - v.mean()) / sd if sd > 0 else 0 * v)
    return out


def run_t(
    p: Panel, scorer: Callable[[int, int], np.ndarray | None], hi: int, start: int
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray | None]]:
    """IC and top-decile excess per date for ``scorer(t, hi)``; the same measures as ``run``."""
    ics = np.full(p.D, np.nan)
    exs = np.full(p.D, np.nan)
    scores: list[np.ndarray | None] = [None] * p.D
    for t in range(start, p.D):
        s = scorer(t, hi)
        if s is None:
            continue
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


Run = tuple[np.ndarray, np.ndarray, list[np.ndarray | None]]


def study_horizon(
    lab: Lab, hi: int, seeds: Sequence[int], methods: Sequence[str]
) -> dict[str, Any]:
    p, c = lab.p, lab.c
    h = HORIZONS[hi]
    t0 = time.time()
    runs: dict[str, Run] = {}
    seed_ic: dict[str, list[float | None]] = {}

    def lin(name: str, fn: Any) -> None:
        pred: dict[int, Any] = {}

        def sc(t: int, hh: int) -> np.ndarray | None:
            key = t // 21
            if key not in pred:
                pred[key] = fn(c, t, hh)
            q = pred[key]
            return None if q is None else np.asarray(q(p.X[t], p.state[t]))

        runs[name] = run_t(p, sc, hi, WARMUP)

    lin("equal", lambda cc, t, hh: lambda X, _s: X[:, B_IDX].mean(1))
    lin("ridge4_x120", ridge_x(120, B_IDX))
    lin("icw_x250", icw_x(250))
    for kind in ("gbm", "mlp"):
        if kind in methods:
            fn = model_scheme(kind, every=63 if kind == "gbm" else 126)
            lin(kind, fn)

    for kind in KINDS:
        if kind not in methods:
            continue
        per_seed: list[Run] = []
        for sd in seeds:

            def sc(t: int, _hh: int, sd: int = sd, kind: str = kind) -> np.ndarray | None:
                f = lab.predictor(kind, sd, hi, t)
                return None if f is None else f(t)

            per_seed.append(run_t(p, sc, hi, WARMUP))
        seed_ic[kind] = [summ(r[0], h)["mean"] for r in per_seed]

        def avg(t: int, _hh: int, kind: str = kind) -> np.ndarray | None:
            fs = [lab.predictor(kind, sd, hi, t) for sd in seeds]
            parts = [f(t) for f in fs if f is not None]
            return _zmean(parts) if parts else None

        runs[kind] = run_t(p, avg, hi, WARMUP)
        print(f"  h={h} {kind} done ({time.time() - t0:.0f}s)", flush=True)

    def combo(name: str, parts: Sequence[str]) -> None:
        if not all(x in runs for x in parts):
            return

        def sc(t: int, _hh: int) -> np.ndarray | None:
            v = [runs[x][2][t] for x in parts]
            return None if any(a is None for a in v) else _zmean([a for a in v if a is not None])

        runs[name] = run_t(p, sc, hi, WARMUP)

    combo("gbm_gru", ("gbm", "gru"))
    combo("deep_avg", [k for k in ("dmlp", "gru", "tcn", "diff") if k in runs])
    pool = {n: r for n, r in runs.items() if n not in ("equal", "gbm_gru", "deep_avg")}
    if len(pool) >= 3:
        e_ic, e_ex = ensemble(c, {"equal": runs["equal"], **pool}, hi, WARMUP)
        runs["hedge_all"] = (e_ic, e_ex, [None] * p.D)

    mid = WARMUP + (p.D - WARMUP) // 2
    base_ic, base_ex = runs["equal"][0], runs["equal"][1]
    out: dict[str, Any] = {}
    for n, (ic, ex, _s) in runs.items():
        out[n] = {
            "ic": summ(ic, h),
            "ex": summ(ex, h),
            "d_ic": paired(ic, base_ic, h) if n != "equal" else None,
            "d_ex": paired(ex, base_ex, h) if n != "equal" else None,
            "d_ic_early": paired(ic[:mid], base_ic[:mid], h) if n != "equal" else None,
            "d_ic_late": paired(ic[mid:], base_ic[mid:], h) if n != "equal" else None,
            "seed_ic": seed_ic.get(n),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-deep-study")
    ap.add_argument("--out", default=str(Path("docs/data/deep-study.json")))
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--horizons", default=",".join(str(h) for h in HORIZONS))
    ap.add_argument("--methods", default="gbm,mlp," + ",".join(KINDS))
    a = ap.parse_args()
    methods = a.methods.split(",")
    horizons = [int(x) for x in a.horizons.split(",")]
    p = Panel(build_panel())
    lab = Lab(p)
    seeds = list(range(11, 11 + a.seeds))
    mid = WARMUP + (p.D - WARMUP) // 2
    res: dict[str, Any] = {
        "first": str(p.dates[0]),
        "last": str(p.dates[-1]),
        "oos_from": str(p.dates[WARMUP]),
        "mid": str(p.dates[mid]),
        "device": str(lab.dev),
        "torch": torch.__version__,
        "seeds": seeds,
        "settings": {
            "seq": SEQ,
            "lag_y": LAG_Y,
            "every": EVERY,
            "window": WINDOW,
            "frac": FRAC,
            "epochs": EPOCHS,
            "patience": PATIENCE,
            "diffusion_steps": T_STEPS,
            "samples": N_SAMPLES,
        },
        "horizons": horizons,
        "results": {},
    }
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    for h in horizons:
        hi = HORIZONS.index(h)
        res["results"][str(h)] = study_horizon(lab, hi, seeds, methods)
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1))  # partial results survive
        print("horizon", h, "done", flush=True)
    print("wrote", path)


if __name__ == "__main__":
    main()
