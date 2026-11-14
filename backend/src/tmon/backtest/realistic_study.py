"""A portfolio simulator that cannot trade where the market would not let it.

``parameter_study.simulate`` buys every selected name at the next close and sells at a later close,
with no queues and no size. This one adds what actually stops a trade on the Tehran exchange:

* **Buy queue:** a name whose close is at the upper price limit (``queue_state == buy_queue``)
  cannot be bought that day; the order waits for the next day that is not in a buy queue, at most
  ``MAX_WAIT_BUY`` days, then the slot stays in cash.
* **Sell queue:** a name that closes at the lower limit cannot be sold; the exit is the first later
  close not in a sell queue (at most ``MAX_WAIT_SELL`` days, else the last close reached).
* **Size:** each position is ``notional / names`` rial and may take at most ``PARTICIPATION`` of
  the day's traded value; the part that cannot be filled stays in cash (earning nothing).
* **Cost** on every buy and sell (half of the round trip each).

The benchmark is the median stock over the same period. Results are per review period, compounded
(CAGR) and by calendar year, so an edge that fades shows up.

``python -m tmon.backtest.realistic_study`` writes ``docs/data/realistic-study.json``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.parameter_study import HS, MIN_N, G, build, composite, sig_cols
from tmon.features.builder import KEYS

MAX_WAIT_BUY = 3
MAX_WAIT_SELL = 10
PARTICIPATION = 0.10


@dataclass
class Calendar:
    """One instrument's trading calendar: ordinal dates, adjusted close, locks and traded value."""

    day: np.ndarray[Any, Any]
    px: np.ndarray[Any, Any]
    buy_locked: np.ndarray[Any, Any]
    sell_locked: np.ndarray[Any, Any]
    value: np.ndarray[Any, Any]


def make_paths(paths: pl.DataFrame) -> dict[int, Calendar]:
    p = paths.sort(KEYS).with_columns(pl.col("date").dt.epoch("d").alias("_d"))
    out: dict[int, Calendar] = {}
    for key, g in p.group_by(G, maintain_order=True):
        iid = int(key[0])
        qs = g["queue_state"].fill_null("none")
        out[iid] = Calendar(
            day=g["_d"].to_numpy(),
            px=g["adj_close"].to_numpy().astype(float),
            buy_locked=(qs == "buy_queue").to_numpy(),
            sell_locked=(qs == "sell_queue").to_numpy(),
            value=g["value"].fill_null(0.0).to_numpy().astype(float),
        )
    return out


def _first_free(locked: np.ndarray[Any, Any], start: int, wait: int) -> int | None:
    """First index in ``[start, start + wait]`` that is not locked, else ``None``."""
    for k in range(start, min(start + wait + 1, locked.size)):
        if not locked[k]:
            return k
    return None


