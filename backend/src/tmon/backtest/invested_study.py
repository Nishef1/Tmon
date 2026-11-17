"""ADR 0004 sections 4-6: the pre-registered study of seven books (S0-S6) and the decile profile.

Nothing here is tuned. The seven configurations, the phases, the judging rule and the zone rules are
written in the ADR before the data was looked at; the numbers live in ``engine.yaml`` under
``v2.invested``. The module only computes and reports: it makes no decision about the site.

Conventions, all fixed here and repeated in the report:

* Every book decides at the close of ``t`` and executes at the close of ``t + 1``
  (``simulate_invested``); S4-S6 read the exposure of ``t`` the same way.
* A **start phase** is the book starting ``phase`` days later. All phases are scored on one fixed
  window that begins after the warm-up of the latest phase, so the phases are comparable.
* The base run is phase 0; the judging rule's conditions 1, 2 and 4 are read on it and condition 3
  on all phases.
* S4-S6 need the exposure, which exists only from mid-2024, so they and their comparator (S0 on
  the same days) use that shorter window.
* The score used by S2/S3 is the R3 one (percentile among every ranked name). S1 drops the bottom
  30% of the *tradable basket* by re-ranking inside the basket.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.invested_sim import InvestedParams, InvestedResult, simulate_invested
from tmon.backtest.signal_decay import MIN_CROSS_SECTION
from tmon.backtest.v2_gates import Matrices, monthly, yearly
from tmon.core.engine_config import EngineConfig
from tmon.features.builder import KEYS

CODES = ("S0", "S1", "S2", "S3", "S4", "S5", "S6")
LABELS = {
    "S0": "سبد هم‌وزن جهان قابل‌معامله، بخر و نگه‌دار (معیار)",
    "S1": "S0 بدون ۳۰٪ پایین امتیاز",
    "S2": "سبد R3 با قاعده‌های بند ۳",
    "S3": "سبد کند",
    "S4": "S0 × مواجهه",
    "S5": "S2 × مواجهه",
    "S6": "S3 × مواجهه",
}
BASE_OF = {"S4": "S0", "S5": "S2", "S6": "S3"}


@dataclass
class StudyData:
    m: Matrices  # the liquid basket (names outside it have no rank)
    expo: np.ndarray  # exposure decided at each close; NaN where unknown
    rf: np.ndarray  # treasury-bill return of the day; 0 where there is no yield
    rf_known: np.ndarray  # bool: the day has a yield
    official: np.ndarray  # official equal-weight index return; NaN where unknown
    own_index: np.ndarray  # the basket's own costed 5-day index; NaN where unknown
    cfg: EngineConfig


def basket_rank(rank: np.ndarray) -> np.ndarray:
    """Percentile of the score inside the day's basket (the names that have a rank)."""
    out = np.full_like(rank, np.nan)
    for d in range(rank.shape[0]):
        ok = np.isfinite(rank[d])
        n = int(ok.sum())
        if n:
            order = rank[d][ok].argsort().argsort()  # ties are rare: the composite is continuous
            out[d, ok] = (order + 0.5) / n
    return out


def params_for(
    code: str,
    cfg: EngineConfig,
    *,
    cost_multiplier: float = 1.0,
    entry_delay: int | None = None,
    redeploy_idle: bool = False,
) -> InvestedParams:
    inv, pc, sz = cfg.v2.invested, cfg.v2.portfolio, cfg.sizing
    base = BASE_OF.get(code, code)
    common: dict[str, Any] = {
        "core_review_every": inv.core_review_days,
        "cost_multiplier": cost_multiplier,
        "entry_delay": entry_delay or pc.entry_delay_days,
        "capital": cfg.backtest.initial_capital,
        "use_exposure": code in BASE_OF,
        "redeploy_idle": redeploy_idle,
    }
    sel: dict[str, Any] = {
        "sector_cap_pct": sz.sector_cap_pct,
        "name_cap_pct": sz.max_position_pct,
        "liquidity_cap": sz.liquidity_cap_of_median_value,
    }
    if base == "S0":
        return InvestedParams(**common)
    if base == "S1":
        return InvestedParams(**common, core_drop_bottom_frac=inv.s1_drop_bottom_frac)
    if base == "S2":
        return InvestedParams(
            **common,
            **sel,
            n_names=pc.n_names,
            n_tranches=pc.n_tranches,
            review_every=pc.review_every_days,
            buy_top_frac=pc.buy_top_frac,
            hold_top_frac=pc.hold_top_frac,
        )
    return InvestedParams(
        **common,
        **sel,
        n_names=inv.slow_n_names,
        n_tranches=inv.slow_n_tranches,
        review_every=inv.slow_review_every_days,
        buy_top_frac=inv.slow_buy_top_frac,
        hold_top_frac=inv.slow_hold_top_frac,
    )


