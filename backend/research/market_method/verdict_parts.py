"""Do the symbol page's other parts add to the verdict? Trend-ride state inside each verdict zone.

Report: docs/reports/verdict-parts-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/verdict_parts.py

The verdict's zones are measured as in research/market_method/horizon_profile.py: each day the
100 most liquid names without a buy queue, re-ranked by the composite; candidate = top half, avoid
= bottom 40%. Forward excess = ``fwd_h`` (next close to ``h`` days later, the verdict's own
convention) minus the day's mean of the 100. The trend ride (``backtest/trend_ride.py``, live
settings of engine.yaml) gives each symbol-day one state known at that day's close:

- ``ride``: a ride is held (bought on or before this day, not yet sold)
- ``sell_near``: held and the close is within ``warn_band`` above the sell line
- ``buy_near``: no ride and tomorrow's entry needs a rise within ``warn_band``
- ``free``: no ride, entry not near

For each zone, state and horizon: the mean over days of the state's mean excess, minus the zone's
mean excess the same day (what the state adds inside the zone), for each half of time. The t is
the daily t divided by sqrt(h), a conservative fix for overlapping windows. A state changes the
verdict only if its difference has the same sign in both halves, is larger than one round trip
at that horizon and has |t| >= 2.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.backtest.signal_decay import build_panel
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.builder import build_features
from tmon.features.store import load_inputs
from tmon.tools.v2_ranking import adjusted_close

HORIZONS = (1, 3, 5, 20, 60, 120)
SINCE = date.fromisoformat(os.environ.get("TRM_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TRM_OUT", "results_verdict_parts.json"))
G = "instrument_id"
KEYS = [G, "date"]


def ride_states(prices: pl.DataFrame, clients: pl.DataFrame) -> pl.DataFrame:
    rc = get_engine_config().v2.trend_ride
    panel = tp.build_panel(prices, clients)
    w = rc.warn_band
    rows = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        a = tr._symbol_arrays(g)
        c = a["close"]
        sig = tr.entry_signals(c, a["sma50"], a["sma200"], a["hi250"], rc.near_high)
        with np.errstate(invalid="ignore"):
            trend = tr.trending(c, a["sma50"], a["sma200"])
        rs = tr.rides(c, a["up"], a["down"], sig, rc.trail, rc.max_hold_days, trend, rc.same_day)
        trig = tr.trigger_line(c, rc.near_high)
        stop = tr.stop_line(c, rs, rc.trail, rc.max_hold_days, trend)
        held = np.zeros(len(c), dtype=bool)
        for r in rs:
            if r.entry is None:
                continue
            end = len(c) - 1 if r.exit is None else r.exit - 1
            held[r.entry : end + 1] = True
        with np.errstate(invalid="ignore", divide="ignore"):
            sell_near = held & (c / stop - 1 <= w)
            buy_near = ~held & (trig / c - 1 <= w)
        state = np.where(
            sell_near, "sell_near", np.where(held, "ride", np.where(buy_near, "buy_near", "free"))
        )
        rows.append(pl.DataFrame({G: [int(iid)] * len(c), "date": g["date"], "state": state}))
    return pl.concat(rows)


def main() -> None:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
    feats = build_features(prices, clients, rules, sectors=sectors)
    panel = build_panel(feats, adjusted_close(prices), cfg, horizons=HORIZONS)
    last = panel["date"].max()
    assert isinstance(last, date)
    rt = CostModel.from_rules(rules, last, cfg.costs.slippage_fraction).round_trip
    states = ride_states(prices, clients)
    vc = cfg.v2.verdict
    d = (
        panel.filter(pl.col("date") >= SINCE)
        .join(feats.select(*KEYS, "median_value_20"), on=KEYS, how="left")
        .filter(pl.col("median_value_20").is_not_null() & (pl.col("queue_state") != "buy_queue"))
        .with_columns(
            pl.col("median_value_20").rank("ordinal", descending=True).over("date").alias("_liq")
        )
        .filter(pl.col("_liq") <= cfg.v2.invested.profile_top_n)
        .with_columns(
            (
                (pl.col("composite").rank("average").over("date") - 0.5)
                / pl.col("composite").count().over("date")
            ).alias("_rr")
        )
        .with_columns(
            pl.when(pl.col("_rr") >= 1 - vc.candidate_top_frac)
            .then(pl.lit("candidate"))
            .when(pl.col("_rr") < vc.avoid_bottom_frac)
            .then(pl.lit("avoid"))
            .otherwise(pl.lit("middle"))
            .alias("zone")
        )
        .join(states, on=KEYS, how="left")
        .with_columns(pl.col("state").fill_null("free"))
    )
    dates = d["date"].unique().sort()
    split = dates[len(dates) // 2]
    out: dict = {
        "since": str(SINCE),
        "last": str(last),
        "split": str(split),
        "round_trip": rt,
        "zones": {},
    }
    for zone in ("candidate", "middle", "avoid", "all"):
        zd = d if zone == "all" else d.filter(pl.col("zone") == zone)
        res: dict = {}
        for h in HORIZONS:
            f = f"fwd_{h}"
            x = d.filter(pl.col(f).is_finite()).with_columns(
                (pl.col(f) - pl.col(f).mean().over("date")).alias("x")
            )
            x = x.join(zd.select(KEYS), on=KEYS, how="semi") if zone != "all" else x
            zmean = x.group_by("date").agg(pl.col("x").mean().alias("zx"))
            per = (
                x.group_by("date", "state")
                .agg(pl.col("x").mean().alias("sx"), pl.len().alias("n"))
                .join(zmean, on="date")
                .with_columns((pl.col("sx") - pl.col("zx")).alias("diff"))
                .sort("date")
            )
            hres: dict = {}
            for st in ("ride", "sell_near", "buy_near", "free"):
                p = per.filter(pl.col("state") == st)
                r: dict = {"rows": int(p["n"].sum())}
                for half, q in (
                    ("h1", p.filter(pl.col("date") < split)),
                    ("h2", p.filter(pl.col("date") >= split)),
                ):
                    if q.height == 0:
                        r[half] = None
                        continue
                    nd = q["diff"].to_numpy()
                    # overlapping h-day windows: shrink the daily t by sqrt(h) (conservative)
                    t = (
                        float(
                            nd.mean()
                            / (nd.std(ddof=1) / np.sqrt(len(nd)))
                            / np.sqrt(min(h, len(nd)))
                        )
                        if len(nd) > 2 and nd.std() > 0
                        else None
                    )
                    r[half] = {
                        "diff": float(q["diff"].mean()),
                        "excess": float(q["sx"].mean()),
                        "days": q.height,
                        "t": t,
                    }
                hres[st] = r
            res[str(h)] = hres
        out["zones"][zone] = res
        print(zone)
        for h in HORIZONS:
            line = f"  h={h:3d} "
            for st, r in res[str(h)].items():
                a, b = r["h1"] or {}, r["h2"] or {}
                line += (
                    f" {st}:{a.get('diff', np.nan):+.3f}/{b.get('diff', np.nan):+.3f}"
                    f"(t {a.get('t') or np.nan:+.1f}/{b.get('t') or np.nan:+.1f})"
                )
            print(line)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
