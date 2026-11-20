"""How complete the stored market data is, stated in numbers, and the one place gaps are noted.

A day is *partial* when the rows it holds are far fewer than the days around it (the real case:
23 Aban 1405 had 1212 price rows while the days before held about 2100-2400, because the fetch ran
while TSETMC was still publishing). Nothing here guesses at missing values; it only counts.

The note (``data-health/gaps.json`` in the artifact store) keeps every gap with the date it was
first seen, so a gap that stays open across cycles stays visible until a refill closes it.
``python -m tmon.tools.data_health refill`` is the job behind the site's refill button: it
re-downloads what this machine can reach, says what it cannot, and rewrites the note.
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.timeutil import to_tehran, utcnow
from tmon.ingest.tsetmc.classify import get_classifier
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily
from tmon.storage.objectstore import ObjectStore, get_object_store

log = logging.getLogger(__name__)

WINDOW_DAYS = 30  # newest market days that are checked
REFERENCE_DAYS = 15  # older days a day is compared with
MIN_RATIO = 0.9  # a day below this share of its reference is partial
STALE_RUN_MINUTES = 45  # a "running" refill older than this is a dead one
NOTE_KEY = "data-health/gaps.json"
REFILL_KEY = "data-health/refill.json"
CYCLE_KEY = "data-health/cycle.json"
TIMINGS_KEY = "data-health/cycle-timings.json"
TIMINGS_KEEP = 30  # cycles kept in the timing record
CYCLE_MAX_HOURS = 4  # a cycle marker older than this is a crashed one
# Iran trades Saturday..Wednesday (Python: Monday=0).
TRADING_WEEKDAYS = {5, 6, 0, 1, 2}
CLOSE_HOUR = 18  # Tehran hour after which today's prices should have been published


@dataclass(frozen=True)
class Issue:
    kind: str  # prices_partial | flows_partial | today_pending
    date: date
    have: int | None = None
    expected: int | None = None


@dataclass(frozen=True)
class Day:
    date: date
    prices: int
    flows: int
    price_ref: int | None
    flow_ref: int | None
    prices_ok: bool
    flows_ok: bool


def _window_start(session: Session) -> date | None:
    """First day of the checked window, as a plain date. Inline as a subquery it is evaluated
    again for every row scanned (seconds), so it is read once."""
    newest = session.scalar(select(func.max(PriceDaily.date)))
    return None if newest is None else newest - timedelta(days=WINDOW_DAYS + REFERENCE_DAYS * 2)


def _counts(session: Session, model: Any, *, traded_only: bool = False) -> dict[date, int]:
    """Rows per day for the instruments the daily run fetches (stocks and funds). Options, rights
    and bonds are left out of the count: older days that were loaded market-wide hold them, newer
    ones do not, and comparing the two would flag every normal day as partial."""
    kinds = [t.value for t in get_classifier().tradable]
    q = select(model.date, func.count()).join(Instrument, Instrument.id == model.instrument_id)
    q = q.where(Instrument.instrument_type.in_(kinds))
    if traded_only:
        q = q.where(model.volume > 0)
    q = q.where(model.date >= _window_start(session)).group_by(model.date)
    return dict(session.execute(q).all())


_counts_cache: dict[
    tuple[object, ...], tuple[dict[date, int], dict[date, int], dict[date, int]]
] = {}
_counts_lock = threading.Lock()


def _window_fingerprint(session: Session) -> tuple[object, ...]:
    """What the three day-counts are made from: rows of the checked window (a new, removed or
    refetched row moves the count, the newest fetch time or the sum) and the symbol table. Far
    cheaper than the counts themselves, which join every row to its symbol."""
    start = _window_start(session)
    prices = session.execute(
        select(func.count(), func.max(PriceDaily.fetched_at), func.sum(PriceDaily.volume)).where(
            PriceDaily.date >= start
        )
    ).one()
    flows = session.execute(
        select(
            func.count(),
            func.max(ClientTypeDaily.fetched_at),
            func.sum(ClientTypeDaily.buy_value_i),
        ).where(ClientTypeDaily.date >= start)
    ).one()
    insts = session.scalar(select(func.count()).select_from(Instrument))
    return (*tuple(prices), *tuple(flows), insts)


def _all_counts(
    session: Session,
) -> tuple[dict[date, int], dict[date, int], dict[date, int]]:
    """Traded prices, all prices and flows per day, kept while the rows behind them are unchanged
    (a fingerprint of the data, never a clock); one request builds them, the others wait."""
    key = _window_fingerprint(session)
    with _counts_lock:
        hit = _counts_cache.get(key)
        if hit is not None:
            return hit
        out = (
            _counts(session, PriceDaily, traded_only=True),
            _counts(session, PriceDaily),
            _counts(session, ClientTypeDaily),
        )
        _counts_cache.clear()  # only the latest state is ever asked for
        _counts_cache[key] = out
        return out


def _ref(counts: dict[date, int], d: date, days: list[date]) -> int | None:
    older = [counts.get(x, 0) for x in days if x < d][-REFERENCE_DAYS:]
    return int(statistics.median(older)) if len(older) >= 5 else None


def tehran_now(now: datetime | None = None) -> datetime:
    return to_tehran(now or utcnow())


def check(session: Session, now: datetime | None = None) -> dict[str, Any]:
    """The numbers: per-day counts, the days that fall short, and whether today's prices are
    still missing."""
    traded, rows, flows = _all_counts(session)
    all_days = sorted(rows)
    days: list[Day] = []
    for d in all_days[-WINDOW_DAYS:]:
        # flows are kept only for symbols that traded, so they are compared with traded prices
        p_ref, f_ref = _ref(rows, d, all_days), _ref(flows, d, all_days)
        days.append(
            Day(
                date=d,
                prices=rows[d],
                flows=flows.get(d, 0),
                price_ref=p_ref,
                flow_ref=f_ref,
                prices_ok=p_ref is None or rows[d] >= MIN_RATIO * p_ref,
                flows_ok=f_ref is None or flows.get(d, 0) >= MIN_RATIO * f_ref,
            )
        )
    issues: list[Issue] = []
    for x in days:
        if not x.prices_ok:
            issues.append(Issue("prices_partial", x.date, x.prices, x.price_ref))
        if not x.flows_ok:
            issues.append(Issue("flows_partial", x.date, x.flows, x.flow_ref))
    t = tehran_now(now)
    newest = all_days[-1] if all_days else None
    if (
        newest is not None
        and t.weekday() in TRADING_WEEKDAYS
        and t.hour >= CLOSE_HOUR
        and newest < t.date()
    ):
        issues.append(Issue("today_pending", t.date()))
    return {
        "checked_at": utcnow(),
        "newest": newest,
        "days": days,
        "issues": issues,
        "traded_rows_newest": traded.get(newest) if newest else None,
    }


# --------------------------------------------------------------------------- #
# The note
# --------------------------------------------------------------------------- #


def _bucket() -> str:
    return get_settings().minio_artifact_bucket


def _read(store: ObjectStore, key: str) -> dict[str, Any] | None:
    try:
        return json.loads(store.get(_bucket(), key))  # type: ignore[no-any-return]
    except Exception:  # missing object or damaged file: there is simply no note yet
        return None


def _write(store: ObjectStore, key: str, doc: dict[str, Any]) -> None:
    store.put(
        _bucket(),
        key,
        json.dumps(doc, ensure_ascii=False, default=str).encode(),
        "application/json",
    )


def read_note(store: ObjectStore | None = None) -> dict[str, Any] | None:
    return _read(store or get_object_store(), NOTE_KEY)


def record(
    session: Session, store: ObjectStore | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Check the data and update the note: new gaps get a ``first_seen``, gaps that are no longer
    found are marked closed with the day they were seen healed."""
    store = store or get_object_store()
    found = check(session, now)
    today = tehran_now(now).date().isoformat()
    old = {(g["kind"], g["date"]): g for g in (_read(store, NOTE_KEY) or {}).get("gaps", [])}
    gaps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for i in found["issues"]:
        k = (i.kind, i.date.isoformat())
        seen.add(k)
        prev = old.get(k)
        gaps.append(
            {
                **{a: str(b) if isinstance(b, date) else b for a, b in asdict(i).items()},
                "first_seen": (prev or {}).get("first_seen", today),
                "last_seen": today,
                "closed_on": None,
            }
        )
    for k, g in old.items():
        if k not in seen:
            gaps.append({**g, "closed_on": g.get("closed_on") or today})
    gaps = gaps[-200:]
    doc = {"updated_at": utcnow().isoformat(), "gaps": gaps}
    _write(store, NOTE_KEY, doc)
    return doc


