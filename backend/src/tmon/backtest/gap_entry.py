"""Buying at the open after a gap, or waiting (docs/reports/gap-entry-2026-11.md).

Buying at 09:00 and buying near 12:30 the same day lead to the same exit, so the only difference
between them is the price paid. This module measures that difference: how much more the opening
price cost than the price near the end of the session, by the size of the opening gap (the open
against yesterday's reference close).

The end-of-session price is the day's last trade (``last``), because the official close is an
average over the day and nobody can trade at it. When the symbol ends the day locked at the upper
limit, nobody can buy at the end either, so waiting then means buying at the next day's open. A
limit order at yesterday's close is the third way: it fills when the day's low reaches it, and an
unfilled order buys at the end of the session like waiting does.

Rows are stock symbol-days on or after ``SINCE`` among the ``TOP`` symbols by the mean traded value
of the previous ``LIQ_DAYS`` days. Days locked at one price all day are dropped, because nobody
could choose a price. Days where the next day's reference price is not today's last or close (a
capital change) are dropped, so the next open is comparable. For each gap band and way of buying
the saving against buying at the open is averaged by month; a way counts as better only when it is
ahead in both halves of the dates with t >= 2. Bands and ways were fixed before the run.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import polars as pl

SINCE = dt.date(2023, 11, 1)  # the last three years (docs/reports/README.md)
TOP = 100
LIQ_DAYS = 60
GAP_EDGES = (-1.0, -0.01, 0.005, 0.015, 0.025, 1.0)  # the bands of tmon.portfolio.entry
GAP_FA = (
    "بازگشایی بیش از ۱٪ پایین‌تر",
    "نزدیک قیمت دیروز",
    "۰.۵ تا ۱.۵٪ بالاتر",
    "۱.۵ تا ۲.۵٪ بالاتر",
    "بیش از ۲.۵٪ بالاتر",
)
WAYS = ("wait", "limit", "high")
WAY_FA = {
    "wait": "صبر تا آخر جلسه (آخرین معامله؛ اگر صف خرید شد، بازگشایی فردا)",
    "limit": "سفارش محدود به قیمت پایانی دیروز؛ اگر پر نشد، آخر جلسه",
    "high": "خرید در بالاترین قیمت روز (بدترین حالت خرید در بازگشایی)",
}
T_MIN = 2.0


def _band(gap: pl.Expr) -> pl.Expr:
    """The :data:`GAP_FA` label of each gap; a band holds (lower edge, upper edge]."""
    out = pl.lit(GAP_FA[-1])
    for edge, label in reversed(list(zip(GAP_EDGES[1:-1], GAP_FA[:-1], strict=True))):
        out = pl.when(gap <= edge).then(pl.lit(label)).otherwise(out)
    return out


def frame(prices: pl.DataFrame) -> pl.DataFrame:
    """One row per liquid symbol-day with the gap and the price each way of buying pays.

    ``prices`` needs instrument_id, date, open, high, low, last, close, prev_close, value and
    limit_up, unadjusted, as stored."""
    c = pl.col
    g = "instrument_id"
    p = (
        prices.sort(g, "date")
        .with_columns(
            liq=c("value").rolling_mean(LIQ_DAYS, min_samples=LIQ_DAYS // 2).shift(1).over(g),
            nxt_open=c("open").shift(-1).over(g),
            nxt_ref=c("prev_close").shift(-1).over(g),
        )
        .filter(
            (c("date") >= SINCE)
            & (c("open") > 0)
            & (c("low") > 0)
            & (c("last") > 0)
            & (c("prev_close") > 0)
            & (c("high") > c("low"))
            & c("liq").is_not_null()
        )
        .with_columns(rank=c("liq").rank("ordinal", descending=True).over("date"))
        .filter(c("rank") <= TOP)
    )
    locked_end = c("limit_up").is_not_null() & (c("last") >= c("limit_up") * 0.999)
    same_ref = ((c("nxt_ref") - c("last")).abs() < 1.0) | ((c("nxt_ref") - c("close")).abs() < 1.0)
    wait = pl.when(locked_end).then(c("nxt_open")).otherwise(c("last"))
    p = p.with_columns(gap=c("open") / c("prev_close") - 1, locked_end=locked_end, wait=wait)
    p = p.filter(c("wait").is_not_null() & (c("wait") > 0) & (~c("locked_end") | same_ref))
    filled = c("low") <= c("prev_close")
    p = p.with_columns(
        filled=filled,
        limit=pl.when(filled).then(pl.min_horizontal("open", "prev_close")).otherwise(c("wait")),
        band=_band(c("gap")),
    )
    # saving of each way against buying at the open, as a share of the open price paid
    dates = p["date"].unique().sort()
    mid = dates[len(dates) // 2]
    return p.with_columns(
        s_wait=c("open") / c("wait") - 1,
        s_limit=c("open") / c("limit") - 1,
        s_high=c("open") / c("high") - 1,
        half=pl.when(c("date") < mid).then(pl.lit("A")).otherwise(pl.lit("B")),
        month=c("date").dt.strftime("%Y-%m"),
    ).select(
        "instrument_id",
        "date",
        "band",
        "gap",
        "half",
        "month",
        "filled",
        "locked_end",
        "s_wait",
        "s_limit",
        "s_high",
    )


@dataclass(frozen=True)
class Cell:
    n: int
    mean: float
    t: float | None
    ahead: float  # share of days the way paid less than the open


def _t(sub: pl.DataFrame, col: str) -> float | None:
    m = sub.group_by("month").agg(pl.col(col).mean())[col].to_numpy()
    if len(m) < 3 or m.std(ddof=1) == 0:
        return None
    return float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m))))


def summary(df: pl.DataFrame) -> dict[tuple[str, str, str], Cell]:
    out: dict[tuple[str, str, str], Cell] = {}
    for (band, half), sub in df.group_by(["band", "half"]):
        for w in WAYS:
            col = sub[f"s_{w}"]
            out[(str(band), w, str(half))] = Cell(
                n=sub.height,
                mean=float(col.mean()),  # type: ignore[arg-type]
                t=_t(sub, f"s_{w}"),
                ahead=float((col > 0).mean()),  # type: ignore[arg-type]
            )
    return out


def passes(s: dict[tuple[str, str, str], Cell], band: str, way: str) -> bool:
    return all(
        (c := s.get((band, way, h))) is not None and c.mean > 0 and (c.t or 0) >= T_MIN
        for h in ("A", "B")
    )


def _pp(x: float) -> str:
    return f"{x * 100:+.2f}"


def markdown(df: pl.DataFrame) -> str:
    s = summary(df)
    a = df.filter(pl.col("half") == "A")["date"].to_list()
    b = df.filter(pl.col("half") == "B")["date"].to_list()
    lines = [
        f"نیمهٔ اول: {min(a)} تا {max(a)}؛ نیمهٔ دوم: {min(b)} تا {max(b)}.",
        "",
        "عددها صرفه نسبت به خرید در قیمت بازگشایی است، به واحد درصد از قیمت پرداختی. مثبت یعنی "
        "آن راه ارزان‌تر از بازگشایی خرید کرده است.",
        "",
    ]
    for band in GAP_FA:
        sub = df.filter(pl.col("band") == band)
        if sub.is_empty():
            continue
        fill = float(sub["filled"].mean())  # type: ignore[arg-type]
        locked = float(sub["locked_end"].mean())  # type: ignore[arg-type]
        lines += [
            f"**{band}** ({sub.height:,} روز-نماد؛ سفارش محدود {fill * 100:.0f} بار از ۱۰۰ پر شد؛ "
            f"{locked * 100:.0f} بار از ۱۰۰ آخر روز صف خرید بود)",
            "",
            "| راه خرید | صرفه (نیمهٔ ۱ / ۲) | t (۱ / ۲) | ارزان‌تر از بازگشایی، از ۱۰۰ روز (۱ / ۲) "
            "| در هر دو نیمه بهتر؟ |",
            "| --- | --- | --- | --- | --- |",
        ]
        for w in WAYS:
            ca, cb = s.get((band, w, "A")), s.get((band, w, "B"))
            if ca is None or cb is None:
                continue
            ok = "—" if w == "high" else ("بله" if passes(s, band, w) else "نه")
            lines.append(
                f"| {WAY_FA[w]} | {_pp(ca.mean)} / {_pp(cb.mean)} "
                f"| {ca.t or 0:+.2f} / {cb.t or 0:+.2f} "
                f"| {ca.ahead * 100:.0f} / {cb.ahead * 100:.0f} | {ok} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from sqlalchemy import select

    from tmon.core.db import session_scope
    from tmon.storage.models import Instrument, PriceDaily

    ap = argparse.ArgumentParser(prog="tmon-gap-entry")
    ap.add_argument("--md", type=Path, help="write the tables as Markdown")
    args = ap.parse_args(argv)
    cols = (
        PriceDaily.instrument_id,
        PriceDaily.date,
        PriceDaily.open,
        PriceDaily.high,
        PriceDaily.low,
        PriceDaily.last,
        PriceDaily.close,
        PriceDaily.prev_close,
        PriceDaily.value,
        PriceDaily.limit_up,
    )
    start = SINCE - dt.timedelta(days=LIQ_DAYS * 2)
    with session_scope() as s:
        rows = s.execute(
            select(*cols)
            .join(Instrument, Instrument.id == PriceDaily.instrument_id)
            .where(Instrument.instrument_type == "stock", PriceDaily.date >= start)
        ).all()
    names = [c.key for c in cols]
    prices = pl.DataFrame(
        [(r[0], r[1], *(None if x is None else float(x) for x in r[2:])) for r in rows],
        schema=names,
        orient="row",
        infer_schema_length=None,
    )
    text = markdown(frame(prices))
    if args.md:
        args.md.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
