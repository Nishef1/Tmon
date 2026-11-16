from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from tmon.portfolio import alerts as alert_store
from tmon.portfolio.meetings import meeting_finding, meeting_findings
from tmon.portfolio.watch import URGENT, WARN, HoldingView
from tmon.storage.models import CorporateEvent

TODAY = dt.date(2026, 11, 16)


def _holding(instrument_id: int = 1, symbol: str = "الف") -> HoldingView:
    return HoldingView(1, 7, instrument_id, "1", symbol, 100, 1000, None, None)


def test_far_meeting_is_not_pushed() -> None:
    far = TODAY + dt.timedelta(days=8)
    assert meeting_finding(7, _holding(), "مجمع سالانه", far, 8) is None
    assert meeting_finding(7, _holding(), "مجمع سالانه", TODAY, -1) is None


def test_meeting_within_a_week_warns_and_tomorrow_is_urgent() -> None:
    day = TODAY + dt.timedelta(days=5)
    f = meeting_finding(7, _holding(), "مجمع سالانه", day, 5)
    assert f is not None and f.severity == WARN
    assert "5 روز دیگر" in f.title
    tomorrow = meeting_finding(7, _holding(), "مجمع سالانه", TODAY + dt.timedelta(days=1), 1)
    assert tomorrow is not None and tomorrow.severity == URGENT and "فردا" in tomorrow.title
    today = meeting_finding(7, _holding(), "مجمع سالانه", TODAY, 0)
    assert today is not None and "امروز" in today.title


def test_findings_read_held_symbols_only_and_skip_cancelled(session: Session) -> None:
    base = {"type": "agm_dividend", "title": "آگهی"}
    session.add_all(
        [
            CorporateEvent(instrument_id=1, stage="invitation", announced_at=TODAY,
                           event_date=TODAY + dt.timedelta(days=3), **base),
            CorporateEvent(instrument_id=2, stage="invitation", announced_at=TODAY,
                           event_date=TODAY + dt.timedelta(days=2), **base),
            CorporateEvent(instrument_id=2, stage="meeting_cancelled", announced_at=TODAY, **base),
            CorporateEvent(instrument_id=3, stage="invitation", announced_at=TODAY,
                           event_date=TODAY + dt.timedelta(days=2), **base),
        ]
    )  # fmt: skip
    session.commit()
    views = {7: [_holding(1, "الف"), _holding(2, "ب")]}  # instrument 3 is not held
    out = meeting_findings(session, views, TODAY)
    assert list(out) == [7]
    assert [f.instrument_id for f in out[7]] == [1]  # 2 was cancelled, 3 is not held
    assert out[7][0].key == f"7:meeting:1:{(TODAY + dt.timedelta(days=3)).isoformat()}"


def test_same_meeting_alerts_once_until_it_gets_urgent(session: Session) -> None:
    from tmon.storage.models import Portfolio

    at = dt.datetime.now(dt.UTC)
    session.add(
        Portfolio(id=7, name="p", key_hash="h", cash=0, settings={}, channels=[], created_at=at)
    )
    session.commit()
    day = TODAY + dt.timedelta(days=3)
    warn = meeting_finding(7, _holding(), "مجمع سالانه", day, 3)
    urgent = meeting_finding(7, _holding(), "مجمع سالانه", day, 1)
    assert warn is not None and urgent is not None
    assert len(alert_store.record(session, 7, [warn], dt.datetime.now(dt.UTC))) == 1
    assert alert_store.record(session, 7, [warn], dt.datetime.now(dt.UTC)) == []
    assert len(alert_store.record(session, 7, [urgent], dt.datetime.now(dt.UTC))) == 1
