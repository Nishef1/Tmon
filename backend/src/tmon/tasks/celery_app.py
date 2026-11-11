from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from tmon.core.config import get_settings

settings = get_settings()

app = Celery(
    "tmon", broker=settings.redis_url, backend=settings.redis_url, include=["tmon.tasks.jobs"]
)
app.conf.update(
    timezone="Asia/Tehran",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="tmon",
)

# Trading days are Saturday..Wednesday (Celery: 0=Sunday). Thursday/Friday closed.
TRADING_DOW = "sat,sun,mon,tue,wed"

app.conf.beat_schedule = {
    "ingest-instruments-daily": {
        "task": "tmon.tasks.jobs.refresh_instruments",
        "schedule": crontab(hour=7, minute=30, day_of_week=TRADING_DOW),
    },
    "ingest-eod-daily": {
        "task": "tmon.tasks.jobs.ingest_end_of_day",
        "schedule": crontab(hour=13, minute=30, day_of_week=TRADING_DOW),
    },
    "compute-features-daily": {
        "task": "tmon.tasks.jobs.compute_features",
        "schedule": crontab(hour=14, minute=0, day_of_week=TRADING_DOW),
    },
}
