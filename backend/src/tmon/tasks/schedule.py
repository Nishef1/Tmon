"""When the daily cycle is due, derived from ``market_rules`` (no hours written in code).

The cycle (EOD ingest, indices and risk-free refresh, features, publish with outcome resolution)
becomes due ``eod_delay_minutes`` after the day's last session ends. The last session is the
closing session (``closing_session_tal``) when that rule is valid on the day, else the main
``trading_hours`` close. Both come from the rule book, with their validity dates. Beat only wakes
``daily_cycle_tick`` every few minutes; this module decides whether the cycle is due and the
claim makes sure it runs once per day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from tmon.core.timeutil import TEHRAN
from tmon.domain.rules import MissingRuleError, RuleBook


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def session_close(rules: RuleBook, day: date) -> time:
    """Close of the day's last session in Tehran time."""
    main = _hhmm(rules.value("trading_hours", day)["close"])
    try:
        closing = _hhmm(rules.value("closing_session_tal", day)["close"])
    except MissingRuleError:
        return main
    return max(main, closing)


def cycle_due_at(rules: RuleBook, day: date, delay_minutes: int) -> datetime:
    """The Tehran-time moment from which the cycle of ``day`` may start."""
    close = session_close(rules, day)
    return datetime.combine(day, close, tzinfo=TEHRAN) + timedelta(minutes=delay_minutes)


def is_schedule_day(now: datetime, schedule_days: str) -> bool:
    """``now`` (any timezone) falls on one of the configured weekday names (Tehran calendar)."""
    names = {d.strip().lower()[:3] for d in schedule_days.split(",") if d.strip()}
    return now.astimezone(TEHRAN).strftime("%a").lower() in names


def cycle_decision(
    rules: RuleBook, now: datetime, *, schedule_days: str, delay_minutes: int
) -> tuple[bool, str]:
    """``(due, reason)`` for the daily cycle at ``now``."""
    if not is_schedule_day(now, schedule_days):
        return False, "not a scheduled weekday"
    local = now.astimezone(TEHRAN)
    try:
        due = cycle_due_at(rules, local.date(), delay_minutes)
    except MissingRuleError:
        return False, "no trading_hours rule valid today"
    if local < due:
        return False, f"not before {due:%H:%M} Tehran"
    return True, f"due since {due:%H:%M} Tehran"
