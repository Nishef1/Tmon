"""Domestic and foreign highlights for the briefings: what moved since the last session, and how
much each holding has historically reacted to it.

Moves: every series in ``macro_series`` (free-market dollar, Emami coin, 18k gold from tgju; Brent,
copper, COMEX gold and the dollar index from Yahoo), latest value against the value on the
holding's last trading day and five observations earlier.

Sensitivity is measured, not assumed: for each held stock, its daily return on Tehran trading day
``t`` is regressed (one series at a time, ordinary least squares) on the series' move between the
two previous Tehran sessions as-of date (foreign markets close after Tehran, so their move shows up
in the next session). Only betas with ``|t| >= T_MIN`` over the last ``WINDOW`` sessions are kept.
The expected pressure on the next open is ``beta * move since the stock's last close``; it is a
historical tendency, reported with its t-statistic, never a promise.

Foreign headlines come from the English feeds in :data:`tmon.ingest.news.rss.FOREIGN`, filtered to
what can move Tehran (Iran, Hormuz, sanctions, oil, OPEC, the Fed, the dollar, metals, China...).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.ingest.news.rss import FOREIGN
from tmon.storage.models import MacroSeries, NewsRaw, PriceDaily

LABEL_FA: dict[str, str] = {
    "usd_free": "دلار آزاد",
    "coin_emami": "سکه امامی",
    "gold_18k": "طلای ۱۸ عیار",
    "brent_usd": "نفت برنت",
    "copper_usd": "مس",
    "gold_usd": "طلای جهانی",
    "dxy": "شاخص دلار",
}
DOMESTIC = frozenset({"usd_free", "coin_emami", "gold_18k"})
WINDOW = 500  # Tehran sessions in the regression
MIN_OBS = 120
T_MIN = 2.5  # seven series per stock: a stricter bar than 2 against chance hits
FOREIGN_WORDS = re.compile(
    r"\b(iran\w*|tehran|hormuz|gulf|sanction\w*|opec\w*|oil|crude|brent|fed|rate cut\w*|"
    r"inflation|dollar|gold|copper|steel|iron ore|china|israel|war|ceasefire|tanker\w*|"
    r"recession|tariff\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Move:
    series: str
    label_fa: str
    last: float
    last_date: dt.date
    change_1: float | None  # since the previous observation
    change_5: float | None  # since five observations earlier

    def since(self, history: list[tuple[dt.date, float]], day: dt.date) -> float | None:
        """Change from the last value the session of ``day`` could price (dated before it: a
        value dated ``day`` is published after Tehran closes) to the latest value."""
        base = [v for d, v in history if d < day]
        return self.last / base[-1] - 1.0 if base and base[-1] else None


def load_series(session: Session) -> dict[str, list[tuple[dt.date, float]]]:
    out: dict[str, list[tuple[dt.date, float]]] = {}
    rows = session.execute(
        select(MacroSeries.series, MacroSeries.ref_period, MacroSeries.value)
        .where(MacroSeries.series.in_(list(LABEL_FA)))
        .order_by(MacroSeries.series, MacroSeries.ref_period)
    )
    for name, day, value in rows:
        if value and np.isfinite(value) and value > 0:
            out.setdefault(str(name), []).append((day, float(value)))
    return out


def moves(series: dict[str, list[tuple[dt.date, float]]]) -> dict[str, Move]:
    out: dict[str, Move] = {}
    for name, hist in series.items():
        if not hist:
            continue
        d, v = hist[-1]

        def ch(k: int, hist: list[tuple[dt.date, float]] = hist, v: float = v) -> float | None:
            return v / hist[-1 - k][1] - 1.0 if len(hist) > k else None

        out[name] = Move(name, LABEL_FA.get(name, name), v, d, ch(1), ch(5))
    return out


def _asof(hist: list[tuple[dt.date, float]], days: list[dt.date]) -> np.ndarray:
    """Value of the series as-of (strictly before) each Tehran day."""
    ds = np.array([np.datetime64(d) for d, _ in hist])
    vs = np.array([v for _, v in hist], dtype=float)
    idx = np.searchsorted(ds, np.array([np.datetime64(d) for d in days]), side="left") - 1
    out = np.full(len(days), np.nan)
    ok = idx >= 0
    out[ok] = vs[idx[ok]]
    return out


def sensitivities(
    session: Session, instrument_id: int, series: dict[str, list[tuple[dt.date, float]]]
) -> dict[str, tuple[float, float, int]]:
    """``{series: (beta, t, n)}`` of the stock's session return on the series' overnight move."""
    rows = session.execute(
        select(PriceDaily.date, PriceDaily.close, PriceDaily.prev_close)
        .where(PriceDaily.instrument_id == instrument_id)
        .order_by(PriceDaily.date.desc())
        .limit(WINDOW + 1)
    ).all()
    rows = rows[::-1]
    if len(rows) < MIN_OBS:
        return {}
    days = [r[0] for r in rows]
    # close / prev_close - 1 is the adjusted return (prev_close is TSETMC's adjusted reference)
    ret = np.array(
        [(float(c) / float(p) - 1.0) if c and p else np.nan for _, c, p in rows],
        dtype=float,
    )
    out: dict[str, tuple[float, float, int]] = {}
    for name, hist in series.items():
        if len(hist) < MIN_OBS:
            continue
        level = _asof(hist, days)
        x = np.full(len(days), np.nan)
        x[1:] = level[1:] / level[:-1] - 1.0  # move between the two previous sessions' as-of
        ok = np.isfinite(x) & np.isfinite(ret) & (np.abs(ret) < 0.25)
        n = int(ok.sum())
        if n < MIN_OBS:
            continue
        xs, ys = x[ok], ret[ok]
        xc = xs - xs.mean()
        sxx = float((xc**2).sum())
        if sxx <= 0:
            continue
        beta = float((xc * (ys - ys.mean())).sum() / sxx)
        resid = ys - ys.mean() - beta * xc
        se = float(np.sqrt((resid**2).sum() / (n - 2) / sxx))
        if se > 0:
            out[name] = (beta, beta / se, n)
    return out


def holding_pressure(
    session: Session,
    instrument_id: int,
    last_close_date: dt.date | None,
    series: dict[str, list[tuple[dt.date, float]]],
    mv: dict[str, Move],
) -> dict[str, Any]:
    """The macro moves that historically mattered for this stock, and the summed pressure."""
    if last_close_date is None:
        return {"items": [], "total": 0.0}
    items: list[dict[str, Any]] = []
    for name, (beta, t, n) in sensitivities(session, instrument_id, series).items():
        m = mv.get(name)
        if m is None or abs(t) < T_MIN:
            continue
        move = m.since(series[name], last_close_date)
        if move is None or move == 0:
            continue
        items.append(
            {
                "series": name,
                "label_fa": m.label_fa,
                "move": move,
                "beta": beta,
                "t": t,
                "n": n,
                "impact": beta * move,
            }
        )
    items.sort(key=lambda i: -abs(i["impact"]))
    total = float(sum(i["impact"] for i in items))
    return {"items": [i for i in items if abs(i["impact"]) >= 0.001], "total": total}


def foreign_headlines(session: Session, since: dt.datetime, limit: int = 8) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(NewsRaw)
        .where(NewsRaw.source.in_(sorted(FOREIGN)), NewsRaw.published_at >= since)
        .order_by(NewsRaw.published_at.desc())
        .limit(200)
    )
    out: list[dict[str, Any]] = []
    for n in rows:
        hits = {w.lower() for w in FOREIGN_WORDS.findall(f"{n.title} {n.summary or ''}")}
        if hits:
            out.append(
                {
                    "title": n.title,
                    "source": n.source,
                    "url": n.url,
                    "at": n.published_at.isoformat() if n.published_at else None,
                    "tags": sorted(hits)[:5],
                    "iran": any(h.startswith(("iran", "tehran", "hormuz")) for h in hits),
                }
            )
    out.sort(key=lambda h: (not h["iran"], -len(h["tags"])))
    return out[:limit]


def market_summary(mv: dict[str, Move]) -> dict[str, Any]:
    """The moves for the page and the briefing, domestic first."""
    rows = [
        {
            "series": m.series,
            "label_fa": m.label_fa,
            "domestic": m.series in DOMESTIC,
            "last": m.last,
            "date": m.last_date.isoformat(),
            "change_1": m.change_1,
            "change_5": m.change_5,
        }
        for m in mv.values()
    ]
    rows.sort(key=lambda r: (not r["domestic"], r["series"]))
    return {"moves": rows}
