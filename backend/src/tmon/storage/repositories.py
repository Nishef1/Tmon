"""Idempotent bulk upserts, portable across PostgreSQL and SQLite (tests)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tmon.storage.models import Base

_CHUNK = 2000


def upsert(
    session: Session,
    model: type[Base],
    rows: Iterable[Mapping[str, Any]],
    *,
    conflict_columns: Sequence[str] | None = None,
) -> int:
    """Insert ``rows``; on primary-key (or ``conflict_columns``) conflict update the rest."""
    batch = list(rows)
    if not batch:
        return 0
    mapper = inspect(model)
    pk = [str(c) for c in conflict_columns or [str(col.key) for col in mapper.primary_key]]
    all_cols = [str(c.key) for c in mapper.columns]
    update_cols = [c for c in batch[0] if c in all_cols and c not in pk]

    dialect = session.get_bind().dialect.name
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    written = 0
    for i in range(0, len(batch), _CHUNK):
        chunk = batch[i : i + _CHUNK]
        stmt = insert_fn(model).values(chunk)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk, set_={c: stmt.excluded[c] for c in update_cols}
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk)
        session.execute(stmt)
        written += len(chunk)
    return written
