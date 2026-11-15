"""The v2 ranking page's data: today's ordering of the liquid basket, the evidence per horizon and
the gate verdicts, computed together so the page never shows a ranking without its record.

``python -m tmon.tools.v2_ranking`` writes one JSON document (object store key ``v2/ranking.json``)
that the API serves at ``/v2/ranking``. The ranking is the four-signal composite of ADR 0003 with
no tuning. Whether it may be labelled a recommendation is decided only by the gates (ADR 0003
section 7): while any gate fails, the document says so and the page says so.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.backtest.exposure_eval import sell_queue_share
from tmon.backtest.runner import mean_risk_free, risk_free_daily
from tmon.backtest.signal_decay import (
    SIGNALS,
    adjusted_close,
    build_panel,
    daily_ic,
    forward_returns,
    summarize_ic,
    top_decile_spread,
)
from tmon.backtest.v2_gates import (
    basket_index,
    build_matrices,
    evaluate,
    restrict_top_liquid,
    verdict,
)
from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.engine import adapt
from tmon.engine.exposure import compute_exposure
from tmon.features.builder import KEYS, build_features
from tmon.features.store import load_benchmark_inputs, load_inputs
from tmon.storage.models import Instrument
from tmon.storage.objectstore import get_object_store
from tmon.tools import adapt_cycle

KEY = "v2/ranking.json"
REVIEW_HORIZON = 5  # the product reviews every 5 days, so the horizon-5 champion governs
HORIZONS = (1, 5, 20, 60)  # trading days: next day, week, month, three months
BASKET = 100
EXTRA_MIN_VALUE = 1e10  # rial/day (1bn toman) for a buy-zone name outside the basket


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def _zone(r: float, buy_top: float, hold_top: float) -> str:
    if r > 1.0 - buy_top:
        return "buy"
    if r > 1.0 - hold_top:
        return "hold"
    return "avoid"


def rows_for(universe: list[dict[str, Any]], names: dict[int, Instrument]) -> list[dict[str, Any]]:
    """Top ``BASKET`` eligible, not halted names by 20-day median traded value, ordered by the same
    score the whole universe gets (:func:`universe_scores`), so a partly ingested last day leaves
    no hole in the basket."""
    pool = [
        u
        for u in universe
        if u["eligible"] and not u["halted"] and u["median_value"] and not u.get("too_new")
    ]
    top = sorted(pool, key=lambda u: u["median_value"], reverse=True)[:BASKET]
    core = {u["id"] for u in top}
    # A buy-zone name just outside the 100 most traded still trades enough to buy; leaving it out
    # made strong names drop off the page whenever their liquidity rank slipped for a day.
    top += [
        u
        for u in pool
        if u["id"] not in core and u["zone"] == "buy" and u["median_value"] >= EXTRA_MIN_VALUE
    ]
    top.sort(key=lambda u: (u["score"] is None, -(u["score"] or 0.0)))
    out: list[dict[str, Any]] = []
    for u in top:
        ins = names.get(u["id"])
        if ins is None:
            continue
        zone = u["zone"]
        if u["queue_state"] == "sell_queue":
            zone = "excluded"
        elif zone is None:
            zone = "no_data"
        out.append(
            {
                "symbol": ins.symbol_fa,
                "name": ins.name_fa,
                "sector_code": ins.sector_code,
                "score": u["score"],
                "zone": zone,
                "queue_state": u["queue_state"],
                "median_value": u["median_value"],
                "partial": u["partial"],
                "in_basket": u["id"] in core,
                "signals": {s: u["signals"].get(s) for s in SIGNALS},
            }
        )
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def _mid_rank(ref: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Percentile of ``x`` inside the sorted reference sample, mid-rank for ties. For members of
    the sample this equals the engine's ``(average rank - 0.5) / n``."""
    left = np.searchsorted(ref, x, side="left")
    right = np.searchsorted(ref, x, side="right")
    return (left + right) / 2.0 / len(ref)


