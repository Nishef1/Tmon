"""Industry map for the industries page (docs/reports/correlation-map-2026-11.md).

``python -m tmon.tools.industry_map`` writes one JSON document (object store key
``v2/industry_map.json``). From the weekly returns of the last three years it describes each
industry: how hard it moves with the market (beta), how its move beyond the market tracks the
free-market dollar in each half of the window, how tightly its stocks move together, where it sits
on the export-domestic axis of the industries' residual co-movement, and its recent return.

Universe: stocks among the 300 with the highest 20-day median traded value (known the day
before) on at least 60% of the window's trading days. Weeks run Saturday to Wednesday; a week after
a gap of more than 14 days is dropped. Industries need at least 3 such stocks.

Descriptive only. The report found no lead from the dollar or between industries that survives
both halves and costs, so nothing here is a buy or sell signal.
"""

from __future__ import annotations

import argparse
import warnings
from datetime import date, timedelta
from typing import Any, cast

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.core.db import session_scope
from tmon.domain.enums import InstrumentType
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs
from tmon.storage.models import Instrument, MacroSeries, SectorName
from tmon.storage.objectstore import write_artifact

KEY = "v2/industry_map.json"
C = pl.col
G = "instrument_id"
WINDOW_DAYS = 1095  # last three years (focus of the studies)
TOP = 300
MEMBER_SHARE = 0.6
MIN_STOCKS = 3
MAX_GAP_DAYS = 14
# Residual dollar correlation that counts as a tie: the cut the report used to pick
# dollar-linked industries (correlation-map-2026-11, section 3).
DOLLAR_TIE = 0.15
SHOW_SYMBOLS = 8
# Display cut only: the outer thirds of the axis are named export-side and domestic-side.
# Not tested for any use (OPEN_QUESTIONS 126).
GROUP_CUT = 1 / 3


def _corr(a: np.ndarray, b: np.ndarray, min_n: int = 20) -> float | None:
    ok = ~np.isnan(a) & ~np.isnan(b)
    if ok.sum() < min_n or a[ok].std() == 0 or b[ok].std() == 0:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def _beta(y: np.ndarray, m: np.ndarray) -> float | None:
    ok = ~np.isnan(y) & ~np.isnan(m)
    if ok.sum() < 20:
        return None
    return float(np.cov(y[ok], m[ok])[0, 1] / m[ok].var(ddof=1))


def _resid(y: np.ndarray, m: np.ndarray) -> np.ndarray:
    b = _beta(y, m)
    return np.full_like(y, np.nan) if b is None else y - b * m


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or np.isnan(x) else round(x, nd)


def _load() -> tuple[pl.DataFrame, dict[int, tuple[str, str]], pl.DataFrame]:
    with session_scope() as s:
        prices, _, _ = load_inputs(s)
        names: dict[str, str] = dict(s.execute(select(SectorName.code, SectorName.name)).all())
        inst = s.execute(
            select(Instrument.id, Instrument.symbol_fa, Instrument.sector_code).where(
                Instrument.instrument_type == InstrumentType.STOCK.value
            )
        ).all()
        usd = pl.DataFrame(
            s.execute(
                select(MacroSeries.ref_period, MacroSeries.value).where(
                    MacroSeries.series == "usd_free"
                )
            ).all(),
            schema={"date": pl.Date, "value": pl.Float64},
            orient="row",
        )
    meta = {
        i: (sym, names.get(code or "", code or "")) for i, sym, code in inst if code is not None
    }
    p = (
        apply_adjustments(prices)
        .filter(C(G).is_in(list(meta)) & ~C("market_halt") & (C("close") > 0))
        .with_columns(C("date").cast(pl.Date), C("value").cast(pl.Float64))
        .sort(G, "date")
    )
    return p, meta, usd


def _universe(p: pl.DataFrame, start: date) -> pl.DataFrame:
    """Ids in the top ``TOP`` by prior 20-day median value on enough days, with the latest median
    value (to list the most traded symbols first)."""
    v = p.with_columns(med=C("value").rolling_median(20).shift(1).over(G)).drop_nulls("med")
    v = v.filter(C("date") >= start).with_columns(
        rk=C("med").rank("ordinal", descending=True).over("date")
    )
    n_days = v["date"].n_unique()
    return (
        v.group_by(G)
        .agg(share=(C("rk") <= TOP).sum() / n_days, med=C("med").last())
        .filter(C("share") >= MEMBER_SHARE)
    )


