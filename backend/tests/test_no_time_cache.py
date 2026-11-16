"""No time-based caching anywhere: data is fresh or it says how old it is.

Owner rule: a page may never show data that is stale by even a second because a cache said it
was still good. Freshness is judged by data version or fingerprint, never by a clock. This test
bans the time-based cache tools outright, requires ``cache: "no-store"`` on every server-side
fetch in the web app, and freezes the short list of process-lifetime memoizations (settings,
the DB engine, config, a text normalizer, a classifier, a fixed random null) so a new
``@lru_cache`` around data cannot slip in.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "src" / "tmon"
FRONTEND_DIRS = [ROOT / "frontend" / d for d in ("app", "lib", "components")]

BANNED = re.compile(
    r"TTLCache|cachetools|expire_after|staleTime|s-maxage|stale-while-revalidate"
    r"|max-age=[1-9]|revalidate\s*[:=]\s*[1-9]|next:\s*\{\s*revalidate"
)
MEMO = re.compile(r"^\s*@(?:functools\.)?(?:lru_cache|cache)\b", re.MULTILINE)

# file (relative to tmon/) -> number of memoized functions. Each is a constant for the life of
# the process, not data. Add here only with the same guarantee.
MEMO_ALLOWED = {
    "core/config.py": 1,  # settings from the environment
    "core/db.py": 2,  # SQLAlchemy engine and session factory
    "core/engine_config.py": 1,  # config/engine.yaml; a release restarts the services
    "ingest/news/text.py": 1,  # hazm normalizer object
    "ingest/tsetmc/classify.py": 1,  # instrument_types.yaml classifier
    "portfolio/timing.py": 1,  # random-walk null with a fixed seed
}


def _sources() -> list[Path]:
    files = list(BACKEND.rglob("*.py"))
    for d in FRONTEND_DIRS:
        files += [p for p in d.rglob("*") if p.suffix in {".ts", ".tsx"}]
    return [p for p in files if "node_modules" not in p.parts]


def test_no_time_based_cache() -> None:
    hits = []
    for f in _sources():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if BANNED.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not hits, "time-based caching is not allowed:\n" + "\n".join(hits)


def test_memoization_is_frozen() -> None:
    found = {}
    for f in BACKEND.rglob("*.py"):
        n = len(MEMO.findall(f.read_text(encoding="utf-8")))
        if n:
            found[f.relative_to(BACKEND).as_posix()] = n
    assert found == MEMO_ALLOWED, (
        "memoized functions changed; a cache around data breaks the no-stale-data rule. "
        f"found {found}"
    )


def test_server_fetches_skip_the_next_cache() -> None:
    """Server code in app/ and lib/ runs inside Next.js, whose fetch caches unless told not to."""
    missing = []
    for d in (ROOT / "frontend" / "app", ROOT / "frontend" / "lib"):
        for f in d.rglob("*"):
            if f.suffix not in {".ts", ".tsx"}:
                continue
            text = f.read_text(encoding="utf-8")
            if text.lstrip().startswith(('"use client"', "'use client'")):
                continue
            for m in re.finditer(r"\bfetch\(", text):
                window = text[m.start() : m.start() + 400]
                if "no-store" not in window:
                    line = text.count("\n", 0, m.start()) + 1
                    missing.append(f"{f.relative_to(ROOT)}:{line}")
    assert not missing, 'server fetch without cache: "no-store":\n' + "\n".join(missing)
