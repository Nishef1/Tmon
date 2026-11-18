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

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from tmon.backtest.synthetic import make_market
from tmon.storage.models import Base, Instrument, PriceDaily

N_DAYS, N_INST = 520, 24
SOURCE = "synthetic://demo"


def main(path: str) -> None:
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)

    prices, _, _ = make_market(N_DAYS, N_INST, seed=11, edge=0.03)

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
    print("wrote", db)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo/tmon-demo.sqlite3")
