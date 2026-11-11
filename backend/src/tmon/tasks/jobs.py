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
