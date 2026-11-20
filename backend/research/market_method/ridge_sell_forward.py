"""Forward test of the frozen ridge sell side (OPEN_QUESTIONS 142).

Report: docs/reports/columns-deep-2026-11.md.

In columns_deep.py the ridge combination of the derived columns, fitted on the residual of the v2
four-signal score, made the bottom tenth of 60-day returns worse in three windows, but it did not
survive a correction for about 12 tests and its weight is mostly high beta (one bull regime). The
only honest next check is forward: the weights are fixed today and never refitted, and from now on
the bottom tenth it marks is compared with the bottom tenth of the plain v2 score.

  freeze    fit the 60-day ridge once on every label known today (same lambda, columns and
            centring as columns_deep.rank) and write docs/data/ridge-sell-frozen.json. It refuses
            to overwrite an existing file: refreezing would make the forward test meaningless.
  log       for every date of data/columns-deep/panel.parquet after the freeze day (run
            `columns_deep.py build` first, about once a month), append the bottom tenth of the
            frozen score and of the v2 score to data/ridge-sell-forward.jsonl (one line per date;
            a date already logged is skipped).
  evaluate  for logged dates whose 60-day outcome is now known, the mean excess over the day's
            members of each bottom tenth, and the gap (v2 bottom minus ridge bottom; positive means
            the ridge found the worse stocks). Writes docs/data/ridge-sell-forward.json.

Nothing here touches the production ranking. Run from backend/ with the live env:
  python research/market_method/ridge_sell_forward.py freeze|log|evaluate
"""

# ruff: noqa: N803, N806
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import columns_deep as cd

from tmon.core.timeutil import tehran_today

C = pl.col
G = "instrument_id"
H = 60
FROZEN = cd.OUT / "ridge-sell-frozen.json"
LOG = cd.ROOT / "data" / "ridge-sell-forward.jsonl"
RESULT = cd.OUT / "ridge-sell-forward.json"


def _panel() -> tuple[pl.DataFrame, list[str], list[str]]:
    """The v2 panel with the same centring as columns_deep.rank: every column as its percentile
    rank inside the day's members minus 0.5, the base signals minus 0.5."""
    from tmon.backtest.signal_decay import SIGNALS

    p = pl.read_parquet(cd.CACHE / "panel.parquet").filter(C("v2_ok"))
    cols = [c for c in cd._col_list() if c != "depth_vs_usual"]
    base = [f"r_{s}" for s in SIGNALS]
    p = p.with_columns(
        *[((C(c).rank("average").over("date") - 0.5) / C(c).count().over("date") - 0.5).alias(c)
          for c in cols],
        *[(C(b) - 0.5).alias(b) for b in base],
    )  # fmt: skip
    return p, cols, base


def score(Xe: np.ndarray, Xb: np.ndarray, w: np.ndarray) -> np.ndarray:
    """The combined score of columns_deep.rank: base and column part on one scale, equal say."""
    bs = Xb.mean(1)
    add = Xe @ w
    return bs / (bs.std() + 1e-12) + add / (add.std() + 1e-12)


