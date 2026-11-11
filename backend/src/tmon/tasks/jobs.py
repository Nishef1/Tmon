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


@app.task(name="tmon.tasks.jobs.daily_cycle_tick")
def daily_cycle_tick() -> str:
    """Beat wakes this every few minutes; it runs the EOD cycle once per trading day, once the
    session close from ``market_rules`` plus ``eod_delay_minutes`` has passed."""
    import redis

    from tmon.core.config import get_settings
    from tmon.core.db import session_scope
    from tmon.domain.rules import RuleBook
    from tmon.tasks.cycle import default_steps, tick

    settings = get_settings()
    with session_scope() as session:
        rules = RuleBook.from_session(session)
    kv = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return tick(
        kv,
        rules,
        default_steps(),
        schedule_days=settings.schedule_days,
        delay_minutes=settings.eod_delay_minutes,
        max_attempts=settings.cycle_max_attempts,
    )


@app.task(name="tmon.tasks.jobs.snapshot_intraday")
def snapshot_intraday() -> dict[str, int]:
    """One live poll (no-op outside trading hours); scheduled every minute by beat."""
    from tmon.ingest.tsetmc.intraday import run_intraday

    return run_intraday(once=True)


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
    from tmon.storage.objectstore import get_object_store

    with session_scope() as session:
        res = train_and_publish(session, get_object_store(), timeframe=timeframe)
    return {
        "date": str(res.as_of),
        "model_version": res.model_version,
        "recommended": res.n_recommended,
        "message": res.message,
    }


@app.task(name="tmon.tasks.jobs.ingest_codal_events")
def ingest_codal_events() -> dict[str, int]:
    from tmon.ingest.codal.pipeline import run_events

    return run_events(max_pages=1)
