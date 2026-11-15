from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tmon.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    # SQLite (the local no-Docker stack) allows one writer; wait for it instead of failing at 5 s
    args = {"timeout": 120} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, future=True, connect_args=args)
    if url.startswith("sqlite"):
        # WAL lets the site read while the daily cycle writes (no "database is locked")
        @event.listens_for(engine, "connect")
        def _wal(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=120000")
            # reads go through the OS page cache (no copy per connection); 64 MB page cache
            cur.execute("PRAGMA mmap_size=2147483648")
            cur.execute("PRAGMA cache_size=-65536")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.close()

    return engine


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
