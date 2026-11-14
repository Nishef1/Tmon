"""The living ranking: re-test, every cycle, which way of weighting the signals the market is
rewarding now, and keep the fixed equal weights unless a challenger earns the place.

Everything is causal: the model of date ``t`` is fit only on dates whose outcome was already known
at ``t`` (purge gap ``h + 1``), exactly as in ``backtest.adaptive_study`` (whose schemes are used
as they are). The two public entry points:

* :func:`run_cycle` looks at the latest ``window_dates`` out-of-sample dates of every horizon,
  gates each candidate against ``equal`` and names the champion per horizon (``equal`` when nobody
  passes). It also reports today's weights, today's score of the champion for every symbol and the
  drift of the weights.
* :func:`replay` re-runs the same gate on the past every ``replay_every_dates`` dates, using only
  what was known on each date, and measures the algorithm itself: the IC of "whatever the gate
  chose" against ``equal``, in both halves. That, not any single candidate's edge, is the answer
  to "does the living ranking do better than the fixed one".

The gate (all must hold, else the candidate stays out):
  1. its IC is higher than ``equal``'s with paired t >= ``min_t``;
  2. the gain is positive in the first half and in the second half of the window;
  3. its top-decile excess beats ``equal``'s;
  4. its top-decile excess is larger than one round-trip cost.

Nothing here changes the production score by itself; ``weights_for`` returns the weights the
product may use for a horizon (``equal`` unless a production-expressible champion is sitting).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from tmon.backtest.adaptive_study import B_IDX, Ctx, K, run, schemes
from tmon.backtest.walkforward_study import BASE, CANDS, HORIZONS, WARMUP, Panel, summ
from tmon.core.engine_config import AdaptCfg

EQUAL = "equal"
REFERENCE = "ridge4_x120"  # always computed: the weight drift shown to the reader
# weights on the four production signals only: the product may adopt these
PRODUCTION_EXPRESSIBLE = ("ridge4_", "icw_", "hedge_")
LINEAR = (*PRODUCTION_EXPRESSIBLE, "step", "ridgeall_")

NOT_ENOUGH = "داده‌ی پنجره برای داوری در دو نیمه کافی نیست"
R_IC = "امتیازش از وزن مساوی بهتر نیست یا اطمینان کافی ندارد"
R_HALVES = "برتری‌اش در هر دو نیمهٔ پنجره دیده نمی‌شود"
R_EXCESS = "مازاد دهک بالایش از وزن مساوی بیشتر نیست"
R_COST = "مازاد دهک بالایش از هزینهٔ رفت‌وبرگشت کمتر است"


def _f(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else float(x)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[str, ...]
    n: int
    ic: float | None = None
    d_ic: float | None = None
    t: float | None = None
    early: float | None = None
    late: float | None = None
    top_excess: float | None = None
    d_top_excess: float | None = None


def gate(
    ic: np.ndarray,
    ic_eq: np.ndarray,
    ex: np.ndarray,
    ex_eq: np.ndarray,
    h: int,
    cfg: AdaptCfg,
    round_trip: float,
) -> Verdict:
    """Verdict of one candidate over a window (aligned daily series, NaN where missing)."""
    ok = np.isfinite(ic) & np.isfinite(ic_eq)
    n = int(ok.sum())
    if n < 2 * cfg.min_half_dates:
        return Verdict(False, (NOT_ENOUGH,), n)
    d = (ic - ic_eq)[ok]
    s = summ(d, h)
    mid = n // 2
    early, late = float(d[:mid].mean()), float(d[mid:].mean())
    both = ok & np.isfinite(ex) & np.isfinite(ex_eq)
    top = float(ex[both].mean()) if both.any() else math.nan
    d_top = float((ex - ex_eq)[both].mean()) if both.any() else math.nan
    mean_d = float(d.mean())
    t = s["t"]
    reasons: list[str] = []
    if not (mean_d > 0 and t is not None and t >= cfg.min_t):
        reasons.append(R_IC)
    if not (early > 0 and late > 0):
        reasons.append(R_HALVES)
    if not d_top > 0:
        reasons.append(R_EXCESS)
    if not top > round_trip:
        reasons.append(R_COST)
    return Verdict(
        passed=not reasons,
        reasons=tuple(reasons),
        n=n,
        ic=float(ic[ok].mean()),
        d_ic=mean_d,
        t=_f(t),
        early=early,
        late=late,
        top_excess=_f(top),
        d_top_excess=_f(d_top),
    )


def choose(
    verdicts: Mapping[str, Verdict], previous: str | None, margin_t: float
) -> tuple[str, str]:
    """``(champion, why)``: the best passing candidate by t; the sitting champion stays while it
    still passes unless a challenger's t beats it by ``margin_t``; ``equal`` when nobody passes."""
    passing = {n: v for n, v in verdicts.items() if v.passed and v.t is not None}
    if not passing:
        return EQUAL, "هیچ نامزدی از دروازه نگذشت؛ وزن مساوی می‌ماند"
    best = max(passing, key=lambda n: passing[n].t or -math.inf)
    if previous in passing and previous != best:
        if (passing[best].t or 0) < (passing[previous].t or 0) + margin_t:
            return previous, "قهرمان قبلی هنوز از دروازه می‌گذرد و رقیب به‌اندازهٔ کافی بهتر نیست"
        return best, "رقیب با حاشیهٔ کافی از قهرمان قبلی بهتر شد"
    if previous == best:
        return best, "قهرمان قبلی هنوز بهترین است"
    return best, "نامزد از دروازه گذشت"


