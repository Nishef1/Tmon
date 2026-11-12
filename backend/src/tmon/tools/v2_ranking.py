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

import polars as pl
from sqlalchemy import select

from tmon.backtest.exposure_eval import sell_queue_share
from tmon.backtest.runner import mean_risk_free, risk_free_daily
from tmon.backtest.signal_decay import (
    SIGNALS,
    adjusted_close,
    build_panel,
    daily_ic,
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
from tmon.domain.rules import RuleBook
from tmon.engine.exposure import compute_exposure
from tmon.features.builder import build_features
from tmon.features.store import load_benchmark_inputs, load_inputs
from tmon.storage.models import Instrument
from tmon.storage.objectstore import get_object_store

KEY = "v2/ranking.json"
HORIZONS = (5, 20, 60)
BASKET = 100


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def _zone(r: float, buy_top: float, hold_top: float) -> str:
    if r > 1.0 - buy_top:
        return "buy"
    if r > 1.0 - hold_top:
        return "hold"
    return "avoid"


def rows_for(
    feats: pl.DataFrame, panel: pl.DataFrame, names: dict[int, Instrument], cfg: EngineConfig
) -> tuple[date, list[dict[str, Any]]]:
    """Top ``BASKET`` eligible names by 20-day median traded value on the last day, with the
    composite rank (percentile in the whole eligible universe, as the gates used it)."""
    last = panel["date"].max()
    assert isinstance(last, date)
    today = feats.filter((pl.col("date") == last) & pl.col("eligible") & ~pl.col("market_halt"))
    top = today.sort("median_value_20", descending=True).head(BASKET)
    ranks = panel.filter(pl.col("date") == last).select(
        "instrument_id",
        "r_composite",
        *[f"r_{s}" for s in SIGNALS],
    )
    j = top.select("instrument_id", "queue_state", "median_value_20").join(
        ranks, on="instrument_id", how="left"
    )
    pc = cfg.v2.portfolio
    out: list[dict[str, Any]] = []
    for r in j.sort("r_composite", descending=True, nulls_last=True).iter_rows(named=True):
        ins = names.get(r["instrument_id"])
        if ins is None:
            continue
        rc = r["r_composite"]
        if rc is None:
            zone = "excluded" if r["queue_state"] == "sell_queue" else "no_data"
        else:
            zone = _zone(float(rc), pc.buy_top_frac, pc.hold_top_frac)
        out.append(
            {
                "symbol": ins.symbol_fa,
                "name": ins.name_fa,
                "sector_code": ins.sector_code,
                "score": _f(rc),
                "zone": zone,
                "queue_state": r["queue_state"],
                "median_value": _f(r["median_value_20"]),
                "signals": {s: _f(r[f"r_{s}"]) for s in SIGNALS},
            }
        )
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return last, out


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

    as_of, rows = rows_for(feats, panel, names, cfg)
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
    allowed = all(g["passed"] is True for j in js for g in j.gates.values())
    return {
        "as_of": str(as_of),
        "basket_size": BASKET,
        "recommendation_allowed": allowed,
        "buy_top_frac": cfg.v2.portfolio.buy_top_frac,
        "hold_top_frac": cfg.v2.portfolio.hold_top_frac,
        "exposure": {
            k: (None if exp.get(k) is None else float(exp[k]))
            for k in ("trend", "abs_mom", "vol_cap", "stress", "exposure")
        },
        "exposure_date": str(exp["date"]),
        "rows": rows,
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
