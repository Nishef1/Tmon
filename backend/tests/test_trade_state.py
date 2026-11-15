"""A symbol with no price row on recent market days is shown as idle or stopped, in search and on
the symbol page, and the search can hide the stopped ones."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import dashboard as dash
from tmon.api.trade_state import market_days, trade_state
from tmon.core.db import get_session
from tmon.storage.models import Instrument, PriceDaily

LAST = dt.date(2026, 11, 10)


def _row(i: int, day: dt.date, volume: int = 10) -> PriceDaily:
    return PriceDaily(
        instrument_id=i, date=day, open=100, high=100, low=100, last=100, close=100,
        prev_close=100, volume=volume, value=1e9, trades=1,
    )  # fmt: skip


@pytest.fixture
def seeded(session: Session) -> Session:
    # 1 trades every day; 2 missed the last day; 3 stopped four market days ago; 4 never traded
    for i, sym in enumerate(["الف", "ب", "ج", "د"], start=1):
        session.add(Instrument(id=i, ins_code=f"c{i}", symbol_fa=sym, instrument_type="stock"))
    for k in range(6):
        day = LAST - dt.timedelta(days=k)
        session.add(_row(1, day))
        if k >= 1:
            session.add(_row(2, day))
        if k >= 4:
            session.add(_row(3, day))
    session.commit()
    return session


def test_states_follow_the_market_days_since_the_last_trade(seeded: Session) -> None:
    days = market_days(seeded)
    assert days[0] == LAST
    assert trade_state(seeded, 1, days) == ("active", LAST, 0)
    assert trade_state(seeded, 2, days) == ("idle", LAST - dt.timedelta(days=1), 1)
    state, last, idle = trade_state(seeded, 3, days)
    assert (state, last, idle) == ("halted", LAST - dt.timedelta(days=4), 4)
    state, last, idle = trade_state(seeded, 4, days)
    assert state == "halted" and last is None and idle == len(days)


def test_search_reports_the_state_and_can_hide_stopped_symbols(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dash, "_ranking_doc", lambda: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: seeded
    client = TestClient(app)
    try:
        hits = client.get("/search", params={"q": "ج"}).json()["hits"]
        assert hits[0]["trade_state"] == "halted" and hits[0]["idle_days"] == 4
        assert client.get("/search", params={"q": "ج", "active_only": "true"}).json()["hits"] == []
        kept = client.get("/search", params={"q": "ب", "active_only": "true"}).json()["hits"]
        assert kept[0]["trade_state"] == "idle"
    finally:
        app.dependency_overrides.clear()