# ------------------------------------------------------------------------------- statistics


def _years(dates: Sequence[Any]) -> float:
    return float((dates[-1] - dates[0]).days) / 365.25


def ann_return(ret: np.ndarray, dates: Sequence[Any]) -> float | None:
    ok = np.isfinite(ret)
    if ok.sum() < 2:
        return None
    r, d = ret[ok], [x for x, k in zip(dates, ok, strict=True) if k]
    yrs = _years(d)
    total = float(np.prod(1.0 + r))
    return total ** (1.0 / yrs) - 1.0 if yrs > 0 and total > 0 else None


def max_drawdown(ret: np.ndarray) -> float:
    eq = np.cumprod(1.0 + np.nan_to_num(ret))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float(-(eq / peak - 1.0).min())  # a positive depth


def _t_stat(x: np.ndarray, per: float = 1.0) -> float | None:
    """Mean over its standard error; ``per`` is how many observations make one independent one."""
    x = x[np.isfinite(x)]
    if x.size < 3 or not x.std(ddof=1) > 0:
        return None
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(max(x.size / per, 1.0))))


def run_metrics(res: InvestedResult, dates: Sequence[Any], lo: int) -> dict[str, Any]:
    r, d = res.ret[lo:], list(dates[lo:])
    mid = len(r) // 2
    yrs = _years(d)
    per_year = len(r) / yrs if yrs > 0 else float("nan")
    mo = monthly(pl.DataFrame({"date": d, "ret": r, "buy": res.bought[lo:]}))
    return {
        "first": d[0].isoformat(),
        "last": d[-1].isoformat(),
        "days": len(r),
        "ann": ann_return(r, d),
        "ann_h1": ann_return(r[:mid], d[:mid]),
        "ann_h2": ann_return(r[mid:], d[mid:]),
        "mdd": max_drawdown(r),
        "vol": float(r.std(ddof=1) * math.sqrt(per_year)),
        "turnover_monthly": float(np.mean(mo["buy"].to_numpy())) if mo.height else None,
        "equity_share": float(res.equity_share[lo:].mean()),
        "names": float(res.n_names[lo:].mean()),
        "selection_names": float(res.n_selection[lo:].mean()),
        "n_buys": res.n_buys,
        "cancelled_buys": res.n_cancelled_buys,
        "replacements": res.n_replacements,
        "postponed_sells": res.n_postponed_sells,
        "core_skipped": res.n_core_skipped,
        "years": {
            str(y): {"ret": v[0], "days": v[1]}
            for y, v in yearly(pl.DataFrame({"date": d, "ret": r})).items()
        },
    }


def _ref_metrics(ret: np.ndarray, dates: Sequence[Any], lo: int) -> dict[str, Any]:
    r, d = ret[lo:], list(dates[lo:])
    ok = np.isfinite(r)
    r0 = np.where(ok, r, 0.0)
    mid = len(r) // 2
    return {
        "ann": ann_return(r0, d),
        "ann_h1": ann_return(r0[:mid], d[:mid]),
        "ann_h2": ann_return(r0[mid:], d[mid:]),
        "mdd": max_drawdown(r0),
        "known_days": int(ok.sum()),
    }


def monthly_excess_t(
    x: InvestedResult, y: InvestedResult, dates: Sequence[Any], lo: int
) -> tuple[float | None, int]:
    def mo(res: InvestedResult) -> pl.DataFrame:
        return monthly(pl.DataFrame({"date": list(dates[lo:]), "ret": res.ret[lo:]}))

    j = mo(x).join(mo(y), on=["y", "m"], suffix="_y")
    ex = (j["ret"] - j["ret_y"]).to_numpy()
    return _t_stat(ex), int(ex.size)


