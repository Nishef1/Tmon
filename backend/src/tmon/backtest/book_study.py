"""Do the order book and the queues add anything to the four-signal score?

For every candidate feature, on the days and stocks where ``order_book_daily`` has a book:

* its rank IC against the next 1, 5 and 20 day return (effective n = days / horizon), early and
  late half;
* the paired change in the score's IC when ``w * rank(feature)`` is added (``w`` = 0.1 and 0.25,
  both signs tried, the better sign picked on the *early* half and judged on the *late* half).

A feature is kept only if it helps in both halves with ``|t| > 2``; the rest are dropped.
``python -m tmon.backtest.book_study`` writes ``docs/data/book-study.json``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import text

from tmon.backtest.parameter_study import MIN_N, G, _prank, build, composite, sig_cols
from tmon.backtest.realistic_study import make_paths, simulate_real
from tmon.core.db import session_scope

HZ = (1, 5, 20)
BOARD = (
    "ind_net_flow_ratio",
    "ind_net_flow_z",
    "rel_volume",
    "vol_to_base",
    "last_close_gap",
    "intraday_range_pos",
    "ret_1_norm",
    "days_in_queue",
)
BOOK = (
    "close_imbalance",
    "open_imbalance",
    "early_imbalance",
    "tw_imbalance",
    "tw_spread",
    "tw_depth_value",
    "tw_size_ratio",
    "frac_buy_queue",
    "frac_sell_queue",
    "peak_queue_volume",
)
DERIVED = ("queue_to_median", "depth_to_median", "queue_flip")


def load_book() -> pl.DataFrame:
    with session_scope() as s:
        rows = s.execute(text("select * from order_book_daily")).mappings().all()
    d = pl.DataFrame([dict(r) for r in rows], infer_schema_length=None)
    return d.with_columns(pl.col("date").str.to_date())


def _ic(d: pl.DataFrame, col: str, hz: tuple[int, ...] = HZ) -> pl.DataFrame:
    aggs = [pl.len().alias("n")]
    for h in hz:
        m = pl.col(f"y_{h}").is_not_null() & pl.col(col).is_not_null()
        aggs.append(pl.corr(pl.col(col).filter(m), pl.col(f"y_{h}").filter(m)).alias(f"ic_{h}"))
    return d.group_by("date").agg(*aggs).filter(pl.col("n") >= MIN_N).sort("date")


def _stat(v: np.ndarray[Any, Any], h: int) -> dict[str, float | None]:
    v = v[np.isfinite(v)]
    if v.size < 20:
        return {"mean": None, "t": None, "early": None, "late": None}
    sd = float(v.std(ddof=1))
    half = v.size // 2
    return {
        "mean": float(v.mean()),
        "t": float(v.mean() / (sd / math.sqrt(max(v.size / h, 1.0)))) if sd > 0 else None,
        "early": float(v[:half].mean()),
        "late": float(v[half:].mean()),
    }


def study(panel: pl.DataFrame, feats: list[str]) -> dict[str, Any]:
    base_ic = _ic(panel, "s0")
    out: dict[str, Any] = {
        "dates": base_ic.height,
        "rows": panel.height,
        "base": {str(h): _stat(base_ic[f"ic_{h}"].to_numpy().astype(float), h) for h in HZ},
        "features": {},
    }
    for f in feats:
        d = panel.with_columns(_prank(f).alias("_x"))
        alone = _ic(d, "_x")
        rec: dict[str, Any] = {
            "alone": {str(h): _stat(alone[f"ic_{h}"].to_numpy().astype(float), h) for h in HZ},
            "added": {},
        }
        for w in (0.1, 0.25):
            for sign in (1, -1):
                dd = d.with_columns(
                    (pl.col("s0") + sign * w * pl.col("_x").fill_null(0.0)).alias("s1")
                )
                ic1 = _ic(dd, "s1")
                j = ic1.join(base_ic, on="date", suffix="_b")
                rec["added"][f"w{w}_{'+' if sign > 0 else '-'}"] = {
                    str(h): _stat((j[f"ic_{h}"] - j[f"ic_{h}_b"]).to_numpy().astype(float), h)
                    for h in HZ
                }
        out["features"][f] = rec
    return out


def _delta(panel: pl.DataFrame, cur: str, feat: str, sign: int, w: float, h: int) -> pl.DataFrame:
    """Per-date IC of ``cur + sign * w * rank(feat)`` minus that of ``cur`` at horizon ``h``."""
    d = panel.with_columns((pl.col(cur) + sign * w * _prank(feat).fill_null(0.0)).alias("_s1"))
    a = _ic(d, "_s1", (h,))
    b = _ic(d, cur, (h,))
    j = a.join(b, on="date", suffix="_b")
    return j.select("date", (pl.col(f"ic_{h}") - pl.col(f"ic_{h}_b")).alias("d"))


def greedy(
    panel: pl.DataFrame, feats: list[str], h: int, w: float, select: pl.Expr, max_k: int = 6
) -> tuple[list[dict[str, Any]], pl.DataFrame]:
    """Forward selection on the dates picked by ``select`` (a feature's sign comes from its own IC
    there): add the feature whose gain in IC at horizon ``h`` has the best t, as long as t > 2 and
    the gain is positive in both halves of the selection dates. Returns the chosen features and
    the panel with the final score in column ``s_final``."""
    cur = "s0"
    chosen: list[dict[str, Any]] = []
    left = list(feats)
    for k in range(max_k):
        sel = panel.filter(select)
        best: tuple[float, str, int] | None = None
        for f in left:
            alone = _ic(sel.with_columns(_prank(f).alias("_x")), "_x", (h,))
            sgn = 1 if np.nanmean(alone[f"ic_{h}"].to_numpy().astype(float)) >= 0 else -1
            st = _stat(_delta(sel, cur, f, sgn, w, h)["d"].to_numpy().astype(float), h)
            if (
                st["t"] is None
                or st["t"] <= 2
                or not ((st["early"] or 0) > 0 and (st["late"] or 0) > 0)
            ):
                continue
            if best is None or st["t"] > best[0]:
                best = (float(st["t"]), f, sgn)
        if best is None:
            break
        t, f, sgn = best
        nxt = f"_c{k}"
        panel = panel.with_columns((pl.col(cur) + sgn * w * _prank(f).fill_null(0.0)).alias(nxt))
        cur = nxt
        chosen.append({"feature": f, "sign": sgn, "t_when_added": t})
        left.remove(f)
    return chosen, panel.with_columns(pl.col(cur).alias("s_final"))


def gain(panel: pl.DataFrame, mask: pl.Expr) -> dict[str, Any]:
    """Change in IC of ``s_final`` over ``s0`` on the dates picked by ``mask``, per horizon."""
    d = panel.filter(mask)
    a, b = _ic(d, "s_final"), _ic(d, "s0")
    j = a.join(b, on="date", suffix="_b")
    return {str(h): _stat((j[f"ic_{h}"] - j[f"ic_{h}_b"]).to_numpy().astype(float), h) for h in HZ}


def verdict(rec: dict[str, Any]) -> dict[str, Any]:
    """Keep a feature only if, at some horizon, one sign and weight help in both halves with
    |t| > 2; the sign is the one the early half preferred."""
    best: dict[str, Any] | None = None
    for h in HZ:
        for key, per in rec["added"].items():
            st = per[str(h)]
            if st["t"] is None:
                continue
            ok = st["t"] > 2 and st["early"] > 0 and st["late"] > 0
            if ok and (best is None or st["t"] > best["t"]):
                best = {"horizon": h, "variant": key, **st}
    return {"keep": best is not None, "best": best}


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-book-study")
    ap.add_argument("--out", default=str(Path("docs/data/book-study.json")))
    args = ap.parse_args()
    df, cost, raw_paths = build(extra=list(BOARD))
    base = composite(df, sig_cols())
    book = load_book()
    p = base.join(book, on=[G, "date"], how="inner")
    p = p.with_columns(
        (
            pl.col("peak_queue_volume").abs()
            * pl.coalesce("close_bid_price", "close_ask_price")
            / pl.col("median_value_20")
        ).alias("queue_to_median"),
        (pl.col("tw_depth_value") / pl.col("median_value_20")).alias("depth_to_median"),
        (pl.col("close_imbalance") - pl.col("open_imbalance")).alias("queue_flip"),
    )
    keep_ix = p.filter(pl.col("n_events") > 50)
    # labels and the base score are ranked inside the stocks that have a book
    panel = keep_ix.with_columns(
        *[_prank(f"fwd_{h}").alias(f"y_{h}") for h in HZ],
        _prank("score").alias("s0"),
    )
    feats = [*BOARD, *BOOK, *DERIVED]
    feats = [f for f in feats if f in panel.columns]
    res = study(panel, feats)
    res["verdict"] = {f: verdict(r) for f, r in res["features"].items()}
    dates = panel["date"].unique().sort()
    mid = dates[dates.len() // 2]
    early, late = pl.col("date") < mid, pl.col("date") >= mid
    sel_res: dict[str, Any] = {"split": str(mid)}
    for h in (5, 20):
        for w in (0.1, 0.25):
            tag = f"h{h}_w{w}"
            chosen, pe = greedy(panel, feats, h, w, early)
            sel_res[f"{tag}_pick_early"] = {"chosen": chosen, "test_late": gain(pe, late)}
            chosen, pl_ = greedy(panel, feats, h, w, late)
            sel_res[f"{tag}_pick_late"] = {"chosen": chosen, "test_early": gain(pl_, early)}
            chosen, pa = greedy(panel, feats, h, w, pl.lit(True))
            sel_res[f"{tag}_all"] = {"chosen": chosen, "gain": gain(pa, pl.lit(True))}
            print(tag, [c["feature"] for c in chosen], flush=True)
            if (h, w) == (5, 0.25):
                kept_all, kept_early = pa, pe
    res["selection"] = sel_res

    # does the better score make money once queues and cost are in? (top names of ~100, so few
    # periods: indicative only)
    paths = make_paths(raw_paths)
    rng = np.random.default_rng(3)

    def run(frame: pl.DataFrame, col: str, review: int) -> dict[str, Any]:
        r = simulate_real(
            frame,
            paths,
            buy=0.1,
            hold=0.3,
            n_names=10,
            review=review,
            cost=cost,
            notional=1e9,
            locks=True,
            score=col,
        )
        return {k: v for k, v in r.items() if k != "by_year"}

    sim: dict[str, Any] = {}
    rand = kept_all.with_columns(pl.Series("rnd", rng.normal(size=kept_all.height)))
    for review in (1, 5):
        sim[f"R{review}_all_dates_base"] = run(kept_all, "s0", review)
        sim[f"R{review}_all_dates_book"] = run(kept_all, "s_final", review)
        sim[f"R{review}_all_dates_random"] = run(rand, "rnd", review)
        late_only = kept_early.filter(late)
        sim[f"R{review}_late_base"] = run(late_only, "s0", review)
        sim[f"R{review}_late_book_pick_early"] = run(late_only, "s_final", review)
    res["simulation"] = sim
    for k, v in sim.items():
        print(
            k, {x: (round(y, 3) if isinstance(y, float) else y) for x, y in v.items()}, flush=True
        )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for f, v in res["verdict"].items():
        print(f, "KEEP" if v["keep"] else "drop", v["best"])
    print("wrote", path, panel.height, "rows", res["dates"], "dates")


if __name__ == "__main__":
    main()
