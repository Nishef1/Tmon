"""Build a local SQLite demo database from the SYNTHETIC market, without Docker.

Everything in it is generated: symbols are called "نمونه N", prices are a random walk with a
planted edge, and nothing here describes the real market. It exists so the UI can be viewed
end to end (API -> pages) before real TSETMC data is available.

    python scripts/demo_db.py [path/to/demo.sqlite3]

Then:  TMON_DATABASE_URL=sqlite:///path/to/demo.sqlite3 uvicorn tmon.api.main:app --port 8000
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import polars as pl
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from tmon.backtest.synthetic import make_market
from tmon.core.engine_config import get_engine_config
from tmon.engine.service import train_and_publish
from tmon.storage.models import Base, Instrument, PriceDaily
from tmon.storage.objectstore import MemoryStore
from tmon.storage.seed import seed_rulebook

N_DAYS, N_INST, PUBLISH_DAYS = 520, 24, 6
SOURCE = "synthetic://demo"


def main(path: str) -> None:
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)

    prices, clients, sectors = make_market(N_DAYS, N_INST, seed=11, edge=0.03)
    rules = seed_rulebook()
    cfg = get_engine_config()
    # Thresholds from the document would (correctly) publish nothing on synthetic data; they are
    # loosened here ONLY so the demo shows what a recommendation card looks like.
    demo_cfg = cfg.model_copy(
        update={
            "thresholds": cfg.thresholds.model_copy(
                update={
                    "margin": -1.0,
                    "p_floor": 0.15,
                    "ev_min_abs": 0.0,
                    "min_bucket_samples": 20,
                }
            )
        }
    )

    now = dt.datetime.now(dt.UTC)
    with Session(engine) as s:
        s.add_all(
            Instrument(
                id=i,
                ins_code=f"SYN{i:03d}",
                symbol_fa=f"نمونه {i}",
                name_fa=f"نماد مصنوعی شمارهٔ {i}",
                sector_code=f"s{i % 5}",
                instrument_type="stock",
                source_url=SOURCE,
                fetched_at=now,
            )
            for i in range(1, N_INST + 1)
        )
        s.flush()
        rows = prices.select(
            "instrument_id", "date", "open", "high", "low", "close", "last", "prev_close",
            "volume", "value", "base_volume", "market_halt",
        ).to_dicts()  # fmt: skip
        for r in rows:
            r["source_url"], r["fetched_at"] = SOURCE, now
        s.execute(insert(PriceDaily), rows)
        s.commit()

        dates = prices["date"].unique().sort().to_list()
        for d in dates[-PUBLISH_DAYS:]:  # one run per past day so history has something to show

            def upto(df: pl.DataFrame, d: dt.date = d) -> pl.DataFrame:
                return df.filter(pl.col("date") <= d)

            res = train_and_publish(
                s,
                MemoryStore(),
                inputs=(upto(prices), upto(clients), sectors),
                rules=rules,
                cfg=demo_cfg,
            )
            s.commit()
            print(d, "recommended:", res.n_recommended)
    print("wrote", db)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo/tmon-demo.sqlite3")
