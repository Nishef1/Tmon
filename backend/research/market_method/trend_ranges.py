"""Buy and sell ranges for the trend ride: which kind of range earns most after costs?

Report: docs/reports/trend-ranges-2026-11.md. Run from backend/ with the live-data env of
docs/14-local-run.md::

    uv run python research/market_method/trend_ranges.py

Signals are the ``trend_high`` entries of ``tmon.backtest.trend_ride`` on liquid days since
``SINCE``. Every variant is judged on the same signals, per half of time (split at the median
signal date), net of the round-trip cost, with the paired difference to the plain rule (buy at the
next close, sell at 25% under the peak close). A signal that a variant skips counts as cash (0).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr
from tmon.backtest import turning as tp
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel, RuleBook
from tmon.features.store import load_inputs

import os

SINCE = date.fromisoformat(os.environ.get("TRR_SINCE", "2023-11-10"))
OUT = Path(__file__).with_name(os.environ.get("TRR_OUT", "results_trend_ranges.json"))
G = "instrument_id"


def load() -> tuple[pl.DataFrame, float]:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
    panel = tp.build_panel(prices, clients)
    as_of = panel["date"].max()
    cost = CostModel.from_rules(rules, as_of, cfg.costs.slippage_fraction).round_trip  # type: ignore[arg-type]
    return panel, float(cost)


def exit_from(
    close: np.ndarray, fill: int, trail: float | np.ndarray, down: np.ndarray, max_hold: int = 250
) -> tuple[int, float, float, bool]:
    """Sell row, sell price, peak and whether the ride is still open, for a buy at row ``fill``."""
    n = len(close)
    pk = fill
    tl = trail if np.isscalar(trail) else float(trail[fill])  # type: ignore[index]
    for j in range(fill + 1, n):
        if close[j] > close[pk]:
            pk = j
        if close[j] < (1 - tl) * close[pk] or j - fill >= max_hold:
            x = j + 1
            while x < n and down[x]:
                x += 1
            if x >= n:
                return n - 1, close[n - 1], close[pk], True
            return x, close[x], close[pk], False
    return n - 1, close[n - 1], close[pk], True


def collect(panel: pl.DataFrame, rc) -> list[dict]:  # noqa: ANN001
    rows = []
    for (iid,), g in panel.sort(G, "date").group_by([G], maintain_order=True):
        a = tr._symbol_arrays(g)
        close = a["close"]
        hi = g["high"].to_numpy().astype(float)
        lo = g["low"].to_numpy().astype(float)
        d = g["date"].to_list()
        liq = g["liquid"].to_numpy()
        r = g["ret1"].fill_null(0.0).to_numpy()
        vol = (
            g.select(pl.col("ret1").rolling_std(20, min_samples=20).alias("v"))["v"]
            .fill_null(np.nan)
            .to_numpy()
        )
        sig = tr.entry_signals(close, a["sma50"], a["sma200"], a["hi250"], rc.near_high)
        busy = -1
        for t in map(int, np.flatnonzero(sig)):
            if t <= busy or t + 2 >= len(close):
                continue
            if d[t] < SINCE or not liq[t]:
                continue
            rows.append(
                dict(
                    iid=int(iid), t=t, date=d[t], close=close, high=hi, low=lo,
                    up=a["up"], down=a["down"], vol=vol, liq=liq, r=r,
                )
            )  # fmt: skip
            # a later signal of the same symbol is judged only after the plain ride ended
            e = t + 1
            _, _, _, open_ = exit_from(close, e, rc.trail, a["down"], rc.max_hold_days)
            x, _, _, op = exit_from(close, e, rc.trail, a["down"], rc.max_hold_days)
            busy = len(close) if op else x
    return rows


def ride(s: dict, fill: int, price: float, trail, cost: float) -> float:  # noqa: ANN001
    x, px, pk, open_ = exit_from(s["close"], fill, trail, s["down"])
    return px / price - 1 - cost


def plain(s: dict, cost: float, trail: float) -> float | None:
    e = s["t"] + 1
    if s["up"][e]:
        return None
    return ride(s, e, s["close"][e], trail, cost)


def limit_buy(s: dict, d: float, wait: int, ceil: float | None, cost: float, trail: float):
    """Limit buy ``d`` under the signal close, valid ``wait`` days; optional no-chase ceiling."""
    t, c = s["t"], s["close"]
    lim = c[t] * (1 - d)
    for j in range(t + 1, min(t + 1 + wait, len(c) - 1)):
        locked = s["high"][j] == s["low"][j]
        if ceil is not None and j == t + 1 and c[j] > c[t] * (1 + ceil):
            # chasing: the next close is above the ceiling, so only the limit may still fill
            pass
        if not locked and s["low"][j] <= lim:
            return ride(s, j, lim, trail, cost), j - t
    return None, None


def stats(x: np.ndarray) -> dict:
    if len(x) == 0:
        return {"n": 0}
    return {
        "n": int(len(x)),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "p10": float(np.quantile(x, 0.10)),
        "win": float(np.mean(x > 0)),
    }


def boot_ci(x: np.ndarray, months: np.ndarray, reps: int = 2000, seed: int = 1) -> list[float]:
    """95% interval of the mean, resampling whole signal months (signals of a month move together)."""
    rng = np.random.default_rng(seed)
    keys = np.unique(months)
    groups = [x[months == k] for k in keys]
    means = []
    for _ in range(reps):
        pick = rng.integers(0, len(groups), len(groups))
        means.append(float(np.mean(np.concatenate([groups[i] for i in pick]))))
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def main() -> None:
    panel, cost = load()
    rc = get_engine_config().v2.trend_ride
    sigs = collect(panel, rc)
    sigs.sort(key=lambda s: s["date"])
    split = sigs[len(sigs) // 2]["date"]
    half = np.array([0 if s["date"] < split else 1 for s in sigs])
    months = np.array([s["date"].year * 12 + s["date"].month for s in sigs])
    print(f"signals {len(sigs)}  split {split}  cost {cost:.4f}")
    res: dict = {"n_signals": len(sigs), "split": str(split), "cost": cost}

    # ---- 1. buy: limit under the signal close, and a no-chase ceiling -----------------------
    base = [plain(s, cost, rc.trail) for s in sigs]
    ok = np.array([b is not None for b in base])
    basev = np.array([b if b is not None else 0.0 for b in base])
    res["base"] = {"all": stats(basev[ok]), "filled_share": float(ok.mean())}
    buy: dict = {}
    for d in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08):
        for wait in (1, 3, 5, 10):
            v, fills, days = [], [], []
            for s in sigs:
                x, dd = limit_buy(s, d, wait, None, cost, rc.trail)
                v.append(0.0 if x is None else x)
                fills.append(x is not None)
                if dd:
                    days.append(dd)
            v = np.array(v)
            f = np.array(fills)
            diff = v - basev
            entry = {
                "fill": float(f.mean()),
                "per_signal_mean": float(v.mean()),
                "per_signal_halves": [float(v[half == h].mean()) for h in (0, 1)],
                "diff_mean": float(diff.mean()),
                "diff_halves": [float(diff[half == h].mean()) for h in (0, 1)],
                "t": float(diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))),
                "when_filled": stats(v[f]),
            }
            buy[f"d{d}_w{wait}"] = entry
    res["buy_limit"] = buy
    ceil: dict = {}
    for u in (0.01, 0.02, 0.03, 0.05, 0.08):
        v = []
        for s in sigs:
            e = s["t"] + 1
            ok_e = (not s["up"][e]) and s["close"][e] <= s["close"][s["t"]] * (1 + u)
            v.append(ride(s, e, s["close"][e], rc.trail, cost) if ok_e else 0.0)
        v = np.array(v)
        diff = v - basev
        ceil[f"u{u}"] = {
            "taken": float(np.mean(v != 0.0)),
            "per_signal_halves": [float(v[half == h].mean()) for h in (0, 1)],
            "diff_halves": [float(diff[half == h].mean()) for h in (0, 1)],
            "t": float(diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))),
        }
    res["buy_ceiling"] = ceil
    gp = np.array([s["close"][s["t"] + 1] / s["close"][s["t"]] - 1 for s in sigs])
    res["entry_vs_signal_close"] = {
        "q": {str(q): float(np.quantile(gp, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "halves": [
            {str(q): float(np.quantile(gp[half == h], q)) for q in (0.1, 0.5, 0.9)} for h in (0, 1)
        ],
    }
    res["base_per_signal"] = {
        "mean": float(basev.mean()),
        "halves": [float(basev[half == h].mean()) for h in (0, 1)],
        "ci95": boot_ci(basev, months),
    }

    # ---- 2. sell: width of the trailing line (fixed and by the symbol's own volatility) ------
    sell: dict = {}
    entries = [(s, s["t"] + 1) for s in sigs if not s["up"][s["t"] + 1]]
    for label, mk in [
        *[
            (f"fixed{int(w * 100)}", (lambda s, e, w=w: w))
            for w in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
        ],
        *[
            (
                f"vol{k}",
                (
                    lambda s, e, k=k: (
                        float(np.clip(k * s["vol"][e] * np.sqrt(20), 0.10, 0.50))
                        if np.isfinite(s["vol"][e])
                        else 0.25
                    )
                ),
            )
            for k in (1.5, 2.0, 2.5, 3.0, 4.0)
        ],
    ]:
        v, hold, h = [], [], []
        for s, e in entries:
            tl = mk(s, e)
            x, px, pk, op = exit_from(s["close"], e, tl, s["down"])
            v.append(px / s["close"][e] - 1 - cost)
            hold.append(x - e)
            h.append(0 if s["date"] < split else 1)
        v = np.array(v)
        h = np.array(h)
        sell[label] = {
            **stats(v),
            "halves": [float(v[h == k].mean()) for k in (0, 1)],
            "median_halves": [float(np.median(v[h == k])) for k in (0, 1)],
            "p10_halves": [float(np.quantile(v[h == k], 0.1)) for k in (0, 1)],
            "hold_median": float(np.median(hold)),
        }
    res["sell_trail"] = sell
    # paired: the same entries sold at a wider line against the 25% line
    paired: dict = {}
    mon = np.array([s["date"].year * 12 + s["date"].month for s, _ in entries])
    hh = np.array([0 if s["date"] < split else 1 for s, _ in entries])
    ref = np.array([ride(s, e, s["close"][e], 0.25, cost) for s, e in entries])
    for w in (0.30, 0.35, 0.40, 0.50):
        v = np.array([ride(s, e, s["close"][e], w, cost) for s, e in entries])
        d = v - ref
        paired[f"trail{int(w * 100)}_minus_25"] = {
            "mean": float(d.mean()),
            "halves": [float(d[hh == k].mean()) for k in (0, 1)],
            "t": float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))),
            "ci95_by_month": boot_ci(d, mon),
            "share_better": float(np.mean(d > 0)),
            "share_equal": float(np.mean(d == 0)),
        }
    res["sell_paired"] = paired

    # ---- 3. sell range: where the sale lands against the stop line (trail breaks only) -----
    sr: dict = {}
    for w in (0.25, 0.35):
        land = {0: [], 1: []}
        for s in sigs:
            e = s["t"] + 1
            if s["up"][e]:
                continue
            x, px, pk, op = exit_from(s["close"], e, w, s["down"])
            if op or x - e >= 250:
                continue
            land[0 if s["date"] < split else 1].append(px / ((1 - w) * pk))
        blk: dict = {}
        for hh in (0, 1):
            a = np.array(land[hh])
            blk[f"half{hh}"] = {
                "n": int(len(a)),
                "q": {str(q): float(np.quantile(a, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            }
        for src, dst in ((0, 1), (1, 0)):
            lo, hi = np.quantile(land[src], [0.1, 0.9])
            t = np.array(land[dst])
            blk[f"cover_{src}to{dst}"] = float(np.mean((t >= lo) & (t <= hi)))
        sr[f"trail{int(w * 100)}"] = blk
    res["sell_range"] = sr

    # ---- 4. one-month price range after the signal (calibration, plain and by volatility) ----
    fw, z = [], []
    for s in sigs:
        e = s["t"] + 1
        if e + 20 >= len(s["close"]) or s["up"][e] or not np.isfinite(s["vol"][e]):
            fw.append(np.nan)
            z.append(np.nan)
            continue
        r20 = s["close"][e + 20] / s["close"][e] - 1
        fw.append(r20)
        z.append(r20 / (s["vol"][e] * np.sqrt(20)))
    fw = np.array(fw)
    z = np.array(z)
    mr = {}
    for src, dst in ((0, 1), (1, 0)):
        tr_ = fw[(half == src) & np.isfinite(fw)]
        te = (half == dst) & np.isfinite(fw)
        lo, hi = np.quantile(tr_, [0.1, 0.9])
        zl, zh = np.quantile(z[(half == src) & np.isfinite(z)], [0.1, 0.9])
        sg = np.array([s["vol"][s["t"] + 1] * np.sqrt(20) for s in sigs])
        plain_cov = float(np.mean((fw[te] >= lo) & (fw[te] <= hi)))
        vol_cov = float(np.mean((fw[te] >= zl * sg[te]) & (fw[te] <= zh * sg[te])))
        mr[f"{src}to{dst}"] = {
            "plain_range": [float(lo), float(hi)],
            "plain_cover": plain_cov,
            "plain_width": float(hi - lo),
            "vol_z": [float(zl), float(zh)],
            "vol_cover": vol_cov,
            "vol_width_mean": float(np.mean((zh - zl) * sg[te])),
        }
    res["month_range"] = mr
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("base", "base_per_signal")}, indent=1))


if __name__ == "__main__":
    main()
