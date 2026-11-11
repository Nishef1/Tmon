"""The daily cycle: EOD ingest -> index and risk-free refresh -> features -> publish (which also
resolves the outcomes of earlier signals).

``daily_cycle_tick`` (every few minutes from beat) calls :func:`tick`: if the cycle of today is due
(``tmon.tasks.schedule``) and nobody has claimed it, it claims it in Redis and runs it. A claim is
a lock while it runs, a ``done`` mark when it succeeded, and an attempt counter so a failing cycle
is retried by the next ticks but not forever. Every step logs ``cycle day=... step=... status=...``
so one cycle can be followed in the worker log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from tmon.core.timeutil import TEHRAN, utcnow
from tmon.domain.rules import RuleBook
from tmon.tasks.schedule import cycle_decision

log = logging.getLogger(__name__)

KEY_TTL_SECONDS = 4 * 86400
LOCK_TTL_SECONDS = 3 * 3600


class KeyValue(Protocol):
    """The few Redis calls the claim needs (a fake implements them in tests)."""

    def set(self, name: str, value: str, *, nx: bool = ..., ex: int | None = ...) -> Any: ...
    def exists(self, name: str) -> Any: ...
    def incr(self, name: str) -> Any: ...
    def expire(self, name: str, time: int) -> Any: ...
    def delete(self, name: str) -> Any: ...


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[], Any]
    required: bool = True


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str


class CycleFailedError(RuntimeError):
    """A required step of the cycle failed; the claim is released so a later tick can retry."""


def run_cycle(day: date, steps: Sequence[Step]) -> list[StepResult]:
    """Run the steps in order. A failing optional step is logged and skipped; a failing required
    step stops the cycle with :class:`CycleFailedError`."""
    results: list[StepResult] = []
    for step in steps:
        log.info("cycle day=%s step=%s status=start", day, step.name)
        t0 = time.monotonic()
        try:
            out = step.run()
        except Exception as exc:
            secs = time.monotonic() - t0
            results.append(StepResult(step.name, False, secs, repr(exc)))
            log.exception("cycle day=%s step=%s status=failed seconds=%.1f", day, step.name, secs)
            if step.required:
                raise CycleFailedError(f"{step.name}: {exc!r}") from exc
            continue
        secs = time.monotonic() - t0
        results.append(StepResult(step.name, True, secs, str(out)[:300]))
        log.info("cycle day=%s step=%s status=ok seconds=%.1f result=%s", day, step.name, secs, out)
    return results


def default_steps(timeframes: Sequence[str] | None = None) -> list[Step]:
    """The production steps (imports are lazy: they pull in the whole backend).

    One publish step per timeframe in ``engine.yaml: publish_timeframes``. The first (D1) is
    required; later ones are optional so a weaker horizon never blocks the main product.
    """
    if timeframes is None:
        from tmon.core.engine_config import get_engine_config

        timeframes = get_engine_config().publish_timeframes

    def ingest() -> Any:
        from tmon.ingest.tsetmc.pipeline import ingest_end_of_day

        return ingest_end_of_day()

    def indices() -> Any:
        from tmon.ingest.tsetmc.pipeline import run_indices

        return run_indices()

    def risk_free() -> Any:
        from tmon.ingest.tsetmc.pipeline import run_risk_free

        return run_risk_free()

    def macro() -> Any:
        from tmon.ingest.macro.pipeline import run_macro

        return run_macro()

    def news() -> Any:
        from tmon.ingest.news.pipeline import run_news

        return run_news()

    def features() -> Any:
        from tmon.core.db import session_scope
        from tmon.features.store import refresh_features

        with session_scope() as session:
            return refresh_features(session, timeframes[0])

    def publisher(timeframe: str) -> Callable[[], Any]:
        def publish() -> Any:
            from tmon.core.db import session_scope
            from tmon.engine.service import train_and_publish
            from tmon.storage.objectstore import get_object_store

            with session_scope() as session:
                res = train_and_publish(session, get_object_store(), timeframe=timeframe)
            return {
                "timeframe": timeframe,
                "date": str(res.as_of),
                "model_version": res.model_version,
                "recommended": res.n_recommended,
                "message": res.message,
            }

        return publish

    return [
        Step("ingest_eod", ingest),
        Step("indices", indices, required=False),
        Step("risk_free", risk_free, required=False),
        Step("macro", macro, required=False),
        Step("news", news, required=False),
        Step("features", features),
        *(
            Step(f"publish_and_resolve_outcomes_{tf}", publisher(tf), required=(i == 0))
            for i, tf in enumerate(timeframes)
        ),
    ]


def claim(kv: KeyValue, day: date, max_attempts: int) -> str:
    """``"claimed"``, or why not: ``"done"``, ``"running"`` or ``"gave_up"``."""
    base = f"tmon:cycle:{day}"
    if kv.exists(f"{base}:done"):
        return "done"
    if not kv.set(f"{base}:lock", "1", nx=True, ex=LOCK_TTL_SECONDS):
        return "running"
    attempts = int(kv.incr(f"{base}:attempts"))
    kv.expire(f"{base}:attempts", KEY_TTL_SECONDS)
    if attempts > max_attempts:
        kv.delete(f"{base}:lock")
        return "gave_up"
    return "claimed"


def finish(kv: KeyValue, day: date, *, ok: bool) -> None:
    base = f"tmon:cycle:{day}"
    if ok:
        kv.set(f"{base}:done", "1", ex=KEY_TTL_SECONDS)
    kv.delete(f"{base}:lock")


def tick(
    kv: KeyValue,
    rules: RuleBook,
    steps: Sequence[Step],
    *,
    now: datetime | None = None,
    schedule_days: str,
    delay_minutes: int,
    max_attempts: int,
) -> str:
    """One beat tick. Returns a short status string (also the task result)."""
    now = now or utcnow()
    due, why = cycle_decision(rules, now, schedule_days=schedule_days, delay_minutes=delay_minutes)
    if not due:
        return f"skip: {why}"
    day = now.astimezone(TEHRAN).date()
    got = claim(kv, day, max_attempts)
    if got != "claimed":
        return f"skip: {got}"
    log.info("cycle day=%s status=begin (%s)", day, why)
    try:
        run_cycle(day, steps)
    except CycleFailedError as exc:
        finish(kv, day, ok=False)
        log.error("cycle day=%s status=failed: %s", day, exc)
        return f"failed: {exc}"
    finish(kv, day, ok=True)
    log.info("cycle day=%s status=complete", day)
    return "complete"
