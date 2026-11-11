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

# Days the jobs are woken (default Saturday..Wednesday; TMON_SCHEDULE_DAYS overrides). Which days
# actually traded is derived from data into trading_calendar, not decided here.
TRADING_DOW = settings.schedule_days

app.conf.beat_schedule = {
    "ingest-instruments-daily": {
        "task": "tmon.tasks.jobs.refresh_instruments",
        "schedule": crontab(hour=7, minute=30, day_of_week=TRADING_DOW),
    },
    "snapshot-intraday": {  # the task itself checks market_rules.trading_hours
        "task": "tmon.tasks.jobs.snapshot_intraday",
        "schedule": crontab(minute="*", hour="9-12", day_of_week=TRADING_DOW),
    },
    # EOD ingest -> features -> publish -> outcome resolution. The tick only asks "is it due?": the
    # time comes from market_rules (tmon.tasks.schedule), and a claim makes it run once per day.
    "daily-cycle-tick": {
        "task": "tmon.tasks.jobs.daily_cycle_tick",
        "schedule": crontab(minute="*/5", day_of_week=TRADING_DOW),
    },
}
