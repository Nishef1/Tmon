"""The v2 ranking page: zones follow the configured fractions and the API never invents a verdict."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import ranking as rk
from tmon.core.db import get_session
from tmon.storage import objectstore
from tmon.storage.objectstore import MemoryStore
from tmon.tools.v2_ranking import _zone

DOC = {
    "as_of": "2026-11-10",
    "basket_size": 100,
    "recommendation_allowed": False,
    "buy_top_frac": 0.1,
    "hold_top_frac": 0.3,
    "exposure": {"trend": 1.0, "abs_mom": 1.0, "vol_cap": 1.0, "stress": 0.99, "exposure": 0.99},
    "exposure_date": "2026-11-10",
    "rows": [
        {
            "rank": 1,
            "symbol": "الف",
            "name": None,
            "sector_code": None,
            "score": 0.95,
            "zone": "buy",
            "queue_state": "none",
            "median_value": 1e9,
            "signals": {"ind_buy_power": 0.9, "rv_20": None},
        }
    ],
    "evidence": [
        {
            "horizon_days": 20,
            "ic": 0.1,
            "ic_t": 3.0,
            "top_excess": 0.04,
            "bottom_excess": 0.0,
            "excess_t": 4.0,
            "n_days": 100,
        }
    ],
    "gates": [],
    "book": {"n_buys": 1, "cancelled_buys": 0, "postponed_sells": 0, "avg_held": 1.0},
}


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def test_zones_follow_the_configured_fractions() -> None:
    assert _zone(0.95, 0.1, 0.3) == "buy"
    assert _zone(0.9, 0.1, 0.3) == "hold"  # the boundary belongs to the lower zone
    assert _zone(0.75, 0.1, 0.3) == "hold"
    assert _zone(0.7, 0.1, 0.3) == "avoid"
    assert _zone(0.0, 0.1, 0.3) == "avoid"


def test_endpoint_without_a_stored_ranking_says_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(objectstore, "get_object_store", MemoryStore)
    body = client.get("/v2/ranking").json()
    assert body["available"] is False
    assert body["recommendation_allowed"] is False
    assert body["rows"] == []


def test_endpoint_serves_the_stored_document_and_keeps_the_disclaimer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.core.config import get_settings
    from tmon.tools.v2_ranking import KEY

    store = MemoryStore()
    store.put(
        get_settings().minio_artifact_bucket,
        KEY,
        json.dumps(DOC, ensure_ascii=False).encode(),
        "application/json",
    )
    monkeypatch.setattr(objectstore, "get_object_store", lambda: store)
    body = client.get("/v2/ranking").json()
    assert body["available"] is True
    assert body["recommendation_allowed"] is False
    assert body["rows"][0]["zone"] == "buy"
    assert body["evidence"][0]["horizon_days"] == 20
    assert "توصیه سرمایه‌گذاری نیست" in body["disclaimer"]


def test_universe_scores_match_the_engine_for_members_and_extend_to_the_rest() -> None:
    import datetime as dt

    import numpy as np
    import polars as pl

    from tmon.backtest.signal_decay import build_panel
    from tmon.core.engine_config import get_engine_config
    from tmon.tools.v2_ranking import universe_scores

    cfg = get_engine_config()
    rng = np.random.default_rng(7)
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(300)]
    n = 40
    adj_rows, feat_rows = [], []
    for i in range(n):
        px = 1000 * np.exp(np.cumsum(rng.normal(0.001 * (i - 20) / 20, 0.02, len(days))))
        for d, p in zip(days, px, strict=True):
            adj_rows.append({"instrument_id": i, "date": d, "adj_close": float(p)})
            feat_rows.append(
                {
                    "instrument_id": i,
                    "date": d,
                    "eligible": i < 30,  # the last ten are "thin": outside the engine universe
                    "market_halt": False,
                    "queue_state": "none",
                    "median_value_20": 1e11 if i < 30 else 1e9,
                    "ind_buy_power": float(rng.uniform(0.2, 3)),
                    "rv_20": float(rng.uniform(0.1, 0.8)),
                    "dist_high_52w": float(rng.uniform(0.5, 1.0)),
                }
            )
    feats = pl.DataFrame(feat_rows).with_columns(
        pl.when(pl.col("instrument_id") == 39).then(None).otherwise(pl.col("rv_20")).alias("rv_20")
    )
    adj = pl.DataFrame(adj_rows)
    last = days[-1]
    got = {r["id"]: r for r in universe_scores(feats, adj, cfg, last)}
    assert len(got) == n
    panel = build_panel(feats, adj, cfg, horizons=(5,)).filter(pl.col("date") == last)
    for r in panel.iter_rows(named=True):
        # equal composites are one tie here and may be split by float noise in the engine: a
        # difference of at most half a rank of the 30 members
        assert abs(got[r["instrument_id"]]["score"] - r["r_composite"]) <= 0.5 / 30 + 1e-9
    thin = got[35]
    assert thin["eligible"] is False and thin["score"] is not None and 0 <= thin["score"] <= 1
    assert thin["zone"] in ("buy", "hold", "avoid")
    # one signal never known: scored from the other three and marked partial
    assert got[39]["missing"] == ["rv_20"] and got[39]["partial"] is True
    assert got[39]["score"] is not None and got[39]["signals_as_of"] == str(last)


def test_a_partly_ingested_last_day_does_not_drop_scores() -> None:
    """The newest day often has prices but not yet client types (ind_buy_power), or no row at all
    for a halted name: each signal's newest known value is carried forward."""
    import datetime as dt

    import numpy as np
    import polars as pl

    from tmon.core.engine_config import get_engine_config
    from tmon.tools.v2_ranking import universe_scores

    cfg = get_engine_config()
    rng = np.random.default_rng(3)
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(300)]
    adj_rows, feat_rows = [], []
    for i in range(20):
        px = 1000 * np.exp(np.cumsum(rng.normal(0, 0.02, len(days))))
        for k, (d, p) in enumerate(zip(days, px, strict=True)):
            adj_rows.append({"instrument_id": i, "date": d, "adj_close": float(p)})
            if i == 19 and k >= len(days) - 2:
                continue  # halted for the last two days: no rows
            feat_rows.append(
                {
                    "instrument_id": i,
                    "date": d,
                    "eligible": True,
                    "market_halt": False,
                    "queue_state": "none",
                    "median_value_20": 1e11,
                    # the last day lacks client types for all but three names
                    "ind_buy_power": None if k == len(days) - 1 and i > 2 else float(i + 1),
                    "rv_20": float(rng.uniform(0.1, 0.8)),
                    "dist_high_52w": float(rng.uniform(0.5, 1.0)),
                }
            )
    feats = pl.DataFrame(feat_rows)
    got = {r["id"]: r for r in universe_scores(feats, pl.DataFrame(adj_rows), cfg, days[-1])}
    assert len(got) == 20 and all(r["score"] is not None for r in got.values())
    assert all(not r["partial"] for r in got.values())
    assert got[10]["signals_as_of"] == str(days[-2])
    assert got[19]["seen"] == str(days[-3])