STALE_DAYS = 10  # trading days a signal may be carried forward when its newest value is missing
MIN_SIGNALS = 2  # fewer known signals than this: no score at all
# A name needs about a year of trading days before it is scored: the 12-1 month momentum looks 252
# days back, the 52-week high needs the same, and the validated score is only meaningful against
# names that have all four signals. A fresh listing (or one that just resumed after a long
# suspension) has too little history and is left out of the ranking instead of getting a
# score built from the two or three signals it happens to have.
MIN_RANK_DAYS = 253


def latest_signals(
    feats: pl.DataFrame, adj: pl.DataFrame, last: date, stale_days: int = STALE_DAYS
) -> pl.DataFrame:
    """One row per instrument seen in the last ``stale_days`` trading days: the state columns from
    its newest row, and each signal's newest known value with the date it is from.

    The newest day is often only partly ingested (client types arrive later than prices, and a
    halted or untraded name has no row at all), so taking the signals of that one day only left
    most of the market unscored."""
    cols = list(SIGNALS)
    mom = forward_returns(adj, (5,)).select(*KEYS, "mom_12_1")
    days = feats.filter(pl.col("date") <= last).select("date").unique().sort("date")
    window = days.tail(stale_days)["date"]
    d = (
        feats.filter(pl.col("date").is_in(window.implode()))
        .select(*KEYS, "eligible", "market_halt", "queue_state", "median_value_20", *cols[:3])
        .join(mom, on=list(KEYS), how="left")
        .sort(*KEYS)
    )
    known = {c: pl.col(c).is_not_null() & pl.col(c).is_finite() for c in cols}
    return d.group_by("instrument_id").agg(
        pl.col("date").last().alias("seen"),
        pl.col("eligible").last(),
        pl.col("market_halt").last(),
        pl.col("queue_state").last(),
        pl.col("median_value_20").drop_nulls().last(),
        *[pl.col(c).filter(known[c]).last() for c in cols],
        *[pl.col("date").filter(known[c]).last().alias(f"{c}__at") for c in cols],
    )