def beats(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("ann", "ann_h1", "ann_h2")
    return all(a[k] is not None and b[k] is not None and a[k] > b[k] for k in keys)


# ------------------------------------------------------------------------------- the study


def exposure_start(expo: np.ndarray, start: int) -> int | None:
    """First day from which the exposure is known on every later day."""
    bad = np.flatnonzero(~np.isfinite(expo))
    first = int(bad.max()) + 1 if bad.size else 0
    first = max(first, start)
    return first if first < expo.size else None


def run_study(
    data: StudyData, phases: Sequence[int], *, redeploy_idle: bool = False, progress: Any = None
) -> dict[str, Any]:
    cfg, m = data.cfg, data.m
    inv = cfg.v2.invested
    dates = m.dates
    rank_b = basket_rank(m.rank)
    pmax = max(phases)
    s_full = m.start
    s_expo = exposure_start(data.expo, m.start)
    if s_expo is None:
        raise ValueError("the exposure is unknown on every day: S4-S6 cannot run")
    lo_full, lo_expo = s_full + inv.warmup_days + pmax, s_expo + inv.warmup_days + pmax
    if lo_expo >= len(dates) - 60:
        raise ValueError("the exposure window is too short for the study")

    cache: dict[tuple[str, int, float, int], InvestedResult] = {}

    def run(code: str, phase: int, cost: float, base: int) -> InvestedResult:
        key = (code, phase, cost, base)
        if key not in cache:
            p = params_for(code, cfg, cost_multiplier=cost, redeploy_idle=redeploy_idle)
            rank = rank_b if code == "S1" else m.rank
            cache[key] = simulate_invested(
                m.ret, rank, m.queue, m.median_value, m.sector, m.buy_cost, m.sell_cost,
                data.rf, data.expo, p, base + phase,
            )  # fmt: skip
            if progress:
                progress(code, phase, cost)
        return cache[key]

    def window(code: str) -> tuple[int, int]:
        return (s_expo, lo_expo) if code in BASE_OF else (s_full, lo_full)

    per_code: dict[str, dict[str, Any]] = {}
    for code in CODES:
        base, lo = window(code)
        runs = [run(code, ph, 1.0, base) for ph in phases]
        base_run = runs[0]
        mets = [run_metrics(r, dates, lo) for r in runs]
        per_code[code] = {
            "base": mets[0],
            "heavy": run_metrics(run(code, phases[0], inv.cost_multiplier, base), dates, lo),
            "phases": {"ann": [x["ann"] for x in mets], "mdd": [x["mdd"] for x in mets]},
            "_runs": runs,
            "_base_run": base_run,
        }

    # comparators: S0 on the exposure window (for S4-S6), S0 on its own (for S1-S3)
    s0_full = per_code["S0"]
    s0_expo: dict[str, Any] = {
        "base": run_metrics(run("S0", phases[0], 1.0, s_expo), dates, lo_expo),
        "heavy": run_metrics(run("S0", phases[0], inv.cost_multiplier, s_expo), dates, lo_expo),
        "phases": [run_metrics(run("S0", ph, 1.0, s_expo), dates, lo_expo) for ph in phases],
    }

    judged: dict[str, dict[str, Any]] = {}
    for code in CODES[1:]:
        e = code in BASE_OF
        ref = s0_expo if e else s0_full
        ref_base = ref["base"]
        ref_heavy = ref["heavy"]
        ref_phases = (
            ref["phases"] if e else [run_metrics(r, dates, lo_full) for r in s0_full["_runs"]]
        )
        _, lo = window(code)
        runs = per_code[code]["_runs"]
        mets = [run_metrics(r, dates, lo) for r in runs]
        c1 = beats(per_code[code]["base"], ref_base)
        c2 = per_code[code]["base"]["mdd"] <= ref_base["mdd"]
        share = float(np.mean([beats(a, b) for a, b in zip(mets, ref_phases, strict=True)]))
        c3 = share >= inv.min_phase_share
        c4 = beats(per_code[code]["heavy"], ref_heavy)
        s0_base_run = run("S0", phases[0], 1.0, s_expo if e else s_full)
        t, n_months = monthly_excess_t(per_code[code]["_base_run"], s0_base_run, dates, lo)
        diffs = np.array([a["ann"] - b["ann"] for a, b in zip(mets, ref_phases, strict=True)])
        judged[code] = {
            "c1": bool(c1), "c2": bool(c2), "c3": bool(c3), "c4": bool(c4),
            "passes": bool(c1 and c2 and c3 and c4),
            "phase_share": share,
            "ann_diff_base": per_code[code]["base"]["ann"] - ref_base["ann"],
            "ann_diff_median": float(np.median(diffs)),
            "ann_diff_worst": float(diffs.min()),
            "ann_diff_best": float(diffs.max()),
            "ann_median": float(np.median([x["ann"] for x in mets])),
            "ann_worst": float(min(x["ann"] for x in mets)),
            "ann_best": float(max(x["ann"] for x in mets)),
            "mdd_median": float(np.median([x["mdd"] for x in mets])),
            "excess_t": t,
            "excess_months": n_months,
            "window": "exposure" if e else "full",
        }  # fmt: skip

    passers = [c for c in CODES[1:] if judged[c]["passes"]]
    winner = max(passers, key=lambda c: per_code[c]["base"]["ann"]) if passers else "S0"

    # references on both windows
    bill = np.where(data.rf_known, data.rf, np.nan)
    refs: dict[str, dict[str, Any]] = {
        w: {
            "official": _ref_metrics(data.official, dates, lo),
            "bill": _ref_metrics(bill, dates, lo) if w == "exposure" else None,
            "own_index": _ref_metrics(data.own_index, dates, lo),
        }
        for w, lo in (("full", lo_full), ("exposure", lo_expo))
    }
    s4 = per_code["S4"]["base"]
    s4_rule = {
        "mdd_not_deeper": bool(s4["mdd"] <= s0_expo["base"]["mdd"]),
        "beats_bill_both_halves": bool(
            s4["ann_h1"] is not None
            and s4["ann_h2"] is not None
            and refs["exposure"]["bill"]["ann_h1"] is not None
            and refs["exposure"]["bill"]["ann_h2"] is not None
            and s4["ann_h1"] > refs["exposure"]["bill"]["ann_h1"]
            and s4["ann_h2"] > refs["exposure"]["bill"]["ann_h2"]
        ),
    }
    s4_rule["apply_exposure"] = bool(all(s4_rule.values()))

    return {
        "phases": list(phases),
        "windows": {
            "full": {
                "first": dates[lo_full].isoformat(),
                "last": dates[-1].isoformat(),
                "book_start": dates[s_full].isoformat(),
            },
            "exposure": {
                "first": dates[lo_expo].isoformat(),
                "last": dates[-1].isoformat(),
                "book_start": dates[s_expo].isoformat(),
            },
        },
        "configs": {
            c: {k: v for k, v in per_code[c].items() if not k.startswith("_")} for c in CODES
        },
        "s0_on_exposure_window": {"base": s0_expo["base"], "heavy": s0_expo["heavy"]},
        "judged": judged,
        "winner": winner,
        "winner_exposure_rule": s4_rule,
        "refs": refs,
        "n_configs_run": len(CODES),
    }


# ------------------------------------------------------------------------------- decile profile


def decile_table(
    panel: pl.DataFrame,
    liquidity: pl.DataFrame,
    horizon: int,
    *,
    top_n: int | None,
) -> dict[str, Any]:
    """Mean forward return of each score decile minus the group mean, per date, then averaged:
    full period and the two halves of time. ``top_n`` keeps the most liquid names without a buy
    queue and re-ranks inside them (what a buyer could have got); ``None`` bins the global
    percentile score of the whole universe. Returns the per-date decile matrix too."""
    fwd = f"fwd_{horizon}"
    d = panel.filter(pl.col(fwd).is_not_null() & pl.col(fwd).is_finite())
    if top_n is not None:
        d = (
            d.join(liquidity.select(*KEYS, "median_value_20"), on=list(KEYS), how="left")
            .filter(
                pl.col("median_value_20").is_not_null() & (pl.col("queue_state") != "buy_queue")
            )
            .with_columns(
                pl.col("median_value_20")
                .rank("ordinal", descending=True)
                .over("date")
                .alias("_liq")
            )
            .filter(pl.col("_liq") <= top_n)
            .with_columns(
                (
                    (pl.col("composite").rank("average").over("date") - 0.5)
                    / pl.col("composite").count().over("date")
                ).alias("_rr")
            )
        )
    else:
        d = d.with_columns(pl.col("r_composite").alias("_rr"))
    d = d.with_columns(
        (pl.col("_rr") * 10).floor().clip(0, 9).cast(pl.Int64).alias("dec"),
        pl.col(fwd).mean().over("date").alias("_avg"),
        pl.len().over("date").alias("_n"),
    ).filter(pl.col("_n") >= MIN_CROSS_SECTION)
    g = (
        d.group_by("date", "dec")
        .agg((pl.col(fwd).mean() - pl.col("_avg").first()).alias("x"))
        .pivot(on="dec", index="date", values="x")
        .sort("date")
    )
    cols = [str(i) for i in range(10)]
    for c in cols:
        if c not in g.columns:
            g = g.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    dates = g["date"].to_list()
    mat = g.select(cols).to_numpy().astype(float)  # (dates, 10), NaN where a decile is empty
    return {"dates": dates, "mat": mat, "horizon": horizon}


def _mean(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(a.mean()) if a.size else float("nan")


def zone_stats(
    mat: np.ndarray, idx: list[int], sign: float, horizon: int, round_trip: float, cfg: EngineConfig
) -> dict[str, Any]:
    """Net excess of a set of deciles (0-based ``idx`` into the per-date decile matrix), in the
    full period and in each half of time, its t, and its ADR 0004 section 6 grade. ``sign`` is +1
    for a zone bought and -1 for a zone avoided (the gain is the shortfall)."""
    n = mat.shape[0]
    mid = n // 2
    s = sign * (np.nanmean(mat[:, idx], axis=1) if idx else np.full(n, np.nan))
    net = _mean(s) - round_trip
    n1, n2 = _mean(s[:mid]) - round_trip, _mean(s[mid:]) - round_trip
    t = _t_stat(s, per=float(horizon))
    inv = cfg.v2.invested
    if net >= inv.grade_min_net_edge and t is not None and t >= inv.grade_min_t:
        g = "ثابت‌شده"
    elif n1 > 0 and n2 > 0:
        g = "احتمالی"
    else:
        g = "ثابت‌نشده"
    return {"net": net, "net_h1": n1, "net_h2": n2, "t": t, "grade": g}


def profile_summary(tab: dict[str, Any], round_trip: float, cfg: EngineConfig) -> dict[str, Any]:
    mat, h = tab["mat"], tab["horizon"]
    n = mat.shape[0]
    mid = n // 2
    halves = (slice(0, mid), slice(mid, n))

    dec: list[dict[str, Any]] = []
    for k in range(10):
        col = mat[:, k]
        dec.append(
            {
                "decile": k + 1,
                "excess": _mean(col),
                "h1": _mean(col[halves[0]]),
                "h2": _mean(col[halves[1]]),
                "t": _t_stat(col, per=float(h)),
            }
        )

    top: list[int] = []
    for k in range(9, -1, -1):
        if dec[k]["h1"] > 0 and dec[k]["h2"] > 0:
            top.append(k)
        else:
            break
    bottom: list[int] = []
    for k in range(10):
        if dec[k]["h1"] < 0 and dec[k]["h2"] < 0:
            bottom.append(k)
        else:
            break
    # a candidate zone may not reach into deciles already claimed by the avoid zone
    bottom = [k for k in bottom if k not in top]

    top_idx = sorted(top)
    cand = {
        "deciles": [k + 1 for k in top_idx],
        **(zone_stats(mat, top_idx, 1.0, h, round_trip, cfg) if top_idx else {}),
    }
    avoid_idx = sorted(bottom)
    avoid = {
        "deciles": [k + 1 for k in avoid_idx],
        **(zone_stats(mat, avoid_idx, -1.0, h, round_trip, cfg) if avoid_idx else {}),
    }
    top1_net = (dec[9]["excess"] - round_trip, dec[9]["h1"] - round_trip, dec[9]["h2"] - round_trip)
    return {
        "horizon": h,
        "days": n,
        "round_trip": round_trip,
        "deciles": dec,
        "candidate": cand,
        "avoid": avoid,
        "top_net": top1_net[0],
        "top_net_both_halves_positive": bool(top1_net[1] > 0 and top1_net[2] > 0),
    }


def verdict_horizon(profiles: dict[int, dict[str, Any]]) -> tuple[int, str]:
    ok = {h: p["top_net"] for h, p in profiles.items() if p["top_net_both_halves_positive"]}
    if ok:
        best = max(ok, key=lambda h: ok[h])
        return best, "از داده"
    return max(profiles), "ثابت‌نشده"