def test_a_fresh_listing_gets_no_score_and_does_not_shape_the_ranking() -> None:
    """A name with fewer than MIN_RANK_DAYS trading days is not scored (not even partially), is not
    part of the reference every other score is placed in, and never enters the basket."""
    import datetime as dt

    import numpy as np
    import polars as pl

    from tmon.core.engine_config import get_engine_config
    from tmon.tools.v2_ranking import MIN_RANK_DAYS, rows_for, universe_scores

    cfg = get_engine_config()
    rng = np.random.default_rng(11)
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(300)]
    adj_rows, feat_rows = [], []
    for i in range(21):
        young = i == 20  # listed 100 days before the last day, very liquid and very strong
        first = len(days) - 100 if young else 0
        px = 1000 * np.exp(np.cumsum(rng.normal(0.01 if young else 0, 0.02, len(days) - first)))
        for d, p in zip(days[first:], px, strict=True):
            adj_rows.append({"instrument_id": i, "date": d, "adj_close": float(p)})
            feat_rows.append(
                {
                    "instrument_id": i,
                    "date": d,
                    "eligible": True,
                    "market_halt": False,
                    "queue_state": "none",
                    "median_value_20": 1e13 if young else 1e11,
                    "ind_buy_power": 100.0 if young else float(rng.uniform(0.2, 3)),
                    "rv_20": 0.01 if young else float(rng.uniform(0.1, 0.8)),
                    "dist_high_52w": 1.0 if young else float(rng.uniform(0.5, 1.0)),
                }
            )
    feats, adj = pl.DataFrame(feat_rows), pl.DataFrame(adj_rows)
    got = universe_scores(feats, adj, cfg, days[-1])
    by_id = {r["id"]: r for r in got}
    new = by_id[20]
    assert new["too_new"] is True and new["history_days"] == 100 < MIN_RANK_DAYS
    assert new["score"] is None and new["zone"] is None
    assert all(not by_id[i]["too_new"] and by_id[i]["score"] is not None for i in range(20))
    names = {
        i: type("I", (), {"symbol_fa": f"s{i}", "name_fa": f"n{i}", "sector_code": None})()
        for i in range(21)
    }
    assert 20 not in {r["symbol"] for r in rows_for(got, names)} | set()  # symbols are s<i>
    assert "s20" not in {r["symbol"] for r in rows_for(got, names)}


