"""The portfolio ledger: sizes and prices left out, sales, cash, capital increases, dividends,
history, and the Mofid sync."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.portfolio import ledger, mofid
from tmon.storage.models import (
    Instrument,
    Portfolio,
    PortfolioTrade,
    PriceAdjustment,
    PriceDaily,
    ShareChange,
)

AT = dt.datetime(2026, 11, 14, 7, 0, tzinfo=dt.UTC)
D0 = dt.date(2026, 1, 1)


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _stock(session: Session, symbol: str, prices: list[float], isin: str | None = None) -> int:
    i = Instrument(
        ins_code=str(abs(hash(symbol)) % 10**12), symbol_fa=symbol, name_fa=symbol, isin=isin
    )
    session.add(i)
    session.flush()
    for k, p in enumerate(prices):
        session.add(
            PriceDaily(
                instrument_id=i.id,
                date=D0 + dt.timedelta(days=k),
                open=p,
                high=p,
                low=p,
                last=p,
                close=p,
                prev_close=p,
                volume=1e6,
                value=p * 1e6,
                fetched_at=AT,
            )
        )
    session.flush()
    return i.id


def _portfolio(session: Session, cash: float = 0.0) -> Portfolio:
    p = Portfolio(name="t", key_hash="x", cash=cash, created_at=AT, settings={}, channels=[])
    session.add(p)
    session.flush()
    return p


def _trade(session: Session, p: Portfolio, iid: int, side: str, day: int, **kw: float) -> None:
    session.add(
        PortfolioTrade(
            portfolio_id=p.id,
            instrument_id=iid,
            side=side,
            date=D0 + dt.timedelta(days=day),
            created_at=AT,
            **kw,
        )
    )
    session.flush()


def test_a_buy_with_nothing_but_the_symbol_is_priced_and_sized(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 5 + [1200.0] * 5)
    b = _stock(session, "ب", [500.0] * 10)
    p = _portfolio(session)
    _trade(session, p, b, "buy", 0, shares=2000, price=500)  # 1,000,000 rial
    _trade(session, p, a, "buy", 2)  # no size, no price
    pos = ledger.replay(session, p)
    assert pos[a].price_estimated and pos[a].size_estimated
    assert pos[a].shares == pytest.approx(1000)  # same size as the other buy, at that day's close
    doc = ledger.summarize(session, p, pos)
    assert doc["estimated"]
    h = next(x for x in doc["holdings"] if x["instrument_id"] == a)
    assert h["unrealized"] > 0 and doc["totals"]["in_profit"]


def test_a_sale_books_realized_profit_after_fees(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 10)
    p = _portfolio(session)
    _trade(session, p, a, "buy", 0, shares=100, price=1000, fee=0)
    _trade(session, p, a, "sell", 5, shares=40, price=1500, fee=0)
    pos = ledger.replay(session, p)[a]
    assert pos.shares == 60
    assert pos.realized == pytest.approx(40 * 500)
    assert pos.cost == pytest.approx(60 * 1000)


def test_a_dividend_is_income_not_a_loss(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 5 + [900.0] * 5)
    session.add(
        PriceAdjustment(
            instrument_id=a,
            date=D0 + dt.timedelta(days=5),
            close_before=1000,
            price_after=900,
            adj_factor=0.9,
        )
    )
    p = _portfolio(session)
    _trade(session, p, a, "buy", 0, shares=100, price=1000, fee=0)
    pos = ledger.replay(session, p)[a]
    assert pos.dividends == pytest.approx(100 * 100)
    t = ledger.summarize(session, p, {a: pos})["totals"]
    # the price fell by the dividend: total profit is about the sell fee, not -10%
    assert t["total_pnl"] == pytest.approx(-90_000 * ledger.STOCK_FALLBACK[1], rel=0.5)


def test_a_bonus_issue_adds_shares_and_keeps_the_cost(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 5 + [500.0] * 5)
    day = D0 + dt.timedelta(days=5)
    session.add(
        PriceAdjustment(
            instrument_id=a, date=day, close_before=1000, price_after=500, adj_factor=0.5
        )
    )
    session.add(
        ShareChange(
            idn=1,
            ins_code="x",
            instrument_id=a,
            date=day,
            shares_old=1000,
            shares_new=2000,
            fetched_at=AT,
            source_url="x",
        )
    )
    p = _portfolio(session)
    _trade(session, p, a, "buy", 0, shares=100, price=1000, fee=0)
    pos = ledger.replay(session, p)[a]
    assert pos.shares == pytest.approx(200)
    assert pos.cost == pytest.approx(100_000)


def test_api_trades_cash_and_history(client: TestClient, session: Session) -> None:
    _stock(session, "الف", [1000.0 + 10 * k for k in range(30)])
    pid_key = client.post("/portfolios", json={"name": "من", "cash": 1_000_000}).json()
    pid, hdr = pid_key["id"], {"X-Portfolio-Key": pid_key["key"]}
    r = client.post(
        f"/portfolios/{pid}/trades",
        json={"side": "buy", "symbol": "الف", "shares": 500, "date": str(D0)},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cash"] < 1_000_000 - 500 * 1000 + 1  # paid with the fee
    assert body["holdings"][0]["shares"] == 500
    r = client.post(
        f"/portfolios/{pid}/trades",
        json={"side": "sell", "symbol": "الف", "date": str(D0 + dt.timedelta(days=20))},
        headers=hdr,
    )
    body = r.json()
    assert body["holdings"] == [] and body["realized"] > 0 and body["closed"]
    assert body["total_pnl"] == pytest.approx(body["realized"])
    trades = client.get(f"/portfolios/{pid}/trades", headers=hdr).json()
    assert [t["side"] for t in trades] == ["sell", "buy"]
    hist = client.get(f"/portfolios/{pid}/history", headers=hdr).json()
    assert hist["points"] and hist["return"] == pytest.approx(body["total_pnl_pct"], abs=1e-6)
    too_many = client.post(
        f"/portfolios/{pid}/trades",
        json={"side": "sell", "symbol": "الف", "shares": 1},
        headers=hdr,
    )
    assert too_many.status_code == 422


def test_mofid_positions_replace_the_ledger_for_their_symbols(session: Session) -> None:
    a = _stock(session, "طلا", [9000.0] * 10, isin="IRTKLOTF0001")
    b = _stock(session, "ب", [500.0] * 10)
    p = _portfolio(session)
    _trade(session, p, a, "buy", 0, shares=1, price=8000)  # replaced by Mofid
    _trade(session, p, b, "buy", 0, shares=10, price=500)  # not at Mofid: kept
    items = [
        {"symbolIsin": "IRTKLOTF0001", "symbolName": "طلا", "asset": 3280,
         "periodicBuyAveragePrice": 9129.1, "totalRealizedProfitAndLoss": 1315},
        {"symbolIsin": "IRXXXXXXXXXX", "symbolName": "ناشناس", "asset": 5},
        {"symbolIsin": "IRYYYYYYYYYY", "symbolName": "فروخته", "asset": 0},
    ]  # fmt: skip
    out = mofid.apply(session, p, items, {"buyPowerT0": 30_174_233})
    assert out["unknown"] == ["ناشناس"] and out["mofid_realized"] == 1315
    assert p.cash == 30_174_233
    pos = ledger.replay(session, p)
    assert pos[a].shares == 3280 and pos[b].shares == 10
    again = mofid.apply(session, p, items, {"buyPowerT0": 1})  # a re-sync does not double up
    assert again["positions"][0]["shares"] == 3280
    assert ledger.replay(session, p)[a].shares == 3280


def test_mofid_token_expiry_is_read_from_the_jwt() -> None:
    import base64
    import json

    claims = base64.urlsafe_b64encode(json.dumps({"exp": 1_800_000_000}).encode()).rstrip(b"=")
    tok = f"h.{claims.decode()}.s"
    assert mofid._expiry(tok) == dt.datetime.fromtimestamp(1_800_000_000, dt.UTC)
    assert mofid._expiry("garbage") is None


def test_history_counts_a_buy_dated_on_a_holiday(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 3)  # prices on days 0-2 only
    b = _stock(session, "ب", [1000.0] * 10)
    p = _portfolio(session)
    _trade(session, p, b, "buy", 0, shares=10, price=1000, fee=0)
    _trade(session, p, a, "buy", 5, shares=10, price=1000, fee=0)  # no session on day 5 for الف
    pos = ledger.replay(session, p)
    hist = ledger.history(session, p, pos)
    total = ledger.summarize(session, p, pos)["totals"]["total_pnl_pct"]
    assert hist["return"] == pytest.approx(total, abs=1e-9)


def test_a_mofid_average_that_could_not_have_been_paid_is_not_used(session: Session) -> None:
    a = _stock(session, "طلا", [170_000.0] * 10, isin="IRTKLOTF0001")
    p = _portfolio(session)
    item = {"symbolIsin": "IRTKLOTF0001", "symbolName": "طلا", "asset": 3280,
            "date": str(D0), "periodicBoughtVolume": 3280,
            "periodicBuyAveragePrice": 9129.1}  # fmt: skip
    out = mofid.apply(session, p, [item], {"buyPowerT0": 0})
    assert out["positions"][0]["cost_source"] == "doubtful"
    pos = ledger.replay(session, p)[a]
    assert pos.price_estimated  # valued at the close, not a fake +1700%
    link = mofid._link(session, p.id)
    link.last_result = {**out, "items": [item]}
    mofid.set_cost(session, p, "IRTKLOTF0001", 500_000_000)
    assert ledger.replay(session, p)[a].cost == pytest.approx(500_000_000)
    assert mofid.status(session, p.id)["last_result"]["positions"][0]["cost_source"] == "owner"


def test_a_deleted_line_is_not_brought_back_from_the_old_holdings(session: Session) -> None:
    from sqlalchemy import delete

    from tmon.storage.models import Holding

    a = _stock(session, "الف", [1000.0] * 5)
    p = _portfolio(session)
    session.add(
        Holding(portfolio_id=p.id, instrument_id=a, shares=10, avg_price=1000, created_at=AT)
    )
    session.flush()
    assert ledger.rebuild(session, p)[a].shares == 10  # migrated once
    session.execute(delete(PortfolioTrade).where(PortfolioTrade.portfolio_id == p.id))
    session.flush()
    assert a not in ledger.rebuild(session, p)


def test_a_mofid_line_after_a_bonus_keeps_its_cost_shares_and_date(session: Session) -> None:
    a = _stock(session, "طلا", [1_800_000.0] * 5 + [180_000.0] * 5, isin="IRTKLOTF0001")
    bonus = D0 + dt.timedelta(days=5)
    session.add(
        PriceAdjustment(
            instrument_id=a,
            date=bonus,
            close_before=1_800_000,
            price_after=180_000,
            adj_factor=0.1,
        )
    )
    session.add(
        ShareChange(
            idn=1, ins_code="x", instrument_id=a, date=bonus, shares_old=1000,
            shares_new=10_000, fetched_at=AT, source_url="x",
        )
    )  # fmt: skip
    session.flush()
    p = _portfolio(session)
    # Mofid restarts the period at the bonus and counts the bonus shares as bought there
    item = {"symbolIsin": "IRTKLOTF0001", "symbolName": "طلا", "asset": 3280,
            "date": str(D0), "periodicBoughtVolume": 3280, "totalBoughtVolume": 3380,
            "periodicBuyAveragePrice": 9129.1}  # fmt: skip
    out = mofid.apply(session, p, [item], {"buyPowerT0": 0})
    assert out["positions"][0]["cost_source"] == "mofid"
    pos = ledger.replay(session, p)[a]
    assert pos.shares == 3280  # today's count, not multiplied by the bonus again
    assert pos.cost == pytest.approx(3280 * 9129.1, rel=0.01)  # plus the buy fee
    line = session.query(PortfolioTrade).filter_by(portfolio_id=p.id).one()
    assert line.date == bonus  # moved past the bonus, never the sync day


def test_a_mofid_line_is_dated_when_mofid_says_it_was_bought(session: Session) -> None:
    a = _stock(session, "الف", [1000.0] * 10, isin="IRO1AAAA0001")
    p = _portfolio(session)
    item = {"symbolIsin": "IRO1AAAA0001", "symbolName": "الف", "asset": 10,
            "date": str(D0 + dt.timedelta(days=3)), "periodicBuyAveragePrice": 1000}  # fmt: skip
    mofid.apply(session, p, [item], {"buyPowerT0": 0})
    line = session.query(PortfolioTrade).filter_by(portfolio_id=p.id, instrument_id=a).one()
    assert line.date == D0 + dt.timedelta(days=3)


def test_an_expired_mofid_login_marks_the_link_broken_and_alerts_once(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.portfolio import alerts
    from tmon.storage.models import BrokerLink

    def no_chrome(*a: object, **k: object) -> str:
        raise RuntimeError("chrome not found")  # the server

    monkeypatch.setattr(mofid, "capture_token", no_chrome)
    p = _portfolio(session)
    session.add(
        BrokerLink(
            portfolio_id=p.id,
            broker="mofid",
            status="linked",
            token="old",
            expires_at=AT - dt.timedelta(hours=1),
            last_sync_at=dt.datetime(2026, 11, 21, 6, 0),
        )
    )
    session.flush()
    with pytest.raises(mofid.MofidError):
        mofid.sync(session, p)
    st = mofid.status(session, p.id)
    assert st["status"] == "error" and st["stale"]
    assert st["message"] == mofid.EXPIRED
    f = mofid.broken_finding(session.get(BrokerLink, p.id))  # type: ignore[arg-type]
    assert "۱۴۰۵/۰۸/۳۰ ساعت ۰۹:۳۰" in f.body  # the last good copy, Tehran time
    assert len(alerts.record(session, p.id, [f], AT)) == 1
    assert alerts.record(session, p.id, [f], AT) == []  # the same break alerts once


def test_a_token_renewed_on_the_pc_is_accepted_and_synced(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    _stock(session, "الف", [1000.0] * 5, isin="IRO1AAAA0001")
    p = _portfolio(session)
    seen: dict[str, str] = {}

    def fake_get(token: str, path: str) -> object:
        seen["token"] = token
        if path.endswith("money"):
            return {"buyPowerT0": 5}
        return {"items": [{"symbolIsin": "IRO1AAAA0001", "symbolName": "الف", "asset": 3}]}

    @contextlib.contextmanager
    def same() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(mofid, "_get", fake_get)
    monkeypatch.setattr(mofid, "session_scope", same)
    out = mofid.accept(p.id, "a.b.c")
    assert seen["token"] == "a.b.c" and out["positions"][0]["shares"] == 3
    st = mofid.status(session, p.id)
    assert st["status"] == "linked" and not st["stale"] and "token" not in st


def test_the_owner_password_opens_every_portfolio_in_a_new_browser(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.api.routers import portfolios as router
    from tmon.core.config import get_settings
    from tmon.portfolio import keys

    a = client.post("/portfolios", json={"name": "یک"}).json()
    b = client.post("/portfolios", json={"name": "دو"}).json()
    assert client.post("/portfolios/owner/login", json={"password": "x"}).status_code == 503
    st = get_settings()
    monkeypatch.setattr(st, "owner_password_hash", keys.hash_password("درست-است-۱۲۳"))
    monkeypatch.setattr(st, "owner_secret", "s" * 64)
    monkeypatch.setattr(router, "_failed", [])
    r = client.post("/portfolios/owner/login", json={"password": "درست-است-۱۲۳"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert [x["name"] for x in r.json()["portfolios"]] == ["یک", "دو"]
    for pid in (a["id"], b["id"]):
        assert client.get(f"/portfolios/{pid}", headers={"X-Portfolio-Key": tok}).status_code == 200
    assert (
        client.get(f"/portfolios/{a['id']}", headers={"X-Portfolio-Key": a["key"]}).status_code
        == 200
    )
    forged = tok[:-4] + "0000"
    assert (
        client.get(f"/portfolios/{a['id']}", headers={"X-Portfolio-Key": forged}).status_code == 404
    )
    # a new password ends the tokens given before it
    monkeypatch.setattr(st, "owner_password_hash", keys.hash_password("رمز-تازه-۴۵۶"))
    assert client.get(f"/portfolios/{a['id']}", headers={"X-Portfolio-Key": tok}).status_code == 404
    codes = [
        client.post("/portfolios/owner/login", json={"password": "غلط"}).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]