def simulate_real(
    d: pl.DataFrame,
    paths: dict[int, Calendar],
    *,
    buy: float,
    hold: float,
    n_names: int,
    review: int,
    cost: float,
    notional: float | None,
    locks: bool = True,
    score: str = "score",
) -> dict[str, Any]:
    """Equal-weight book reviewed every ``review`` dates; see the module docstring."""
    h = review
    dates = d["date"].unique().sort().to_list()
    sel = (
        d.select("date", G, score, f"fwd_{h}").drop_nulls(score).partition_by("date", as_dict=True)
    )
    held: dict[int, float] = {}  # instrument -> basis price
    net: list[float] = []
    bench: list[float] = []
    when: list[date] = []
    turns: list[float] = []
    invested: list[float] = []
    gross_l: list[float] = []
    missed = 0
    wanted = 0
    fills: list[float] = []
    prev_p: pl.DataFrame | None = None
    prev_date: date | None = None
    prev_weights: dict[int, float] = {}
    m_prev = 1

    for i in range(0, len(dates), review):
        day = dates[i]
        p = sel.get((day,))
        if p is None or p.height < MIN_N:
            continue
        ids = p[G].to_numpy()
        sc = p[score].to_numpy()
        rk = 1.0 - (sc.argsort().argsort() + 0.5) / len(sc)
        order = {int(x): float(r) for x, r in zip(ids, rk, strict=True)}
        keep = {x for x in held if order.get(x, 1.0) <= hold}
        cands = sorted(
            (x for x, r in order.items() if r <= buy and x not in keep), key=lambda x: order[x]
        )
        new = keep | set(cands[: max(n_names - len(keep), 0)])
        m = max(len(new), 1)  # equal weight over the names actually selected today
        slot = (notional / m) if notional else None
        ordinal = day.toordinal() - date(1970, 1, 1).toordinal()

        def pos_of(iid: int, _o: int = ordinal) -> int | None:
            pth = paths.get(iid)
            if pth is None:
                return None
            k = int(np.searchsorted(pth.day, _o))
            return k if k < pth.day.size and pth.day[k] == _o else None

        # close the period that ends today for the names held during it
        if held and prev_date is not None and prev_p is not None:
            rets: list[float] = []
            for iid, basis in held.items():
                pth = paths[iid]
                k = pos_of(iid)
                if k is None or k + 1 >= pth.px.size:
                    rets.append(0.0)
                    continue
                if iid in new:
                    end = pth.px[k + 1]
                else:
                    if locks:
                        j = _first_free(pth.sell_locked, k + 1, MAX_WAIT_SELL)
                        end = pth.px[
                            j if j is not None else min(k + 1 + MAX_WAIT_SELL, pth.px.size - 1)
                        ]
                    else:
                        end = pth.px[k + 1]
                rets.append(prev_weights.get(iid, 0.0) * (end / basis - 1.0))
            gross = float(np.sum(rets))
            med = float(np.nanmedian(prev_p[f"fwd_{h}"].to_numpy()))
            buys = [x for x in new if x not in held]
            sells = [x for x in held if x not in new]
            c = (
                cost
                / 2
                * (
                    sum(prev_weights.get(x, 1.0 / m_prev) for x in sells)
                    + sum(1.0 / m for x in buys)
                )
            )
            net.append(gross - c)
            gross_l.append(gross)
            invested.append(float(sum(prev_weights.values())))
            bench.append(med)
            when.append(prev_date)
            turns.append((len(buys) + len(sells)) / (2 * max(len(new), 1)))

        # open today's book
        new_held: dict[int, float] = {}
        weights: dict[int, float] = {}
        for iid in new:
            cal = paths.get(iid)
            k = pos_of(iid)
            if cal is None or k is None or k + 1 >= cal.px.size:
                continue
            if iid in held:
                new_held[iid] = float(cal.px[k + 1])  # mark: next close, same grid as the benchmark
                weights[iid] = prev_weights.get(iid, 1.0 / m)
                continue
            wanted += 1
            if locks:
                j = _first_free(cal.buy_locked, k + 1, MAX_WAIT_BUY)
                if j is None:
                    missed += 1
                    continue
            else:
                j = k + 1
            f = 1.0
            if slot is not None:
                cap = PARTICIPATION * float(cal.value[j])
                f = 1.0 if slot <= 0 else min(1.0, cap / slot)
                if f <= 0:
                    missed += 1
                    continue
            fills.append(f)
            new_held[iid] = float(cal.px[j])
            weights[iid] = f / m
        held = new_held
        prev_weights = weights
        m_prev = m
        prev_p = p
        prev_date = day
    ok = np.isfinite(np.array(net)) & np.isfinite(
        np.array(bench)
    )  # last date has no forward return
    net_a, bench_a = np.array(net)[ok], np.array(bench)[ok]
    a = net_a - bench_a
    if a.size < 20:
        return {"n": int(a.size)}
    per_year = 250 / review
    pn = net_a
    cagr = float(np.prod(1 + pn) ** (per_year / pn.size) - 1)
    cagr_b = float(np.prod(1 + bench_a) ** (per_year / pn.size) - 1)
    years = np.array([w.year for w in when])[ok]
    by_year = {
        str(y): float(a[years == y].mean() * per_year)
        for y in sorted(set(years.tolist()))
        if (years == y).sum() >= 8
    }
    return {
        "n": int(a.size),
        "net_excess_annual": float(a.mean() * per_year),
        "t": float(a.mean() / (a.std(ddof=1) / math.sqrt(a.size))) if a.std() > 0 else None,
        "cagr": cagr,
        "cagr_benchmark": cagr_b,
        "pos": float((a > 0).mean()),
        "turnover": float(np.mean(np.array(turns)[ok])),
        "invested": float(np.mean(invested)),
        "gross_mean": float(np.nanmean(gross_l)),
        "bench_mean": float(np.mean(bench_a)),
        "missed_buys": missed / wanted if wanted else 0.0,
        "mean_fill": float(np.mean(fills)) if fills else None,
        "early": float(a[: a.size // 2].mean() * per_year),
        "late": float(a[a.size // 2 :].mean() * per_year),
        "by_year": by_year,
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-realistic-study")
    ap.add_argument("--out", default=str(Path("docs/data/realistic-study.json")))
    args = ap.parse_args()
    df, cost, raw_paths = build()
    paths = make_paths(raw_paths)
    base = composite(df, sig_cols())
    top100 = base.with_columns(
        pl.col("median_value_20").rank("ordinal", descending=True).over("date").alias("_lr")
    ).filter(pl.col("_lr") <= 100)
    res: dict[str, Any] = {
        "cost": cost,
        "max_wait_buy": MAX_WAIT_BUY,
        "max_wait_sell": MAX_WAIT_SELL,
        "participation": PARTICIPATION,
    }

    def prod(
        frame: pl.DataFrame, review: int, notional: float | None, locks: bool
    ) -> dict[str, Any]:
        """The production rules (buy 10 %, keep 30 %, 20 names) under the given realism."""
        return simulate_real(
            frame,
            paths,
            buy=0.1,
            hold=0.3,
            n_names=20,
            review=review,
            cost=cost,
            notional=notional,
            locks=locks,
        )

    ladder: dict[str, Any] = {}
    for uni, frame in (("all", base), ("liquid100", top100)):
        for review in (5, 20):
            ladder[f"{uni}_R{review}_ideal"] = prod(frame, review, None, False)
            ladder[f"{uni}_R{review}_locks"] = prod(frame, review, None, True)
            for n in (1e7, 1e8, 1e9, 1e10, 1e11):
                ladder[f"{uni}_R{review}_locks_N{n:.0e}"] = prod(frame, review, n, True)
            print("ladder", uni, review, flush=True)
    res["ladder"] = ladder

    # what a score with no information earns under the same rules: the benchmark (median stock) is
    # not the mean stock, so an equal-weight book beats it a little by construction; the cost drag
    # is the turnover a random ranking causes.
    rng = np.random.default_rng(7)
    rand: dict[str, Any] = {}
    for review in (5, 20):
        for tag, c in (("zero_cost", 0.0), ("with_cost", cost)):
            runs = []
            for _ in range(5):
                rb = base.with_columns(pl.Series("rscore", rng.normal(size=base.height)))
                runs.append(
                    simulate_real(
                        rb,
                        paths,
                        buy=0.1,
                        hold=0.3,
                        n_names=20,
                        review=review,
                        cost=c,
                        notional=None,
                        locks=True,
                        score="rscore",
                    )
                )
            rand[f"R{review}_{tag}"] = {
                k: float(np.mean([r[k] for r in runs])) for k in ("net_excess_annual", "turnover")
            }
    res["random_baseline"] = rand
    print("random", rand, flush=True)

    grid: dict[str, Any] = {}
    for uni, frame in (("all", base), ("liquid100", top100)):
        for review in (5, 20):
            for buy, hold, n in itertools.product((0.05, 0.1, 0.2), (0.1, 0.3, 0.5), (10, 20, 40)):
                if hold < buy:
                    continue
                grid[f"{uni}_R{review}_buy{buy}_hold{hold}_n{n}"] = simulate_real(
                    frame,
                    paths,
                    buy=buy,
                    hold=hold,
                    n_names=n,
                    review=review,
                    cost=cost,
                    notional=1e9,
                    locks=True,
                )
        print("grid", uni, flush=True)
    res["grid_N1e9"] = grid
    res["horizons"] = list(HS)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