def is_linear(name: str) -> bool:
    return name == EQUAL or name.startswith(LINEAR)


def is_production_expressible(name: str) -> bool:
    return name == EQUAL or name.startswith(PRODUCTION_EXPRESSIBLE)


def _identity_weights(pred: Any, state: np.ndarray) -> np.ndarray:
    # score(e_i) = w_i for a linear score X @ w
    return np.asarray(pred(np.eye(K), state), dtype=float)


def _named(w: np.ndarray, *, base_only: bool = False) -> dict[str, float]:
    """Weights as shares of the total absolute weight, by signal name (zeros left out)."""
    tot = float(np.abs(w).sum())
    if tot <= 0:
        return {}
    idx = B_IDX if base_only else range(K)
    return {CANDS[i]: round(float(w[i] / tot), 4) for i in idx if abs(w[i]) > 1e-12}


def _scheme_pick(names: tuple[str, ...]) -> dict[str, Any]:
    all_s = schemes()
    missing = [n for n in names if n not in all_s]
    if missing:
        raise ValueError(f"unknown adapt candidates: {missing}")
    return {EQUAL: all_s[EQUAL], REFERENCE: all_s[REFERENCE], **{n: all_s[n] for n in names}}


def _window(p: Panel, hi: int, cfg: AdaptCfg) -> tuple[int, int]:
    """``(first, last)`` date indices of the gate window: the latest dates with a known outcome."""
    last = p.D - 1 - HORIZONS[hi]
    return max(WARMUP, last - cfg.window_dates + 1), last


