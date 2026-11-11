"""Celery tasks. Bodies delegate to plain functions so they stay unit-testable."""

from __future__ import annotations

import logging

from tmon.tasks.celery_app import app

log = logging.getLogger(__name__)


@app.task(name="tmon.tasks.jobs.ping")
def ping() -> str:
    return "pong"


@app.task(name="tmon.tasks.jobs.refresh_instruments")
def refresh_instruments() -> int:
    from tmon.ingest.tsetmc.pipeline import refresh_instrument_list

    return refresh_instrument_list()


@app.task(name="tmon.tasks.jobs.ingest_end_of_day")
def ingest_end_of_day() -> dict[str, int]:
    from tmon.ingest.tsetmc.pipeline import ingest_end_of_day as run

    return run()


@app.task(name="tmon.tasks.jobs.compute_features")
def compute_features(timeframe: str = "D1") -> int:
    from tmon.core.db import session_scope
    from tmon.features.store import refresh_features

    with session_scope() as session:
        return refresh_features(session, timeframe)


@app.task(name="tmon.tasks.jobs.publish_signals")
def publish_signals(timeframe: str = "D1") -> dict[str, object]:
    """Train on resolved labels, run the gate and publish the day's signals (or the note that
    there are none)."""
    from tmon.core.db import session_scope
    from tmon.engine.service import train_and_publish
    from tmon.storage.objectstore import MinioStore

    with session_scope() as session:
        res = train_and_publish(session, MinioStore(), timeframe=timeframe)
    return {
        "date": str(res.as_of),
        "model_version": res.model_version,
        "recommended": res.n_recommended,
        "message": res.message,
    }