def _weekly(
    p: pl.DataFrame, ids: list[int], start: date
) -> tuple[list[date], list[int], np.ndarray]:
    w = (
        p.filter(C(G).is_in(ids) & (C("date") >= start - timedelta(days=10)))
        .with_columns(week=(C("date") + pl.duration(days=2)).dt.truncate("1w"))
        .group_by(G, "week")
        .agg(close=C("adj_close").last())
        .sort(G, "week")
        .with_columns(ret=(C("close") / C("close").shift(1) - 1).over(G))
        .filter(C("week") >= start)
    )
    weeks = sorted(w["week"].unique().to_list())
    keep = [k for k, d in enumerate(weeks) if k == 0 or (d - weeks[k - 1]).days <= MAX_GAP_DAYS]
    weeks = [weeks[k] for k in keep]
    cols = sorted(w[G].unique().to_list())
    wi = {d: k for k, d in enumerate(weeks)}
    ci = {c: k for k, c in enumerate(cols)}
    mat = np.full((len(weeks), len(cols)), np.nan)
    for c, d, r in w.select(G, "week", "ret").drop_nulls().iter_rows():
        if d in wi:
            mat[wi[d], ci[c]] = r
    return weeks, cols, np.clip(mat, -0.6, 1.5)


def _usd_weekly(usd: pl.DataFrame, weeks: list[date]) -> np.ndarray:
    # Thursday to Wednesday, so the Thursday-Friday dollar move counts toward the stock week
    # that first trades on it.
    u = (
        usd.sort("date")
        .with_columns(week=(C("date") + pl.duration(days=4)).dt.truncate("1w"))
        .group_by("week")
        .agg(v=C("value").last())
        .sort("week")
        .with_columns(chg=C("v") / C("v").shift(1) - 1)
    )
    by = dict(zip(u["week"].to_list(), u["chg"].to_list(), strict=True))
    return np.array([np.nan if by.get(d) is None else by[d] for d in weeks], dtype=float)


def _cohesion(res: np.ndarray) -> float | None:
    """Mean pairwise correlation of the members' residual returns."""
    vals = [
        c
        for i in range(res.shape[1])
        for j in range(i + 1, res.shape[1])
        if (c := _corr(res[:, i], res[:, j], 40)) is not None
    ]
    return float(np.mean(vals)) if vals else None


def _compound(x: np.ndarray) -> float | None:
    x = x[~np.isnan(x)]
    return float(np.prod(1 + x) - 1) if len(x) else None


