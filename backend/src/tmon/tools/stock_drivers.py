"""Stock-drivers document for the symbol page (``tmon.backtest.drivers``).

``python -m tmon.tools.stock_drivers`` writes one JSON document (object store key
``v2/drivers.json``): the dated shocks and, per stock, its ties to the index, the dollar, copper
and Brent, its price in dollars against its own history, its last cash dividend and its moves
after each shock. The API turns the stock's part into plain sentences.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import polars as pl
from sqlalchemy import select

from tmon.backtest import drivers as dv
from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs
from tmon.storage.models import MacroSeries, MarketIndexDaily, PriceAdjustment
from tmon.storage.objectstore import get_object_store

KEY = "v2/drivers.json"
C = pl.col


def build_document() -> dict[str, Any]:
    code = get_engine_config().benchmarks.indices["tedpix"]
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
        index = pl.DataFrame(
            s.execute(
                select(MarketIndexDaily.date, MarketIndexDaily.close).where(
                    MarketIndexDaily.index_code == code
                )
            ).all(),
            schema={"date": pl.Date, "close": pl.Float64},
            orient="row",
        )
        macro = pl.DataFrame(
            s.execute(
                select(MacroSeries.series, MacroSeries.ref_period, MacroSeries.value).where(
                    MacroSeries.series.in_(("usd_free", "copper_usd", "brent_usd"))
                )
            ).all(),
            schema={"series": pl.Utf8, "date": pl.Date, "value": pl.Float64},
            orient="row",
        )
        adj = pl.DataFrame(
            s.execute(
                select(
                    PriceAdjustment.instrument_id,
                    PriceAdjustment.date,
                    PriceAdjustment.close_before,
                    PriceAdjustment.price_after,
                    PriceAdjustment.adj_factor,
                )
            ).all(),
            schema={
                "instrument_id": pl.Int64,
                "date": pl.Date,
                "close_before": pl.Float64,
                "price_after": pl.Float64,
                "adj_factor": pl.Float64,
            },
            orient="row",
        )
    p = apply_adjustments(prices).filter(~C("market_halt") & (C("close") > 0))
    closes = p.select(dv.G, "date", close=C("adj_close")).drop_nulls()
    as_of = closes["date"].max()
    lv = dv.outside_levels(index, macro)
    events = dv.read_events()
    sens = dv.sensitivities(closes, lv, as_of)  # type: ignore[arg-type]
    usd = dv.usd_position(closes, lv, as_of)  # type: ignore[arg-type]
    div = dv.dividends(adj.filter(C(dv.G).is_in(closes[dv.G].unique().implode())))
    moves = dv.event_moves(closes, index, events)
    ids = set(sens) | set(usd) | set(div) | set(moves)
    return {
        "as_of": str(as_of),
        "window_weeks": dv.WINDOW_WEEKS,
        "event_days": dv.EVENT_DAYS,
        "events": events,
        "market_bad": dv.market_after_bad(index, macro, events),
        "symbols": {
            str(i): {
                **sens.get(i, {}),
                **usd.get(i, {}),
                **div.get(i, {}),
                "moves": moves.get(i, []),
            }
            for i in sorted(ids)
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-stock-drivers")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    if a.out:
        with open(a.out, "wb") as f:
            f.write(data)
    sy = doc["symbols"]
    n_sens = sum(1 for v in sy.values() if "beta_index" in v)
    n_usd = sum(1 for v in sy.values() if "usd_pctl" in v)
    print(f"as_of={doc['as_of']} symbols={len(sy)} with_betas={n_sens} with_usd={n_usd}")


if __name__ == "__main__":
    main()