class _Kinds:
    """Stands in for the session: ``execute(...).all()`` answers (instrument id, type) pairs."""

    def __init__(self, kinds: dict[int, str]) -> None:
        self._kinds = kinds

    def execute(self, _stmt: object) -> _Kinds:
        return self

    def all(self) -> list[tuple[int, str]]:
        return list(self._kinds.items())


def test_a_row_gets_the_stock_pages_answer_whether_or_not_it_traded_today() -> None:
    """A buy row that is idle today and a buy row that is a fund used to keep "buy" in the list
    while their own pages said wait / no decision."""
    from tmon.api.schemas import RankingOut

    stock = {**DOC["rows"][0], "symbol": "الف", "rank": 1, "band": "candidate"}  # type: ignore[index]
    fund = {**stock, "symbol": "ب", "rank": 2, "name": "صندوق ب"}
    out = RankingOut(available=True, **{**DOC, "rows": [stock, fund]})
    for r, ident in zip(out.rows, (7, 8), strict=True):
        r.instrument_id, r.verdict = ident, "candidate"
    hot = {
        "symbols": {"7": {"state": "hot"}},
        "history": {
            "states": {
                "hot": {
                    "n": 40000,
                    "h20": None,
                    "h60": {"n": 40000, "excess_mean": -0.002, "p_dn20": 0.11},
                }
            },
            "base": {"h20": None, "h60": {"n": 1000000, "excess_mean": 0.0, "p_dn20": 0.05}},
        },
        "states": [],
    }
    rule = {
        "horizon_days": 60,
        "candidate_top_frac": 0.5,
        "avoid_bottom_frac": 0.4,
        "candidate_grade": "unproven",
        "avoid_grade": "unproven",
    }
    doc = {**DOC, "round_trip_cost": 0.017512, "verdict": rule}
    rk._settle_verdicts(_Kinds({7: "stock", 8: "etf_equity"}), out, doc, hot)  # type: ignore[arg-type]
    assert out.rows[0].verdict == "hold" and out.rows[0].code == "wait"  # the state objects
    assert out.rows[1].verdict is None  # a fund has no verdict, as on its page
