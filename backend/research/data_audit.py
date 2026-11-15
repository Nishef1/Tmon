"""Audit of every daily row the models read (prices_daily, client_types_daily, the derived
adjustments), for the recommendable universe. Run from backend/ with the live DB env;
argv[1] = output dir. Writes data_audit.json (counts and examples per check) and
data_audit_rows.parquet (one row per (instrument_id, date) with the failed checks), so research
code can drop exactly those rows. It changes nothing in the database.

Checks (a row fails a check when):
  nonpos      open/high/low/close <= 0
  hilo        high < low
  open_out    open outside [low, high] (0.1% slack)
  last_out    last trade outside [low, high] (0.1% slack)
  close_out   the closing price outside [min(low, prev_close), max(high, prev_close)]: the
              Tehran closing price may sit outside the day's range when volume is below the
              base volume (it then moves only part of the way from prev_close), never beyond
  value       value / volume (the day's average price) outside [low, high] (2% slack)
  dup         the (symbol, date) appears more than once
  friday      the date is a Friday (no trading in Tehran)
  prev_gap    prev_close differs from the symbol's previous close by more than 0.5%, and the
              difference is not one of the detected adjustment events
  jump        the adjusted close-to-close move is beyond the day's limit band + 1%, outside the
              first day after a pause of 5+ market days (those may open without a limit);
              informational only: the band was wider at times, so most of these are real
  spike       a jump (as above) that comes back the next day: |r_t| beyond the band, the next
              move of the other sign, and close_{t+1} within the band of close_{t-1} (a bad tick)
  adj_up      a detected adjustment raises the price (factor > 1.02): not a dividend / rights /
              bonus issue, most likely a bad close
  adj_tiny    a detected adjustment factor below 0.05 (a 20x drop): most likely bad data
  copy        the same open/high/low/close/volume as the symbol's previous row, volume > 0
  flow_sum    individual + institutional buy (or sell) value differs from value by more than 3%
  flow_vol    individual + institutional buy (or sell) volume differs from volume by more than 3%
  flow_count  a side has value but zero buyers / sellers, or the reverse
  limit_bad   a stored limit_up outside 0.5%..10% above prev_close
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments, detect_adjustments
from tmon.features.store import load_inputs

C = pl.col
G = "instrument_id"
OUT = Path(sys.argv[1])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        lim = pl.read_database(
            "select instrument_id, date, limit_up from prices_daily where limit_up is not null",
            s.connection(),
        ).with_columns(C("date").str.slice(0, 10).str.to_date(), C("limit_up").cast(pl.Float64))
    prices = prices.join(lim, on=[G, "date"], how="left")
    events = detect_adjustments(prices)
    p = apply_adjustments(prices, events).filter(~C("market_halt")).sort(G, "date")
    cal = p.filter(C("volume") > 0)["date"].unique().sort()
    p = p.join(
        pl.DataFrame({"date": cal, "pos": pl.Series(range(cal.len()))}), on="date", how="left"
    )
    ev = events.select(G, "date", ev_f=C("adj_factor"))
    p = p.join(ev, on=[G, "date"], how="left")
    sl, sh = C("low") * 0.999, C("high") * 1.001
    r = C("adj_close") / C("adj_close").shift(1).over(G) - 1
    band = (C("high") / C("prev_close") - 1).quantile(0.99).over("date")
    prev_c = C("close").shift(1).over(G)
    same = [C(k) == C(k).shift(1).over(G) for k in ("open", "high", "low", "close", "volume")]
    p = p.with_columns(
        nonpos=pl.min_horizontal("open", "high", "low", "close") <= 0,
        hilo=C("high") < C("low"),
        open_out=(C("open") > 0) & ~C("open").is_between(sl, sh),
        last_out=C("last").is_not_null() & (C("last") > 0) & ~C("last").is_between(sl, sh),
        close_out=~C("close").is_between(
            pl.min_horizontal("low", "prev_close") * 0.999,
            pl.max_horizontal("high", "prev_close") * 1.001,
        ),
        value=(C("volume") > 0)
        & ~(C("value") / C("volume")).is_between(C("low") * 0.98, C("high") * 1.02),
        dup=pl.len().over(G, "date") > 1,
        friday=C("date").dt.weekday() == 5,
        prev_gap=(
            prev_c.is_not_null()
            & ((C("prev_close") / prev_c - 1).abs() > 0.005)
            & C("ev_f").is_null()
        ),
        jump=(
            (r.abs() > band + 0.01)
            & (C("pos") - C("pos").shift(1).over(G) < 5)
            & C("ev_f").is_null()
        ),
        spike=(
            (r.abs() > band + 0.01)
            & (r * r.shift(-1).over(G) < 0)
            & (
                (C("adj_close").shift(-1).over(G) / C("adj_close").shift(1).over(G) - 1).abs()
                < band
            )
            & C("ev_f").is_null()
        ),
        adj_up=C("ev_f") > 1.02,
        adj_tiny=C("ev_f") < 0.05,
        copy=pl.all_horizontal(same) & (C("volume") > 0),
        limit_bad=C("limit_up").is_not_null()
        & ~(C("limit_up") / C("prev_close") - 1).is_between(0.005, 0.10),
    )
    q = clients.join(p.select(G, "date", "value", "volume"), on=[G, "date"], how="inner")
    off = lambda a, b: ((a / b - 1).abs() > 0.03) & (b > 0)  # noqa: E731
    q = q.with_columns(
        flow_sum=off(C("buy_value_i") + C("buy_value_n"), C("value"))
        | off(C("sell_value_i") + C("sell_value_n"), C("value")),
        flow_vol=off(C("buy_volume_i") + C("buy_volume_n"), C("volume"))
        | off(C("sell_volume_i") + C("sell_volume_n"), C("volume")),
        flow_count=((C("buy_value_i") > 0) != (C("buy_count_i") > 0))
        | ((C("sell_value_i") > 0) != (C("sell_count_i") > 0))
        | ((C("buy_value_n") > 0) != (C("buy_count_n") > 0))
        | ((C("sell_value_n") > 0) != (C("sell_count_n") > 0)),
    ).select(G, "date", "flow_sum", "flow_vol", "flow_count")
    checks_p = [
        "nonpos",
        "hilo",
        "open_out",
        "last_out",
        "close_out",
        "value",
        "dup",
        "friday",
        "prev_gap",
        "jump",
        "spike",
        "adj_up",
        "adj_tiny",
        "copy",
        "limit_bad",
    ]
    checks_f = ["flow_sum", "flow_vol", "flow_count"]
    rows = (
        p.select(G, "date", *checks_p)
        .join(q, on=[G, "date"], how="left")
        .with_columns(*[C(k).fill_null(False) for k in checks_p + checks_f])
    )
    # 'bad' = rows research should not trust; jump and limit_bad are informational only
    hard = [k for k in checks_p + checks_f if k not in ("jump", "limit_bad")]
    rows = rows.with_columns(bad=pl.any_horizontal(hard))
    report: dict = {"rows": rows.height, "symbols": rows[G].n_unique(), "checks": {}}
    for k in checks_p + checks_f:
        hit = rows.filter(C(k))
        top = hit.group_by(G).len().sort("len", descending=True).head(8)
        report["checks"][k] = {
            "rows": hit.height,
            "share": hit.height / rows.height,
            "symbols": hit[G].n_unique(),
            "by_year": {
                str(y): n
                for y, n in hit.group_by(C("date").dt.year()).len().sort("date").iter_rows()
            },
            "top_symbols": dict(top.iter_rows()),
            "examples": [[i, str(d)] for i, d in hit.select(G, "date").head(5).iter_rows()],
        }
        print(f"{k:11s} {hit.height:8d} rows  {hit[G].n_unique():5d} symbols", flush=True)
    report["bad_rows"] = int(rows["bad"].sum())
    print("rows", rows.height, "bad", report["bad_rows"])
    report["hard_checks"] = hard
    rows.filter(C("bad")).write_parquet(OUT / "data_audit_rows.parquet")
    (OUT / "data_audit.json").write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
