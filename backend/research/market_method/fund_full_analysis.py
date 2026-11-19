"""Does the stock model's whole page hold up on tradable funds? (docs/reports/fund-verdict-2026-11.md)

(a) The fund placed inside the STOCK ranking: its four signals are ranked against the day's stock
    cross-section (the model's own reference: eligible, not in a sell queue, all four signals),
    the composite is placed in the reference composites, and the fund is a "candidate" above
    ``1 - candidate_top_frac`` and "avoid" at or under ``avoid_bottom_frac`` of that score.
    Per fund group and half of time: rank IC, candidate minus every fund-day of the group, avoid
    minus the same, after a round-trip cost, with the t of non-overlapping days.
(b) The trend-ride rule (entry near the 250-day high with the 50/200 averages, trailing exit)
    on each fund against buying and holding it over the same span: total return, maximum
    drawdown, time in the market, and the share of funds the rule beat, both halves of each
    fund's own span.

Run from backend/ with the live env: python research/market_method/fund_full_analysis.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.backtest.signal_decay import SIGNALS, adjusted_close, build_panel, forward_returns
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import build_features
from tmon.features.store import load_inputs
from tmon.storage.models import Instrument

OUT = Path(__file__).parent / "results_fund_full.json"
HORIZONS = (5, 20)
COST = 0.003  # round trip for a fund
MIN_DAYS_PER_DAY = 3  # funds on one side of a zone on a day
GROUP = {
    "etf_equity": "equity_mixed",
    "etf_mixed": "equity_mixed",
    "etf_leveraged": "leveraged",
    "etf_commodity": "commodity",
    "etf_fixed_income": "fixed_income",
}


def mid_rank(ref: np.ndarray, x: np.ndarray) -> np.ndarray:
    lo = np.searchsorted(ref, x, side="left")
    hi = np.searchsorted(ref, x, side="right")
    return ((lo + hi) / 2.0) / max(len(ref), 1)


def t_stat(x: np.ndarray) -> float | None:
    x = x[np.isfinite(x)]
    if len(x) < 5 or x.std(ddof=1) == 0:
        return None
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def part_stats(d: pl.DataFrame, h: int, cand: float, avoid: float) -> dict[str, float | int | None]:
    f = f"fwd_{h}"
    d = d.filter(pl.col(f).is_not_null() & pl.col(f).is_finite())
    if d.is_empty():
        return {"fund_days": 0}
    by = (
        d.group_by("date")
        .agg(
            pl.len().alias("n"),
            pl.col(f).mean().alias("all"),
            pl.col(f).filter(pl.col("score") > 1 - cand).mean().alias("cand"),
            pl.col(f).filter(pl.col("score") > 1 - cand).len().alias("n_cand"),
            pl.col(f).filter(pl.col("score") <= avoid).mean().alias("avoid"),
            pl.col(f).filter(pl.col("score") <= avoid).len().alias("n_avoid"),
            pl.corr(pl.col("score").rank(), pl.col(f).rank()).alias("ic"),
        )
        .sort("date")
    )
    ind = by.gather_every(h)  # non-overlapping windows for t

    def diff(a: str, na: str) -> tuple[np.ndarray, np.ndarray]:
        ok = by.filter(pl.col(na) >= 1)
        okind = ind.filter(pl.col(na) >= 1)
        return (ok[a] - ok["all"]).to_numpy(), (okind[a] - okind["all"]).to_numpy()

    cd, cdi = diff("cand", "n_cand")
    ad, adi = diff("avoid", "n_avoid")
    icd = by.filter((pl.col("n") >= 8) & pl.col("ic").is_not_null())
    ici = ind.filter((pl.col("n") >= 8) & pl.col("ic").is_not_null())
    # pooled score-vs-return rank correlation, for groups too small for a daily cross-section
    pooled = float(np.corrcoef(d["score"].rank().to_numpy(), d[f].rank().to_numpy())[0, 1])
    return {
        "fund_days": int(d.height),
        "days": int(by.height),
        "funds": int(d["instrument_id"].n_unique()),
        "mean_all": float(d[f].mean()),
        "cand_minus_all": float(cd.mean()) if len(cd) else None,
        "cand_minus_all_net": float(cd.mean() - COST) if len(cd) else None,
        "cand_t": t_stat(cdi),
        "cand_share_days": float(len(cd) / by.height),
        "avoid_minus_all": float(ad.mean()) if len(ad) else None,
        "avoid_t": t_stat(adi),
        "ic": float(icd["ic"].mean()) if icd.height else None,
        "ic_t": t_stat(ici["ic"].to_numpy()) if ici.height else None,
        "pooled_rank_corr": pooled,
    }


def score_vs_stocks(panel: pl.DataFrame, funds: pl.DataFrame) -> pl.DataFrame:
    """``score`` of each fund-day: its composite placed in the day's reference composites, where
    each signal first goes through the same percentile placement as in the live ranking."""
    refs: dict[date, dict[str, np.ndarray]] = {}
    for (dt,), g in panel.group_by(["date"]):
        r = {s: np.sort(g[s].to_numpy().astype(float)) for s in SIGNALS}
        r["_comp"] = np.sort(g["composite"].to_numpy().astype(float))
        refs[dt] = r
    out = []
    for (dt,), g in funds.group_by(["date"]):
        r = refs.get(dt)
        if r is None or len(r["_comp"]) < 30:
            continue
        ranks = []
        for s, sign in SIGNALS.items():
            p = mid_rank(r[s], g[s].to_numpy().astype(float))
            ranks.append(p if sign > 0 else 1.0 - p)
        comp = np.mean(ranks, axis=0)
        out.append(g.with_columns(pl.Series("score", mid_rank(r["_comp"], comp))))
    return pl.concat(out)


def study_a(cfg, feats, adj, ffeats, fadj, kinds) -> dict:
    vc = cfg.v2.verdict
    horizons = HORIZONS
    panel = build_panel(feats, adj, cfg, horizons=horizons)
    # panel signals are already percentile ranks r_*; the reference needs the RAW signal values
    raw = feats.select("instrument_id", "date", "ind_buy_power", "rv_20", "dist_high_52w").join(
        forward_returns(adj, horizons).select("instrument_id", "date", "mom_12_1"),
        on=["instrument_id", "date"],
        how="left",
    )
    ref_panel = panel.select("instrument_id", "date", "composite").join(
        raw, on=["instrument_id", "date"], how="left"
    )
    # eligible fund rows of the model's own universe (equity and mixed funds)
    fund_ids = [i for i, k in kinds.items() if k == "equity_mixed"]
    own = panel.filter(pl.col("instrument_id").is_in(fund_ids)).select(
        "instrument_id", "date", *[f"fwd_{h}" for h in horizons]
    )
    own = own.join(raw, on=["instrument_id", "date"], how="left")
    own = own.filter(
        pl.all_horizontal([pl.col(s).is_not_null() & pl.col(s).is_finite() for s in SIGNALS])
    )
    # comparison funds: eligible by the same liquidity and history rule, own signals and returns
    fw = forward_returns(fadj, horizons).select(
        "instrument_id", "date", "mom_12_1", *[f"fwd_{h}" for h in horizons]
    )
    ext = (
        ffeats.filter(~pl.col("market_halt") & pl.col("eligible"))
        .select("instrument_id", "date", "queue_state", "ind_buy_power", "rv_20", "dist_high_52w")
        .join(fw, on=["instrument_id", "date"], how="left")
        .filter(~pl.col("queue_state").is_in(cfg.universe.exclude_queue_states))
        .drop("queue_state")
    )
    ext = ext.filter(
        pl.all_horizontal([pl.col(s).is_not_null() & pl.col(s).is_finite() for s in SIGNALS])
    )
    funds = pl.concat([own, ext.select(own.columns)])
    ref = ref_panel.filter(
        pl.all_horizontal([pl.col(s).is_not_null() & pl.col(s).is_finite() for s in SIGNALS])
    ).join(panel.select("instrument_id", "date").unique(), on=["instrument_id", "date"])
    scored = score_vs_stocks(ref, funds)
    scored = scored.with_columns(
        pl.col("instrument_id").replace_strict(kinds, default=None).alias("kind")
    )
    rows: dict = {}
    for gname in ("equity_mixed", "leveraged", "commodity", "fixed_income", "all"):
        sub = scored if gname == "all" else scored.filter(pl.col("kind") == gname)
        if sub.is_empty():
            rows[gname] = {"fund_days": 0}
            continue
        dates = sorted(sub["date"].unique().to_list())
        mid = dates[len(dates) // 2]
        rows[gname] = {
            "first": str(dates[0]),
            "last": str(dates[-1]),
            "mid": str(mid),
            "mean_score": float(sub["score"].mean()),
            "share_candidate": float((sub["score"] > 1 - vc.candidate_top_frac).mean()),
            "share_avoid": float((sub["score"] <= vc.avoid_bottom_frac).mean()),
        }
        for h in horizons:
            for hn, part in {
                "all": sub,
                "first": sub.filter(pl.col("date") < mid),
                "second": sub.filter(pl.col("date") >= mid),
            }.items():
                rows[gname][f"h{h}_{hn}"] = part_stats(
                    part, h, vc.candidate_top_frac, vc.avoid_bottom_frac
                )
    return rows


def ride_study(cfg, prices, clients, kinds, rules) -> dict:
    ids = list(kinds)
    p = prices.filter(pl.col("instrument_id").is_in(ids))
    c = clients.filter(pl.col("instrument_id").is_in(ids))
    panel = tp.build_panel(p, c)
    rc = cfg.v2.trend_ride
    by = tr.all_rides(panel, rc.near_high, rc.trail, rc.max_hold_days, rc.same_day)
    per: list[dict] = []
    for iid, (g, rs) in by.items():
        close = g["close"].to_numpy().astype(float)
        dts = g["date"].to_list()
        n = len(close)
        if n < 60:
            continue
        r = np.concatenate([[0.0], close[1:] / close[:-1] - 1.0])
        pos = np.zeros(n, dtype=bool)  # held over day t (bought at the close of entry)
        trades = 0
        for q in rs:
            if q.entry is None:
                continue
            end = n - 1 if q.exit is None else q.exit
            pos[q.entry + 1 : end + 1] = True
            trades += 1
        mid = n // 2

        def seg(a: int, b: int) -> dict[str, float | int]:
            rr = r[a:b]
            pp = pos[a:b]
            held = np.where(pp, rr, 0.0)
            entries = int(np.sum(pp & ~np.concatenate([[False], pp[:-1]])))
            eq = np.cumprod(1.0 + held) * (1.0 - COST) ** entries
            bh = np.cumprod(1.0 + rr)
            dd = lambda x: float(np.min(x / np.maximum.accumulate(np.maximum(x, 1e-12)) - 1.0))  # noqa: E731
            return {
                "strategy": float(eq[-1] - 1.0),
                "hold": float(bh[-1] - 1.0),
                "strategy_dd": dd(eq),
                "hold_dd": dd(bh),
                "in_market": float(pp.mean()),
                "trades": entries,
                "days": int(b - a),
            }

        per.append(
            {
                "id": int(iid),
                "kind": kinds[int(iid)],
                "first": str(dts[0]),
                "last": str(dts[-1]),
                "all": seg(1, n),
                "first_half": seg(1, mid),
                "second_half": seg(mid, n),
                "open_now": bool(rs and rs[-1].entry is not None and rs[-1].exit is None),
            }
        )
    out: dict = {"funds": len(per), "per_fund": per}
    for gname in ("equity_mixed", "leveraged", "commodity", "fixed_income", "all"):
        sel = [x for x in per if gname == "all" or x["kind"] == gname]
        agg: dict = {"funds": len(sel)}
        for part in ("all", "first_half", "second_half"):
            if not sel:
                continue
            ex = np.array([x[part]["strategy"] - x[part]["hold"] for x in sel])
            agg[part] = {
                "median_strategy": float(np.median([x[part]["strategy"] for x in sel])),
                "median_hold": float(np.median([x[part]["hold"] for x in sel])),
                "median_dd_strategy": float(np.median([x[part]["strategy_dd"] for x in sel])),
                "median_dd_hold": float(np.median([x[part]["hold_dd"] for x in sel])),
                "mean_strategy": float(np.mean([x[part]["strategy"] for x in sel])),
                "mean_hold": float(np.mean([x[part]["hold"] for x in sel])),
                "mean_diff": float(ex.mean()),
                "median_diff": float(np.median(ex)),
                "share_ahead": float((ex > 0).mean()),
                "mean_dd_strategy": float(np.mean([x[part]["strategy_dd"] for x in sel])),
                "mean_dd_hold": float(np.mean([x[part]["hold_dd"] for x in sel])),
                "mean_in_market": float(np.mean([x[part]["in_market"] for x in sel])),
                "t_diff": t_stat(ex),
            }
        out[gname] = agg
    return out


def main() -> None:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        fprices, fclients, fsectors = load_inputs(s, comparison_funds=True)
        rules = RuleBook.from_session(s)
        types = {i.id: i.instrument_type for i in s.scalars(select(Instrument))}
    kinds = {i: GROUP[t] for i, t in types.items() if t in GROUP}
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    ffeats = build_features(fprices, fclients, rules, sectors=fsectors)
    fadj = adjusted_close(fprices)
    result = {
        "a_in_stock_ranking": study_a(cfg, feats, adj, ffeats, fadj, kinds),
        "b_trend_ride": ride_study(
            cfg,
            pl.concat([prices, fprices.select(prices.columns)]),
            pl.concat([clients, fclients.select(clients.columns)]),
            kinds,
            rules,
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for g, v in result["a_in_stock_ranking"].items():
        print("A", g, {k: x for k, x in v.items() if not k.startswith("h")})
        for k, x in v.items():
            if k.startswith("h"):
                print("  ", k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in x.items()})
    for g in ("equity_mixed", "leveraged", "commodity", "fixed_income", "all"):
        b = result["b_trend_ride"].get(g) or {}
        for part in ("all", "first_half", "second_half"):
            x = b.get(part)
            if x:
                print("B", g, b["funds"], part, {k: round(v, 3) for k, v in x.items() if v is not None})


if __name__ == "__main__":
    main()