def bottom(sc: np.ndarray, ids: np.ndarray) -> list[int]:
    nd = max(sc.size // 10, 5)
    return [int(x) for x in ids[np.argsort(sc)[:nd]]]


def freeze() -> dict[str, Any]:
    if FROZEN.exists():
        raise SystemExit(f"{FROZEN} exists; the weights are frozen and must not be refitted")
    p, cols, base = _panel()
    q = p.filter(C(f"fwd_{H}").is_not_null())
    q = q.with_columns(
        y=(C(f"fwd_{H}").rank("average").over("date") - 0.5) / C(f"fwd_{H}").count().over("date")
        - 0.5
    )
    k = len(cols)
    Gm = np.zeros((k, k))
    bv = np.zeros(k)
    for part in q.partition_by("date"):
        Xt = np.nan_to_num(part.select(cols).to_numpy().astype(float))
        bs = np.nan_to_num(part.select(base).to_numpy().astype(float)).mean(1)
        y = part["y"].to_numpy().astype(float)
        resid = y - (bs @ y) / max(bs @ bs, 1e-12) * bs
        Gm += Xt.T @ Xt
        bv += Xt.T @ resid
    lam = cd.LAMBDA * float(np.mean(np.diag(Gm))) + 1e-9
    w = np.linalg.solve(Gm + lam * np.eye(k), bv)
    out = {
        "frozen_on": str(tehran_today()),
        "labels_through": str(q["date"].max()),
        "horizon": H,
        "lambda": cd.LAMBDA,
        "base": base,
        "rule": "bottom tenth of score() among the day's v2 members is the sell-side flag",
        "weights": {c: float(x) for c, x in zip(cols, w, strict=True)},
    }
    FROZEN.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    top = sorted(out["weights"].items(), key=lambda kv: -abs(kv[1]))[:8]
    print("frozen", out["labels_through"], top)
    return out


def log() -> None:
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    p, cols, base = _panel()
    if cols != list(fz["weights"]) or base != fz["base"]:
        raise SystemExit("the column list changed since the freeze; the frozen test cannot run")
    done = set()
    if LOG.exists():
        done = {json.loads(x)["date"] for x in LOG.read_text(encoding="utf-8").splitlines() if x}
    # every date after the freeze is out of sample, so a rebuild once a month logs them all
    days = sorted(
        d for d in p["date"].unique().to_list()
        if str(d) > fz["frozen_on"] and str(d) not in done
    )  # fmt: skip
    w = np.array([fz["weights"][c] for c in cols])
    with LOG.open("a", encoding="utf-8") as fh:
        for day in days:
            t = p.filter(C("date") == day)
            Xe = np.nan_to_num(t.select(cols).to_numpy().astype(float))
            Xb = np.nan_to_num(t.select(base).to_numpy().astype(float))
            ids = t[G].to_numpy()
            row = {
                "date": str(day),
                "members": int(ids.size),
                "ridge_bottom": bottom(score(Xe, Xb, w), ids),
                "v2_bottom": bottom(Xb.mean(1), ids),
            }
            fh.write(json.dumps(row) + "\n")
    print("logged", len(days), "new dates after", fz["frozen_on"])


def evaluate() -> dict[str, Any]:
    rows = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x]
    p = pl.read_parquet(cd.CACHE / "panel.parquet").filter(C("v2_ok"))
    p = p.filter(C(f"fwd_{H}").is_not_null()).with_columns(
        ex=C(f"fwd_{H}") - C(f"fwd_{H}").mean().over("date")
    )
    ex = {(str(d), int(i)): float(x) for d, i, x in p.select("date", G, "ex").iter_rows()}
    known = []
    for r in rows:
        rb = [ex[(r["date"], i)] for i in r["ridge_bottom"] if (r["date"], i) in ex]
        vb = [ex[(r["date"], i)] for i in r["v2_bottom"] if (r["date"], i) in ex]
        if rb and vb:
            known.append({"date": r["date"], "ridge": np.mean(rb), "v2": np.mean(vb)})
    gap = np.array([k["v2"] - k["ridge"] for k in known])
    out = {
        "logged_dates": len(rows),
        "dates_with_outcome": len(known),
        "mean_ridge_bottom_excess": float(np.mean([k["ridge"] for k in known])) if known else None,
        "mean_v2_bottom_excess": float(np.mean([k["v2"] for k in known])) if known else None,
        "mean_gap": float(gap.mean()) if gap.size else None,
        "share_of_dates_ridge_worse": float((gap > 0).mean()) if gap.size else None,
        "note": "overlapping 60-day windows: about one independent reading per 60 trading days",
        "by_date": known,
    }
    RESULT.write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8"
    )
    print({k: v for k, v in out.items() if k != "by_date"})
    return out


if __name__ == "__main__":
    {"freeze": freeze, "log": log, "evaluate": evaluate}[sys.argv[1]]()
