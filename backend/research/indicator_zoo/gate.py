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
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from checks import locked_next  # noqa: E402
from study import build_panel  # noqa: E402

from tmon.core.db import session_scope  # noqa: E402
from tmon.core.engine_config import get_engine_config  # noqa: E402
from tmon.domain.rules import CostModel, RuleBook  # noqa: E402
from tmon.engine.adapt import gate  # noqa: E402

SP = Path(sys.argv[1])
C = pl.col
BASE = ["b_power", "b_rv20", "b_dist52", "b_mom121"]
H = (5, 20, 60)


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
    d = d.join(locked_next(), on=["instrument_id", "date"], how="left").with_columns(
        tradable=~(C("lock_next").fill_null(False) & C("up_next").fill_null(False))
    )
    feats = list(info) + BASE
    d = d.with_columns(*[((C(f).rank() - 0.5) / C(f).count()).over("date").alias(f) for f in feats])
    d = d.with_columns(eq=pl.mean_horizontal([C(b) for b in BASE]))
    out: dict = {"round_trip": cost, "config": cfg.model_dump(mode="json"), "h": {}}
    for h in H:
        y = f"x{h}"
        dh = d.filter(C(y).is_not_null()).with_columns(
            ry=((C(y).rank() - 0.5) / C(y).count()).over("date")
        )
        parts = []
        for yr in range(2010, int(dh["year"].max()) + 1):
            cut = dt.date(yr, 1, 1) - dt.timedelta(days=90)
            tr, te = dh.filter(C("date") < cut), dh.filter(C("year") == yr)
            if tr.height < 20000 or te.height == 0:
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
                roll.append(verdict(dense.slice(end - cfg.window_dates, cfg.window_dates), h, cfg, cost))
            res[name]["rolling"] = roll
            res[name]["rolling_pass"] = f"{sum(r['passed'] for r in roll)}/{len(roll)}"
            print(h, name, json.dumps(res[name]["latest"], ensure_ascii=False), res[name]["rolling_pass"], flush=True)
        out["h"][h] = res
    (SP / "zoo_gate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
