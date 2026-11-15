"""The combined zoo model through the live adapt gate (``tmon.engine.adapt.gate``), unchanged.

Run from backend/ with the live DB env; argv[1] = a scratch dir for a panel that is daily from
``ZOO_DAILY_FROM`` (the gate window is 500 trading dates, so the every-5th-day study panel is too
thin). The model is the walk-forward LightGBM of models.py (base4 + every zoo indicator, retrained
each calendar year on rows known 90 days before it). The challenger is judged against the plain
equal-weight composite of the four live signals on the same rows, with the live round-trip cost
and the engine's gate settings:

* ``latest``: the last ``window_dates`` dates with a known outcome, as the daily cycle does;
* ``rolling``: the same gate every 125 dates since 2012, to see how often it would have passed;
* each twice: with every row, and with rows whose entry day was locked limit-up left out
  (a buy at the close would not fill there).
Writes zoo_gate.json. Nothing here changes the product.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from study import build_panel  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.features.store import load_inputs  # noqa: E402
from tmon.core.engine_config import get_engine_config  # noqa: E402
from tmon.domain.rules import CostModel, RuleBook  # noqa: E402
from tmon.engine.adapt import gate  # noqa: E402

SP = Path(sys.argv[1])
C = pl.col
G = "instrument_id"
BASE = ["b_power", "b_rv20", "b_dist52", "b_mom121"]
H = (5, 20, 60)


def entry_facts() -> pl.DataFrame:
    """Per (symbol, signal day t), from the raw prices:

    * ``pos``: t's index in the market's trading calendar (for a purge in trading days);
    * ``clean``: the entry row t+1 is the very next market day (the symbol was not halted) and
      each outcome window ends within ``1.25 h + 2`` market days of the entry (no long halt
      inside the 'h days'); one flag per horizon, ``clean{h}``;
    * ``blocked``: on the entry day the last trade was at the day's upper limit (a buy queue at
      the close, so a buy at the close would usually not fill). The limit is the stored
      ``limit_up`` where known, else the day's market-wide band, read as the 99th percentile of
      high / prev_close - 1 over all symbols that day (the band changed over the years).
    * rows near bad data are not clean either: with ``ZOO_AUDIT`` = the dir of
      research/data_audit.py's output, a sample is dropped when any of its symbol's rows from
      t-20 to t+h+1 failed a hard check there (bad prices, copied days, bad adjustments, flows
      that do not add up).
    """
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
    if "limit_up" not in prices.columns:  # not loaded by load_inputs; read it from the table
        with session_scope() as s:
            lim = pl.read_database(
                "select instrument_id, date, limit_up from prices_daily where limit_up is not null",
                s.connection(),
            ).with_columns(C("date").str.slice(0, 10).str.to_date(), C("limit_up").cast(pl.Float64))
        prices = prices.join(lim, on=[G, "date"], how="left")
    p = prices.filter(~C("market_halt") & (C("close") > 0) & (C("prev_close") > 0))
    cal = p["date"].unique().sort()
    p = p.join(pl.DataFrame({"date": cal, "pos": pl.Series(range(cal.len()))}), on="date")
    last = pl.coalesce(C("last"), C("close"))
    band = (C("high") / C("prev_close") - 1).quantile(0.99).over("date")
    lim_pct = C("limit_up") / C("prev_close") - 1  # some stored limits are bad: keep 0.5%..10%
    has_lim = C("limit_up").is_not_null() & lim_pct.is_between(0.005, 0.10)
    at_top = (
        pl.when(has_lim)
        .then(last >= C("limit_up") * 0.999)
        .otherwise((last / C("prev_close") - 1 >= band - 0.002) & (band > 0.01))
    )
    p = p.sort(G, "date").with_columns(
        at_top=at_top & (last >= C("high") * 0.999) & (last > C("prev_close"))
    )
    audit = os.environ.get("ZOO_AUDIT")
    if audit:
        bad = pl.read_parquet(Path(audit) / "data_audit_rows.parquet").filter(C("bad"))
        p = p.join(bad.select(G, "date", bad_row=pl.lit(1)), on=[G, "date"], how="left")
    else:
        p = p.with_columns(bad_row=pl.lit(None, pl.Int32))
    p = p.with_columns(C("bad_row").fill_null(0).cast(pl.Int32))
    back = C("bad_row").rolling_max(21, min_samples=1).over(G) > 0  # t-20 .. t
    nxt = C("pos").shift(-1).over(G)

    def fwd_bad(h: int) -> pl.Expr:  # t .. t+h+1
        return (
            C("bad_row").rolling_max(h + 2, min_samples=1).shift(-(h + 1)).over(G).fill_null(1) > 0
        )

    cols = [
        C("at_top").shift(-1).over(G).fill_null(True).alias("blocked"),
        *[
            (
                (nxt == C("pos") + 1)
                & (C("pos").shift(-(1 + h)).over(G) - nxt <= 1.25 * h + 2)
                & ~back
                & ~fwd_bad(h)
            )
            .fill_null(False)
            .alias(f"clean{h}")
            for h in H
        ],
    ]
    return p.with_columns(cols).select(G, "date", "pos", "blocked", *[f"clean{h}" for h in H])


def daily(p: pl.DataFrame, y: str) -> pl.DataFrame:
    """Per date: IC and top-decile excess of the model (s) and of equal weights (eq)."""

    def top(col: str) -> pl.Expr:
        return C(y).filter(C(col) >= C(col).quantile(0.9)).mean()

    return (
        p.group_by("date")
        .agg(
            ic=pl.corr("s", y, method="spearman"),
            ic_eq=pl.corr("eq", y, method="spearman"),
            ex=top("s"),
            ex_eq=top("eq"),
        )
        .sort("date")
    )


def verdict(g: pl.DataFrame, h: int, cfg, cost: float) -> dict:
    a = {k: g[k].to_numpy().astype(float) for k in ("ic", "ic_eq", "ex", "ex_eq")}
    v = gate(a["ic"], a["ic_eq"], a["ex"], a["ex_eq"], h, cfg, cost)
    return {
        "from": str(g["date"][0]), "to": str(g["date"][-1]), "passed": v.passed,
        "reasons": list(v.reasons), "n": v.n, "ic": v.ic, "d_ic": v.d_ic, "t": v.t,
        "early": v.early, "late": v.late, "top": v.top_excess, "d_top": v.d_top_excess,
        "ic_eq": float(np.nanmean(a["ic_eq"])), "top_eq": float(np.nanmean(a["ex_eq"])),
    }  # fmt: skip


def main() -> None:
    cfg = get_engine_config().adapt
    d = build_panel()
    info = json.loads((SP / "zoo_panel.json").read_text())["info"]
    with session_scope() as s:
        rules = RuleBook.from_session(s)
    cost = CostModel.from_rules(
        rules, d["date"].max(), get_engine_config().costs.slippage_fraction
    ).round_trip
    print("round trip", cost, "rows", d.height, flush=True)
    d = d.join(entry_facts(), on=[G, "date"], how="inner").with_columns(tradable=~C("blocked"))
    print(
        "blocked share",
        float(d["blocked"].mean()),
        {h: float(d[f"clean{h}"].mean()) for h in H},
        flush=True,
    )
    feats = list(info) + BASE
    d = d.with_columns(*[((C(f).rank() - 0.5) / C(f).count()).over("date").alias(f) for f in feats])
    d = d.with_columns(eq=pl.mean_horizontal([C(b) for b in BASE]))
    out: dict = {"round_trip": cost, "config": cfg.model_dump(mode="json"), "h": {}}
    for h in H:
        y = f"x{h}"
        # clean rows only, and the excess re-measured against the clean rows of the same day
        dh = (
            d.filter(C(f"fwd{h}").is_not_null() & C(f"clean{h}"))
            .with_columns((C(f"fwd{h}") - C(f"fwd{h}").mean().over("date")).alias(y))
            .with_columns(ry=((C(y).rank() - 0.5) / C(y).count()).over("date"))
        )
        purge = int(np.ceil(1.25 * h)) + 3  # trading days: an outcome is known by then
        parts = []
        for yr in range(2010, int(dh["year"].max()) + 1):
            te = dh.filter(C("year") == yr)
            if te.height == 0:
                continue
            first = int(te["pos"].min())
            tr = dh.filter(C("pos") + purge < first)
            if tr.height < 20000:
                continue
            m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=31,
                                  min_child_samples=300, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, verbose=-1)  # fmt: skip
            m.fit(tr.select(feats).to_numpy(), tr["ry"].to_numpy())
            parts.append(
                te.select("date", y, "eq", "tradable").with_columns(
                    s=pl.Series(m.predict(te.select(feats).to_numpy()))
                )
            )
            print(f"h={h} {yr}", flush=True)
        p = pl.concat(parts)
        res: dict = {}
        for name, q in (("all", p), ("tradable", p.filter(C("tradable")))):
            g = daily(q, y)
            # only the daily stretch: the gate counts dates as trading days
            dense = g.filter(C("date") >= dt.date.fromisoformat(sys.argv[2]))
            res[name] = {"latest": verdict(dense.tail(cfg.window_dates), h, cfg, cost)}
            roll = []
            for end in range(cfg.window_dates, dense.height + 1, 125):
                roll.append(
                    verdict(dense.slice(end - cfg.window_dates, cfg.window_dates), h, cfg, cost)
                )
            res[name]["rolling"] = roll
            res[name]["rolling_pass"] = f"{sum(r['passed'] for r in roll)}/{len(roll)}"
            print(
                h,
                name,
                json.dumps(res[name]["latest"], ensure_ascii=False),
                res[name]["rolling_pass"],
                flush=True,
            )
        out["h"][h] = res
    (SP / "zoo_gate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