# --------------------------------------------------------------------------- #
# Refill job
# --------------------------------------------------------------------------- #

SOURCES: dict[str, tuple[str, Callable[[], str]]] = {
    "history": ("old.tsetmc.com", lambda: get_settings().tsetmc_old_url),
    "instruments": ("service.tsetmc.com", lambda: "https://service.tsetmc.com"),
    "cdn": ("cdn.tsetmc.com", lambda: get_settings().tsetmc_cdn_url),
}


def reachable(url: str, timeout: float = 8.0) -> bool:
    """Any HTTP answer counts; only a refused or timed-out connection means 'cannot reach'."""
    try:
        httpx.get(url, timeout=timeout, follow_redirects=True)
        return True
    except httpx.HTTPError:
        return False


def sources_here() -> dict[str, bool]:
    return {name: reachable(url()) for name, (_, url) in SOURCES.items()}


def refill_state(
    store: ObjectStore | None = None, now: datetime | None = None
) -> dict[str, Any] | None:
    doc = _read(store or get_object_store(), REFILL_KEY)
    if doc and doc.get("state") == "running":
        started = datetime.fromisoformat(doc["started_at"])
        if (now or utcnow()) - started > timedelta(minutes=STALE_RUN_MINUTES):
            doc = {**doc, "state": "failed", "message": "کار نیمه‌کاره ماند و متوقف شد."}
    return doc


