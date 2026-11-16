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
    from tmon.storage import objectstore

    monkeypatch.setattr(objectstore, "get_object_store", objectstore.MemoryStore)


@pytest.fixture(autouse=True)
def _no_live_tsetmc(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live endpoint asks TSETMC for the current book; tests stay offline."""
    from tmon.api.routers import instruments

    monkeypatch.setattr(instruments, "_tsetmc_book", lambda inst: [])


@pytest.fixture(autouse=True)
def _no_live_price_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The portfolio overlays the exchange's live price; tests stay offline (no bar = stored price)."""
    from tmon.portfolio import liveprice

    monkeypatch.setattr(liveprice, "fetch", lambda ins_code: None)