def universe_scores(
    feats: pl.DataFrame,
    adj: pl.DataFrame,
    cfg: EngineConfig,
    last: date,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """The composite score of every instrument traded in the last ``STALE_DAYS`` trading days, not
    only the liquid basket.

    The reference cross-section is the engine's own universe (eligible, not halted, not in a sell
    queue, all four signals known). Every instrument is placed inside that reference distribution
    signal by signal, using each signal's newest known value (:func:`latest_signals`), so all
    scores share the 0-1 scale; only the basket's is validated by the gates. A name with at least
    ``MIN_SIGNALS`` known signals is scored from those (weights renormalised) and marked
    ``partial``; ``signals_as_of`` is the oldest date any of its signals comes from."""
    cols = list(SIGNALS)
    d = latest_signals(feats, adj, last)
    days = dict(
        adj.filter(pl.col("date") <= last)
        .group_by("instrument_id")
        .len()
        .iter_rows()  # (instrument_id, trading days on record)
    )
    d = d.with_columns(
        pl.col("instrument_id")
        .replace_strict(days, default=0, return_dtype=pl.Int64)
        .alias("history_days")
    ).with_columns((pl.col("history_days") < MIN_RANK_DAYS).alias("too_new"))
    w = np.full(len(cols), 1.0 / len(cols))
    if weights is not None:
        w = np.array([weights.get(c, 0.0) for c in cols], dtype=float)
        w = w / np.abs(w).sum()
    excluded = list(cfg.universe.exclude_queue_states)
    member = d.filter(
        pl.all_horizontal([pl.col(c).is_not_null() for c in cols])
        & ~pl.col("too_new")
        & pl.col("eligible")
        & ~pl.col("market_halt")
        & ~pl.col("queue_state").is_in(excluded)
    )
    refs = {c: np.sort(member[c].to_numpy().astype(float)) for c in cols}

    def signal_rank(c: str, x: float) -> float:
        p = float(_mid_rank(refs[c], np.array([x]))[0])
        return p if SIGNALS[c] > 0 else 1.0 - p

    def composite(r: dict[str, Any]) -> tuple[float, dict[str, float]] | None:
        have = [k for k, c in enumerate(cols) if r[c] is not None]
        if len(have) < MIN_SIGNALS:
            return None
        ranks = {cols[k]: signal_rank(cols[k], float(r[cols[k]])) for k in have}
        ww = np.abs(w[have]).sum()
        if ww == 0:
            return None
        # rounded so that exactly tied sums stay tied (float noise must not split them)
        return round(sum(w[k] * ranks[cols[k]] for k in have) / ww, 12), ranks

    rows = list(d.iter_rows(named=True))
    comps = [None if r["too_new"] else composite(r) for r in rows]
    full = [
        c[0]
        for r, c in zip(rows, comps, strict=True)
        if c is not None
        and len(c[1]) == len(cols)
        and r["eligible"]
        and not r["market_halt"]
        and r["queue_state"] not in excluded
    ]
    comp_ref = np.sort(np.array(full, dtype=float))
    pc = cfg.v2.portfolio
    out: list[dict[str, Any]] = []
    for r, c in zip(rows, comps, strict=True):
        missing = [k for k in cols if r[k] is None]
        score = float(_mid_rank(comp_ref, np.array([c[0]]))[0]) if c and len(comp_ref) else None
        dates = [r[f"{k}__at"] for k in cols if r[f"{k}__at"] is not None]
        out.append(
            {
                "id": r["instrument_id"],
                "eligible": bool(r["eligible"]),
                "halted": bool(r["market_halt"]),
                "queue_state": r["queue_state"],
                "median_value": _f(r["median_value_20"]),
                "missing": missing,
                "partial": bool(missing) and score is not None,
                "too_new": bool(r["too_new"]),
                "history_days": int(r["history_days"]),
                "seen": str(r["seen"]),
                "signals_as_of": str(min(dates)) if dates else None,
                "score": score,
                "zone": _zone(score, pc.buy_top_frac, pc.hold_top_frac)
                if score is not None
                else None,
                "signals": c[1] if c else {},
            }
        )
    return out


def live_weights(
    state: dict[str, Any] | None, as_of: date
) -> tuple[dict[str, float] | None, str, str]:
    """``(weights, champion, note)`` for the production score.

    ``weights`` is None (the plain equal mean, ADR 0003) unless the living ranking's champion for
    the review horizon passed its gate, can be written as weights on the four signals, and was
    computed on the same last day as this ranking. A state of another day is never used."""
    if not state:
        return None, adapt.EQUAL, "no_state"
    if state.get("as_of") != str(as_of):
        return None, adapt.EQUAL, "state_not_current"
    cell = (state.get("horizons") or {}).get(str(REVIEW_HORIZON)) or {}
    champion = str(cell.get("champion", adapt.EQUAL))
    w = adapt.weights_for(state, REVIEW_HORIZON)
    if champion == adapt.EQUAL or all(abs(v - 1 / len(w)) < 1e-9 for v in w.values()):
        return None, adapt.EQUAL, "equal"
    return w, champion, "champion"


def build_document() -> dict[str, Any]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
        index_daily, rf = load_benchmark_inputs(s)
        names = {i.id: i for i in s.scalars(select(Instrument))}
    code = cfg.benchmarks.indices["equal_weight"]
    ew = index_daily.filter(pl.col("index_code") == code).select("date", "close").sort("date")
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    panel = build_panel(feats, adj, cfg, horizons=HORIZONS)
    day = panel["date"].max()
    assert isinstance(day, date)
    weights, champion, note = live_weights(adapt_cycle.load_state(), day)
    if weights is not None:  # a gate-passing champion sets the score: the gates judge that score
        panel = build_panel(feats, adj, cfg, horizons=HORIZONS, weights=weights)

    as_of = day
    universe = universe_scores(feats, adj, cfg, as_of, weights)
    rows = rows_for(universe, names)
    evidence = []
    for h in HORIZONS:
        ic = summarize_ic(daily_ic(panel, "r_composite", h), h)
        sp = top_decile_spread(panel, h)
        evidence.append(
            {
                "horizon_days": h,
                "ic": _f(ic["mean"]),
                "ic_t": _f(ic["t"]),
                "top_excess": _f(sp["top_excess"]),
                "bottom_excess": _f(sp["bottom_excess"]),
                "excess_t": _f(sp.get("t")),
                "n_days": int(sp["n_days"]),
                "signals": {
                    sig: {"ic": _f(si["mean"]), "t": _f(si["t"])}
                    for sig in SIGNALS
                    for si in [summarize_ic(daily_ic(panel, f"r_{sig}", h), h)]
                },
            }
        )

    m = restrict_top_liquid(
        build_matrices(feats, adj, panel, sectors, rules, cfg),
        BASKET,
        cfg.v2.portfolio.min_cross_section,
    )
    rf_daily = risk_free_daily(rf, ew.filter(pl.col("date") >= rf["date"].min())["date"])
    rf_annual = mean_risk_free(rf, rf["date"].min(), rf["date"].max(), cfg)
    sell_share = sell_queue_share(feats)
    bench = basket_index(m, cfg.v2.portfolio.review_every_days)
    js, info = evaluate(m, ew, rf_daily, sell_share, rf_annual, cfg, bench)
    gates = [
        {
            "candidate": j.name,
            "first": str(j.first),
            "last": str(j.last),
            "days": j.days,
            "annual": _f(j.cand.get("annualized_return")),
            "annual_bench": _f(j.ew.get("annualized_return")),
            "max_drawdown": _f(j.cand.get("max_drawdown")),
            "max_drawdown_bench": _f(j.ew.get("max_drawdown")),
            "verdict": verdict(j),
            "gates": [
                {"key": k, "passed": g["passed"], "text": g["text"]} for k, g in j.gates.items()
            ],
        }
        for j in js
    ]
    exp = compute_exposure(ew, rf_daily, sell_share, cfg.v2.exposure).tail(1).to_dicts()[0]
    round_trip = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip
    allowed = all(g["passed"] is True for j in js for g in j.gates.values())
    return {
        "as_of": str(as_of),
        "basket_size": BASKET,
        "recommendation_allowed": allowed,
        "round_trip_cost": round_trip,
        "buy_top_frac": cfg.v2.portfolio.buy_top_frac,
        "hold_top_frac": cfg.v2.portfolio.hold_top_frac,
        "exposure": {
            k: (None if exp.get(k) is None else float(exp[k]))
            for k in ("trend", "abs_mom", "vol_cap", "stress", "exposure")
        },
        "exposure_date": str(exp["date"]),
        "rows": rows,
        "universe": universe,
        "weights": weights or {s: 1 / len(SIGNALS) for s in SIGNALS},
        "weights_champion": champion,
        "weights_note": note,
        "evidence": evidence,
        "gates": gates,
        "book": {
            "n_buys": info["n_buys"],
            "cancelled_buys": info["cancelled_buys"],
            "postponed_sells": info["postponed_sells"],
            "avg_held": info["avg_held"],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-v2-ranking")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
    z = {k: sum(r["zone"] == k for r in doc["rows"]) for k in ("buy", "hold", "avoid")}
    print(f"as_of={doc['as_of']} rows={len(doc['rows'])} zones={z}")
    print(f"recommendation_allowed={doc['recommendation_allowed']}")


if __name__ == "__main__":
    main()