def _set(store: ObjectStore, doc: dict[str, Any]) -> None:
    _write(store, REFILL_KEY, doc)


def mark_cycle(running: bool, store: ObjectStore | None = None) -> None:
    """The daily cycle writes the same tables; a refill started while it runs would fight it for
    the database, so the cycle leaves a marker for the length of its run."""
    try:
        _write(
            store or get_object_store(),
            CYCLE_KEY,
            {"running": running, "at": utcnow().isoformat()},
        )
    except Exception:  # the marker is a courtesy; it must never stop the cycle
        log.warning("could not write the cycle marker", exc_info=True)


def record_timings(
    day: date,
    steps: list[dict[str, Any]],
    *,
    ok: bool,
    full: bool,
    started_at: datetime,
    store: ObjectStore | None = None,
) -> None:
    """Keep how long every step of a cycle took (newest first, the last ``TIMINGS_KEEP`` cycles),
    so a slow night can be compared with the usual one. A courtesy like the marker: it never
    raises. ``steps`` are ``{name, ok, seconds, detail}`` of the steps that finished."""
    try:
        st = store or get_object_store()
        old = (_read(st, TIMINGS_KEY) or {}).get("cycles", [])
        entry = {
            "day": day.isoformat(),
            "started_at": started_at.isoformat(),
            "finished_at": utcnow().isoformat(),
            "ok": ok,
            "eod_mode": "full" if full else "fast",
            "total_seconds": round(sum(float(s["seconds"]) for s in steps), 1),
            "steps": [
                {
                    "name": s["name"],
                    "ok": s["ok"],
                    "seconds": round(float(s["seconds"]), 1),
                    "detail": str(s.get("detail", ""))[:200],
                }
                for s in steps
            ],
        }
        kept = [c for c in old if c.get("day") != entry["day"]]
        _write(st, TIMINGS_KEY, {"cycles": [entry, *kept][:TIMINGS_KEEP]})
    except Exception:
        log.warning("could not write the cycle timings", exc_info=True)


def read_timings(store: ObjectStore | None = None) -> list[dict[str, Any]]:
    return (_read(store or get_object_store(), TIMINGS_KEY) or {}).get("cycles", [])  # type: ignore[no-any-return]


def cycle_running(store: ObjectStore | None = None, now: datetime | None = None) -> bool:
    doc = _read(store or get_object_store(), CYCLE_KEY)
    if not doc or not doc.get("running"):
        return False
    return (now or utcnow()) - datetime.fromisoformat(doc["at"]) < timedelta(hours=CYCLE_MAX_HOURS)


BLOCKED = {
    "state": "blocked",
    "steps": [],
    "message": (
        "دورهٔ روزانهٔ دریافت داده هم‌اکنون در حال اجراست و همین کار را انجام می‌دهد؛ "
        "بعد از پایان آن دوباره بزنید."
    ),
}


