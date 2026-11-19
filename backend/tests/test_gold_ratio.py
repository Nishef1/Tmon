"""Gold premium, coin bubble and oil/gold (tmon.domain.gold_ratio, docs/reports/gold-oil-2026-11.md)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.domain import gold_ratio as gr
from tmon.storage.models import MacroSeries

GRAM = gr.GRAM_PER_OUNCE
START = date(2025, 1, 2)  # a Thursday


def _series(weeks: int, last_prem: float) -> dict[str, list[tuple[date, float]]]:
    """Flat ounce and dollar; 18k gold at its gold value except the last week."""
    pts: dict[str, list[tuple[date, float]]] = {s: [] for s in gr.SERIES}
    for k in range(weeks):
        d = START + timedelta(days=7 * k)
        prem = last_prem if k == weeks - 1 else 0.0
        gram = 2000.0 * 1_000_000 / GRAM
        pts["usd_free"].append((d, 1_000_000))
        pts["gold_usd"].append((d, 2000.0))
        pts["brent_usd"].append((d, 80.0))
        pts["gold_18k"].append((d, gram * 0.75 * (1 + prem)))
        pts["coin_emami"].append((d, gram * 8.133 * 0.9 * 1.05))
    return pts


def test_week_runs_thursday_to_wednesday():
    thu = date(2026, 11, 12)
    assert all(gr.week_of(thu + timedelta(days=i)) == date(2026, 11, 16) for i in range(7))
    assert gr.week_of(thu - timedelta(days=1)) == date(2026, 11, 9)


def test_premium_bubble_and_state():
    g = gr.gold_oil(_series(60, 0.03))
    assert g is not None
    assert g.gold_prem.value == pytest.approx(0.03)
    assert g.coin_bubble.value == pytest.approx(0.05)
    assert g.oil_gold.value == pytest.approx(0.04)
    assert g.usd_implied == pytest.approx(1_030_000)
    # mean of the last 52 weeks holds the 3% week once
    assert g.gold_prem.deviation == pytest.approx(0.03 - 0.03 / 52)
    assert g.gold_prem.state == "high"
    assert g.coin_bubble.state == "normal"
    assert g.oil_gold.state is None
    assert gr.gold_oil(_series(60, -0.03)).gold_prem.state == "low"  # type: ignore[union-attr]
    assert gr.gold_oil(_series(10, 0.0)) is None


def test_cuts_match_the_report():
    text = (Path(__file__).parents[2] / "docs/reports/gold-oil-2026-11.md").read_text("utf-8")
    assert gr.GOLD_PREM_CUTS == (-0.025, 0.016)
    assert re.search(r"حباب طلا ۱٫۶ واحد بالاتر", text)
    assert re.search(r"حباب طلا ۲٫۵ واحد پایین‌تر", text)
    assert gr.COIN_BUBBLE_CUTS[1] == 0.039 and "مرز ۳٫۹" in text


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_endpoint(session, client):
    assert client.get("/macro/gold-oil").status_code == 404
    for s, pts in _series(60, 0.03).items():
        src = "yahoo" if s in ("gold_usd", "brent_usd") else "tgju"
        session.add_all(
            MacroSeries(series=s, source=src, ref_period=d, value=v, release_date=d) for d, v in pts
        )
    session.flush()
    j = client.get("/macro/gold-oil").json()
    assert j["gold_prem"]["state"] == "high"
    assert j["gold_prem_cuts"] == [-0.025, 0.016]


def test_bahar_coin_bubble_has_no_usual_range():
    pts = _series(60, 0.0)
    assert gr.gold_oil(pts).coin_bahar is None  # type: ignore[union-attr]
    gram = 2000.0 * 1_000_000 / GRAM
    pts[gr.BAHAR] = [(d, gram * 8.133 * 0.9 * 1.02) for d, _ in pts["usd_free"]]
    g = gr.gold_oil(pts)
    assert g is not None and g.coin_bahar_bubble is not None
    assert g.coin_bahar_bubble.value == pytest.approx(0.02)
    assert g.coin_bahar_bubble.state is None
    # a stale Bahar series (ending before the other series) is not shown
    pts[gr.BAHAR] = pts[gr.BAHAR][:-5]
    assert gr.gold_oil(pts).coin_bahar is None  # type: ignore[union-attr]
