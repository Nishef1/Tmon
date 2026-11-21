"""Exit rules measured from the holder's own buy (docs/reports/holder-exit-2026-11.md).

The owner buys at the close of day ``t``. Each rule then watches the daily closes up to ``t+H`` and
sells at the close of the first day it fires. If that day is locked at the lower limit (a sell
queue), the sale moves to the next unlocked day. "hold" sells at the close of ``t+H``. After a
sale the money sits in cash for the rest of the ``H`` days. Two cash cases are reported: cash at
zero, and cash earning the one-year bond yield of the buy day (``rf_1y_ytm``), which is about what
a fixed-income fund pays. The round-trip cost is charged once in every case.

Entries are every liquid symbol-day on or after ``SINCE``. A day locked at the upper limit is
skipped, because nobody can buy it. Prices are adjusted. The comparison is paired: for each entry,
the rule's return minus the return of holding. A t-statistic over the monthly means of that
difference is given for each half of the entry dates. A rule counts as better than holding only
when it is ahead in both halves with t >= 2. Rules and thresholds were fixed before the run.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest import trend_ride as tr

SINCE = dt.date(2023, 11, 1)  # the last three years (docs/reports/README.md)
HORIZONS = (20, 60)
STOPS = (5, 8, 10, 15, 20)  # percent below the buy price
TRAILS = (10, 15, 20)  # percent below the highest close since the buy
RULES: tuple[str, ...] = (
    "hold",
    *(f"stop{x}" for x in STOPS),
    *(f"trail{x}" for x in TRAILS),
    "ma20",
    "ma50",
    "time10",
)
RULE_FA = {
    "hold": "نگه داشتن تا آخر دوره",
    **{f"stop{x}": f"حد ضرر {x}٪ زیر قیمت خرید" for x in STOPS},
    **{f"trail{x}": f"حد ضرر شناور {x}٪ زیر بالاترین قیمت پس از خرید" for x in TRAILS},
    "ma20": "فروش با بسته شدن زیر میانگین ۲۰ روزه",
    "ma50": "فروش با بسته شدن زیر میانگین ۵۰ روزه",
    "time10": "فروش در روز دهم اگر زیر قیمت خرید باشد",
}
T_MIN = 2.0


def _exit(
    c: np.ndarray,
    down: np.ndarray,
    sma20: np.ndarray,
    sma50: np.ndarray,
    t: int,
    h: int,
    rule: str,
) -> tuple[float, int]:
    """(price return from the close of ``t`` to the sale, trading days held)."""
    e = c[t]
    peak = e
    for k in range(t + 1, t + h + 1):
        peak = max(peak, c[k])
        if rule.startswith("stop"):
            hit = c[k] <= e * (1 - int(rule[4:]) / 100)
        elif rule.startswith("trail"):
            hit = c[k] <= peak * (1 - int(rule[5:]) / 100)
        elif rule == "ma50":
            hit = bool(c[k] < sma50[k])
        elif rule == "ma20":
            hit = bool(c[k] < sma20[k])
        elif rule == "time10":
            hit = k == t + 10 and c[k] < e
        else:
            hit = False
        if hit:
            x = k
            while x < len(c) - 1 and down[x]:
                x += 1
            return float(c[x] / e - 1), x - t
    return float(c[t + h] / e - 1), h


def rows(panel: pl.DataFrame, rf: dict[dt.date, float], cost: float) -> pl.DataFrame:
    """One row per (entry, horizon, rule), with the net return for both cash cases."""
    keys = sorted(rf)

    def daily_rf(d: dt.date) -> float:
        i = bisect.bisect_right(keys, d) - 1
        return (1 + rf[keys[max(i, 0)]]) ** (1 / 240) - 1 if keys else 0.0

    out: list[tuple[Any, ...]] = []
    for (_iid,), g in panel.sort("instrument_id", "date").group_by(
        ["instrument_id"], maintain_order=True
    ):
        a = tr._symbol_arrays(g)
        c, up, down = a["close"], a["up"], a["down"]
        sma20 = g["sma20"].to_numpy().astype(float)
        sma50 = a["sma50"]
        d = g["date"].to_list()
        liq = g["liquid"].to_numpy()
        n = len(c)
        for t in range(n):
            if d[t] < SINCE or not liq[t] or up[t]:
                continue
            rfd = daily_rf(d[t])
            for h in HORIZONS:
                if t + h >= n:
                    continue
                for rule in RULES:
                    r, held = _exit(c, down, sma20, sma50, t, h, rule)
                    with_rf = (1 + r) * (1 + rfd) ** (h - held) - 1
                    out.append((d[t], h, rule, r - cost, with_rf - cost, held))
    df = pl.DataFrame(
        out, schema=["date", "h", "rule", "net0", "net", "held"], orient="row"
    ).with_row_index("i")
    base = df.filter(pl.col("rule") == "hold").select(
        (pl.col("i") // len(RULES)).alias("grp"), hold0="net0", hold="net"
    )
    df = df.with_columns(grp=pl.col("i") // len(RULES)).join(base, on="grp")
    dates = df["date"].unique().sort()
    mid = dates[len(dates) // 2]
    return df.with_columns(
        half=pl.when(pl.col("date") < mid).then(pl.lit("A")).otherwise(pl.lit("B")),
        month=pl.col("date").dt.strftime("%Y-%m"),
        diff=pl.col("net") - pl.col("hold"),
        diff0=pl.col("net0") - pl.col("hold0"),
    ).drop("i", "grp")


@dataclass(frozen=True)
class Cell:
    n: int
    months: int
    mean: float
    p05: float
    fired: float
    diff: float
    diff_t: float | None


def _t(sub: pl.DataFrame, col: str) -> float | None:
    m = sub.group_by("month").agg(pl.col(col).mean())[col].to_numpy()
    if len(m) < 3 or m.std(ddof=1) == 0:
        return None
    return float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m))))


def summary(df: pl.DataFrame, cash: str = "net") -> dict[tuple[int, str, str], Cell]:
    diff = "diff" if cash == "net" else "diff0"
    out: dict[tuple[int, str, str], Cell] = {}
    for (h, rule, half), sub in df.group_by(["h", "rule", "half"]):
        out[(int(h), str(rule), str(half))] = Cell(
            n=sub.height,
            months=sub["month"].n_unique(),
            mean=float(sub[cash].mean()),  # type: ignore[arg-type]
            p05=float(sub[cash].quantile(0.05)),  # type: ignore[arg-type]
            fired=float((sub["held"] < h).mean()),
            diff=float(sub[diff].mean()),  # type: ignore[arg-type]
            diff_t=None if rule == "hold" else _t(sub, diff),
        )
    return out


def passes(s: dict[tuple[int, str, str], Cell], h: int, rule: str) -> bool:
    halves = [s[(h, rule, x)] for x in ("A", "B")]
    return all(c.diff > 0 and (c.diff_t or 0) >= T_MIN for c in halves)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}٪"


def markdown(df: pl.DataFrame) -> str:
    a = df.filter(pl.col("half") == "A")["date"].to_list()
    b = df.filter(pl.col("half") == "B")["date"].to_list()
    lines = [
        f"نیمهٔ اول: {min(a)} تا {max(a)}؛ نیمهٔ دوم: {min(b)} تا {max(b)}.",
        "",
    ]
    for cash, title in (("net", "نقد با سود اوراق یک‌ساله"), ("net0", "نقد بدون سود")):
        s = summary(df, cash)
        lines += [f"### {title}", ""]
        for h in HORIZONS:
            lines += [
                f"**{h} روز معاملاتی**",
                "",
                "| قاعده | میانگین (نیمهٔ ۱ / ۲) | بدترین ۵ از ۱۰۰ (۱ / ۲) | فعال شد (۱ / ۲) "
                "| فرق با نگه داشتن، واحد درصد (۱ / ۲) | t (۱ / ۲) | بهتر از نگه داشتن؟ |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for rule in RULES:
                ca, cb = s[(h, rule, "A")], s[(h, rule, "B")]
                t = "—" if rule == "hold" else f"{ca.diff_t or 0:+.2f} / {cb.diff_t or 0:+.2f}"
                ok = "—" if rule == "hold" else ("بله" if passes(s, h, rule) else "نه")
                lines.append(
                    f"| {RULE_FA[rule]} | {_pct(ca.mean)} / {_pct(cb.mean)} "
                    f"| {_pct(ca.p05)} / {_pct(cb.p05)} "
                    f"| {ca.fired * 100:.0f} / {cb.fired * 100:.0f} از ۱۰۰ "
                    f"| {ca.diff * 100:+.1f} / {cb.diff * 100:+.1f} | {t} | {ok} |"
                )
            ca = s[(h, "hold", "A")]
            lines += ["", f"ورودها: {ca.n} در نیمهٔ اول، {s[(h, 'hold', 'B')].n} در نیمهٔ دوم.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from sqlalchemy import select

    from tmon.backtest import turning as tp
    from tmon.core.db import session_scope
    from tmon.core.engine_config import get_engine_config
    from tmon.domain.rules import CostModel, RuleBook
    from tmon.features.store import load_inputs
    from tmon.storage.models import MacroSeries

    ap = argparse.ArgumentParser(prog="tmon-holder-exit")
    ap.add_argument("--md", type=Path, help="write the tables as Markdown")
    args = ap.parse_args(argv)
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
        rules = RuleBook.from_session(s)
        rf = {
            m.ref_period: m.value
            for m in s.scalars(select(MacroSeries).where(MacroSeries.series == "rf_1y_ytm"))
        }
    panel = tp.build_panel(prices, clients)
    as_of: dt.date = panel["date"].max()  # type: ignore[assignment]
    cost = CostModel.from_rules(
        rules, as_of, get_engine_config().costs.slippage_fraction
    ).round_trip
    text = f"هزینهٔ رفت‌وبرگشت: {cost * 100:.2f}٪.\n" + markdown(rows(panel, rf, cost))
    if args.md:
        args.md.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