def run_refill(
    store: ObjectStore | None = None,
    steps: dict[str, Callable[[], Any]] | None = None,
    here: Callable[[], dict[str, bool]] = sources_here,
) -> dict[str, Any]:
    """Re-download what this machine can reach, then re-check and rewrite the note.

    The steps are those of the daily cycle that fill the raw tables. They need old.tsetmc.com and
    service.tsetmc.com (history, instrument list); a machine that cannot reach them skips them and
    says so, instead of waiting out thousands of timeouts."""
    from tmon.core.db import session_scope

    store = store or get_object_store()
    started = utcnow()
    base = {"started_at": started.isoformat()}
    if cycle_running(store):
        _set(store, {**base, **BLOCKED})
        return {**base, **BLOCKED}
    _set(store, {**base, "state": "running", "steps": [], "message": "در حال بررسی منبع‌ها…"})
    if steps is None:
        from tmon.ingest.tsetmc.pipeline import ingest_end_of_day, run_indices

        steps = {"history": ingest_end_of_day, "indices": run_indices}
    ok = here()
    can_history = ok.get("history", False) and ok.get("instruments", False)
    out: list[dict[str, Any]] = []
    for name, fn in steps.items():
        needs = name == "history"
        if needs and not can_history:
            out.append(
                {
                    "name": name,
                    "status": "skipped",
                    "detail": (
                        "این کامپیوتر به old.tsetmc.com و service.tsetmc.com "
                        "دسترسی ندارد؛ این بخش باید روی کامپیوتر اصلی اجرا شود."
                    ),
                }
            )
            continue
        if name == "indices" and not ok.get("cdn", False):
            out.append(
                {"name": name, "status": "skipped", "detail": "cdn.tsetmc.com در دسترس نیست."}
            )
            continue
        _set(store, {**base, "state": "running", "steps": out, "message": f"در حال اجرا: {name}"})
        try:
            out.append({"name": name, "status": "ok", "detail": str(fn())[:300]})
        except Exception as exc:  # one failing source must not stop the others
            log.exception("refill step %s failed", name)
            out.append(
                {"name": name, "status": "failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}
            )
    with session_scope() as session:
        doc = record(session, store)
        after = check(session)
    open_gaps = [g for g in doc["gaps"] if g["closed_on"] is None]
    state = "done" if not any(s["status"] == "failed" for s in out) else "failed"
    result = {
        **base,
        "finished_at": utcnow().isoformat(),
        "state": state,
        "steps": out,
        "open_gaps": len(open_gaps),
        "newest": str(after["newest"]) if after["newest"] else None,
        "message": "تمام شد." if not open_gaps else f"{len(open_gaps)} خلأ هنوز باز است.",
    }
    _set(store, result)
    return result


def start_in_background() -> None:
    """Launch the refill as its own process so the API stays responsive (and the job outlives a
    restart of it)."""
    import subprocess

    _set(
        get_object_store(),
        {
            "started_at": utcnow().isoformat(),
            "state": "running",
            "steps": [],
            "message": "شروع شد…",
        },
    )
    flags = 0
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "tmon.tools.data_health", "refill"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def main() -> None:
    from tmon.core.logging import configure_logging

    configure_logging()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "refill":
        print(json.dumps(run_refill(), ensure_ascii=False, indent=2))
    elif cmd == "timings":
        for c in read_timings():
            slow = max(c["steps"], key=lambda s: s["seconds"], default=None)
            print(
                f"{c['day']} {c['eod_mode']:4} {'ok ' if c['ok'] else 'ERR'} "
                f"{c['total_seconds'] / 60:6.1f} min"
                + (f"  slowest: {slow['name']} {slow['seconds'] / 60:.1f} min" if slow else "")
            )
    elif cmd == "note":
        from tmon.core.db import session_scope

        with session_scope() as session:
            print(json.dumps(record(session), ensure_ascii=False, indent=2))
    else:
        from tmon.core.db import session_scope

        with session_scope() as session:
            r = check(session)
        for i in r["issues"]:
            print(i)
        print(f"{len(r['issues'])} issue(s); newest price day {r['newest']}")


if __name__ == "__main__":
    main()