def run_cycle(
    panel: Panel,
    cfg: AdaptCfg,
    round_trip: float,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One live cycle on the data as it stands now."""
    c = Ctx(panel)
    p = panel
    sch = _scheme_pick(cfg.candidates)
    as_of = str(p.dates[-1])
    prev_h = (previous or {}).get("horizons", {})
    out_h: dict[str, Any] = {}
    for hi, h in enumerate(HORIZONS):
        first, last = _window(p, hi, cfg)
        runs = {n: run(c, fn, hi, first) for n, fn in sch.items()}
        eq_ic, eq_ex, _ = runs[EQUAL]
        sl = slice(first, last + 1)
        verdicts = {
            n: gate(ic[sl], eq_ic[sl], ex[sl], eq_ex[sl], h, cfg, round_trip)
            for n, (ic, ex, _s) in runs.items()
            if n in cfg.candidates
        }
        champion, why = choose(
            verdicts, (prev_h.get(str(h)) or {}).get("champion"), cfg.switch_margin_t
        )
        pred = sch[champion](c, p.D - 1, hi)
        weights: dict[str, float] = {}
        live: dict[str, float] | None = None
        if pred is not None and champion != EQUAL:
            score = np.asarray(pred(p.X[-1], p.state[-1]), dtype=float)
            order = score.argsort().argsort() / max(len(score) - 1, 1)
            live = {str(int(i)): round(float(r), 4) for i, r in zip(p.ids[-1], order, strict=True)}
            if is_linear(champion):
                weights = _named(_identity_weights(pred, p.state[-1]))
        if champion == EQUAL:
            weights = {s: round(1 / len(BASE), 4) for s in BASE}
        ref = sch[REFERENCE](c, p.D - 1, hi)
        out_h[str(h)] = {
            "horizon_days": h,
            "window": {
                "from": str(p.dates[first]),
                "to": str(p.dates[last]),
                "dates": last - first + 1,
            },
            "champion": champion,
            "why": why,
            "production_expressible": is_production_expressible(champion),
            "weights": weights,
            "reference_weights": _named(_identity_weights(ref, p.state[-1]), base_only=True)
            if ref is not None
            else {},
            "candidates": {
                n: asdict(v) | {"reasons": list(v.reasons)} for n, v in verdicts.items()
            },
            "live_scores": live,
        }
    history = [r for r in (previous or {}).get("history", []) if r["as_of"] != as_of]
    history.append({"as_of": as_of, "champions": {k: v["champion"] for k, v in out_h.items()}})
    return {
        "as_of": as_of,
        "round_trip_cost": round_trip,
        "config": cfg.model_dump(mode="json"),
        "horizons": out_h,
        "drift": _drift(c, cfg),
        "history": history[-cfg.history_keep :],
        "replay": (previous or {}).get("replay"),
    }


def _drift(c: Ctx, cfg: AdaptCfg, months: int = 24, step: int = 21) -> dict[str, Any]:
    """The reference scheme's weights on the four signals, every ``step`` dates for ``months``."""
    p = c.p
    fn = schemes()[REFERENCE]
    ts = list(range(p.D - 1, max(p.D - 1 - months * step, WARMUP) - 1, -step))[::-1]
    out: dict[str, Any] = {}
    for hi, h in enumerate(HORIZONS):
        dates: list[str] = []
        series: dict[str, list[float]] = {s: [] for s in BASE}
        for t in ts:
            pred = fn(c, t, hi)
            if pred is None:
                continue
            w = _named(_identity_weights(pred, p.state[t]), base_only=True)
            dates.append(str(p.dates[t]))
            for s in BASE:
                series[s].append(w.get(s, 0.0))
        out[str(h)] = {"dates": dates, "series": series}
    return out


def replay(panel: Panel, cfg: AdaptCfg, round_trip: float) -> dict[str, Any]:
    """The gate re-run on the past: what the living ranking would have chosen at each date, using
    only what was known then, and the IC of those choices against ``equal``."""
    c = Ctx(panel)
    p = panel
    sch = _scheme_pick(cfg.candidates)
    res: dict[str, Any] = {"every": cfg.replay_every_dates, "horizons": {}}
    for hi, h in enumerate(HORIZONS):
        runs = {n: run(c, fn, hi, WARMUP) for n, fn in sch.items()}
        eq_ic, eq_ex, _ = runs[EQUAL]
        meta_ic = np.full(p.D, np.nan)
        meta_ex = np.full(p.D, np.nan)
        timeline: list[dict[str, Any]] = []
        champion: str | None = None
        first_cycle = WARMUP + cfg.window_dates + h + 1
        for t in range(first_cycle, p.D, cfg.replay_every_dates):
            last = t - h - 1  # newest date whose outcome is known at t
            sl = slice(last - cfg.window_dates + 1, last + 1)
            verdicts = {
                n: gate(ic[sl], eq_ic[sl], ex[sl], eq_ex[sl], h, cfg, round_trip)
                for n, (ic, ex, _s) in runs.items()
                if n in cfg.candidates
            }
            champion, _why = choose(verdicts, champion, cfg.switch_margin_t)
            timeline.append({"date": str(p.dates[t]), "champion": champion})
            end = min(t + cfg.replay_every_dates, p.D)
            meta_ic[t:end] = runs[champion][0][t:end]
            meta_ex[t:end] = runs[champion][1][t:end]
        both = np.isfinite(meta_ic) & np.isfinite(eq_ic)
        from_t = first_cycle
        valid = np.where(both)[0]
        half = valid[len(valid) // 2] if valid.size else from_t
        d = meta_ic - eq_ic
        dx = meta_ex - eq_ex
        res["horizons"][str(h)] = {
            "horizon_days": h,
            "first_cycle": str(p.dates[first_cycle]) if first_cycle < p.D else None,
            "n_cycles": len(timeline),
            "share_equal": float(np.mean([r["champion"] == EQUAL for r in timeline]))
            if timeline
            else None,
            "meta_ic": summ(np.where(both, meta_ic, np.nan), h),
            "equal_ic": summ(np.where(both, eq_ic, np.nan), h),
            "d_ic": summ(np.where(both, d, np.nan), h),
            "d_ic_early": summ(np.where(both & (np.arange(p.D) < half), d, np.nan), h),
            "d_ic_late": summ(np.where(both & (np.arange(p.D) >= half), d, np.nan), h),
            "d_top_excess": summ(np.where(both, dx, np.nan), h),
            "split_date": str(p.dates[int(half)]) if valid.size else None,
            "timeline": timeline,
            "candidate_counts": {
                n: sum(1 for r in timeline if r["champion"] == n)
                for n in sorted({r["champion"] for r in timeline})
            },
        }
        print("replay horizon", h, "done", flush=True)
    return res


def weights_for(state: dict[str, Any] | None, horizon_days: int) -> dict[str, float]:
    """Weights on the four production signals for ``horizon_days``: equal unless the sitting
    champion is a production-expressible scheme that passed the gate."""
    eq = {s: 1 / len(BASE) for s in BASE}
    if not state:
        return eq
    h = (state.get("horizons") or {}).get(str(horizon_days))
    if not h or h.get("champion") == EQUAL or not h.get("production_expressible"):
        return eq
    w = {s: float(h["weights"].get(s, 0.0)) for s in BASE}
    tot = sum(abs(v) for v in w.values())
    return {s: v / tot for s, v in w.items()} if tot > 0 else eq