def build_document() -> dict[str, Any]:
    p, meta, usd = _load()
    as_of = cast("date", p["date"].max())
    start = as_of - timedelta(days=WINDOW_DAYS)
    uni = _universe(p, start)
    weeks, cols, r = _weekly(p, uni[G].to_list(), start)
    med = dict(zip(uni[G].to_list(), uni["med"].to_list(), strict=True))
    m = np.nanmean(r, axis=1)
    res_stock = np.column_stack([_resid(r[:, k], m) for k in range(len(cols))])
    mid = len(weeks) // 2
    du = _usd_weekly(usd, weeks)

    members: dict[str, list[int]] = {}
    for k, c in enumerate(cols):
        members.setdefault(meta[c][1], []).append(k)
    sectors = sorted(s for s, ks in members.items() if len(ks) >= MIN_STOCKS)
    with warnings.catch_warnings():  # a week where none of an industry's stocks traded
        warnings.simplefilter("ignore", RuntimeWarning)
        idx = np.column_stack([np.nanmean(r[:, members[s]], axis=1) for s in sectors])
    res_idx = np.column_stack([_resid(idx[:, j], m) for j in range(len(sectors))])

    n = len(sectors)
    corr = np.full((n, n), np.nan)
    for a in range(n):
        for b in range(n):
            corr[a, b] = 1.0 if a == b else (_corr(res_idx[:, a], res_idx[:, b], 40) or np.nan)
    # export-domestic axis: the first principal component of the industries' residual
    # correlation, signed so that the dollar-linked side is positive
    vals, vecs = np.linalg.eigh(np.nan_to_num(corr))
    axis = vecs[:, -1]
    factor = np.nan_to_num(res_idx) @ axis
    if (_corr(factor, du) or 0.0) < 0:
        axis, factor = -axis, -factor
    axis_share = float(vals[-1] / vals.sum())
    axis_scale = float(np.abs(axis).max())

    rows: list[dict[str, Any]] = []
    for j, s in enumerate(sectors):
        e = res_idx[:, j]
        usd_all, usd_h1, usd_h2 = (
            _corr(e, du),
            _corr(e[:mid], du[:mid]),
            _corr(e[mid:], du[mid:]),
        )
        tie = "none"
        if usd_h1 is not None and usd_h2 is not None:
            if min(usd_h1, usd_h2) >= DOLLAR_TIE / 2 and (usd_all or 0) >= DOLLAR_TIE:
                tie = "up_steady"
            elif max(usd_h1, usd_h2) <= -DOLLAR_TIE / 2 and (usd_all or 0) <= -DOLLAR_TIE:
                tie = "down_steady"
            elif (usd_all or 0) >= DOLLAR_TIE or max(usd_h1, usd_h2) >= DOLLAR_TIE:
                tie = "up_unsteady"
            elif (usd_all or 0) <= -DOLLAR_TIE or min(usd_h1, usd_h2) <= -DOLLAR_TIE:
                tie = "down_unsteady"
        ks = sorted(members[s], key=lambda k: -(med.get(cols[k]) or 0))
        peers = sorted(
            ((sectors[b], corr[j, b]) for b in range(n) if b != j and not np.isnan(corr[j, b])),
            key=lambda x: -x[1],
        )
        ax = float(axis[j] / axis_scale)
        group = "export" if ax >= GROUP_CUT else "domestic" if ax <= -GROUP_CUT else "middle"
        rows.append(
            {
                "sector": s,
                "group": group,
                "n_stocks": len(ks),
                "symbols": [meta[cols[k]][0] for k in ks[:SHOW_SYMBOLS]],
                "beta": _r(_beta(idx[:, j], m)),
                "cohesion": _r(_cohesion(res_stock[:, ks])),
                "axis": _r(ax),
                "usd_corr": _r(usd_all),
                "usd_corr_h1": _r(usd_h1),
                "usd_corr_h2": _r(usd_h2),
                "dollar_tie": tie,
                "ret_4w": _r(_compound(idx[-4:, j]), 4),
                "ret_13w": _r(_compound(idx[-13:, j]), 4),
                "ret_52w": _r(_compound(idx[-52:, j]), 4),
                "vs_market_13w": _r((_compound(idx[-13:, j]) or 0) - (_compound(m[-13:]) or 0), 4),
                "closest": [{"sector": x, "corr": round(float(c), 2)} for x, c in peers[:3]],
            }
        )
    rows.sort(key=lambda x: -(x["axis"] or 0))
    order = [x["sector"] for x in rows]
    pos = {s: k for k, s in enumerate(sectors)}
    return {
        "as_of": str(as_of),
        "start": str(weeks[0]),
        "mid": str(weeks[mid]),
        "n_weeks": len(weeks),
        "n_stocks": len(cols),
        "dollar_tie_cut": DOLLAR_TIE,
        "group_cut": round(GROUP_CUT, 2),
        "axis_share": round(axis_share, 3),
        "market": {
            "ret_4w": _r(_compound(m[-4:]), 4),
            "ret_13w": _r(_compound(m[-13:]), 4),
            "ret_52w": _r(_compound(m[-52:]), 4),
        },
        "sectors": rows,
        "corr": {
            "order": order,
            "values": [
                [None if np.isnan(v := corr[pos[a], pos[b]]) else round(float(v), 2) for b in order]
                for a in order
            ],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-industry-map")
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document()
    write_artifact(KEY, doc, a.out)
    print(
        f"as_of={doc['as_of']} weeks={doc['n_weeks']} stocks={doc['n_stocks']} "
        f"sectors={len(doc['sectors'])} axis_share={doc['axis_share']}"
    )
    for x in doc["sectors"]:
        print(
            f"{x['axis']:+.2f} usd={x['usd_corr']} h1={x['usd_corr_h1']} h2={x['usd_corr_h2']} "
            f"{x['dollar_tie']:13s} b={x['beta']} coh={x['cohesion']} n={x['n_stocks']} "
            f"{x['sector']}"
        )


if __name__ == "__main__":
    main()
