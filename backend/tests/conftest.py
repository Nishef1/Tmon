from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tmon.storage.models import Base


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_object_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dashboard and screener read the ranking document; tests must not wait on a MinIO."""
    from tmon.api.routers import dashboard
    from tmon.storage.objectstore import MemoryStore

    monkeypatch.setattr(dashboard, "get_object_store", lambda: MemoryStore())
