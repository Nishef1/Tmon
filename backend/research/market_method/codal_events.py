"""What happened to a stock after each kind of Codal letter? (docs/reports/timing-and-codal-2026-11.md)

Every Codal letter of the 100-symbol liquid basket since 2017 is sorted into a kind by its title
(fixed regexes below, written from the list of the most common titles before any return was seen).
Entry: close of the first trading day AFTER the publish date (what a reader of the letter could do;
a letter published during the session is not traded the same day). Also the reaction before entry:
close of the publish day over the close of the day before.

Excess = the stock's return minus the mean of the basket over the same days, at 5, 20 and 60
trading days. A kind is "better" only if the 20-day excess beats the 1.75% round trip in both
halves (split at the median event date), "worse" if it is below minus the cost in both halves.
One event per symbol, kind and day. Entry days locked in a buy queue are dropped.
Second part: the plan's trend and dust picks with and without a known-that-day fundamental filter
(F score of fundamental_model: cheap P/E, profit growth, margin change, low debt; F >= 0.5), among
the names whose F is known that day (about 20 of the 100 a day, 2023-04 on; days with fewer than 10
are dropped).
Run from backend/ with the live env:  python research/market_method/codal_events.py
Output: results_codal_events.json
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import polars as pl

sys.argv = sys.argv[:1]
sys.path.insert(0, str(Path(__file__).parent))
from fundamentals_study import DB
from treasure_hunt import panel

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175

KINDS: list[tuple[str, str]] = [  # first match wins
    ("capital increase: board proposal", r"پیشنهاد هیئت مدیره .*افزایش سرمایه"),
    ("capital increase: auditor opinion", r"اظهارنظر حسابرس .*افزایش سرمایه"),
    ("capital increase: registered", r"آگهی ثبت افزایش سرمایه"),
    ("capital increase: rights/subscription", r"حق تقدم|پذیره نویسی"),
    ("capital increase: other", r"افزایش سرمایه"),
    ("clarification: price move", r"شفاف سازی در خصوص نوسان قیمت"),
    ("clarification: rumour or news", r"شفاف سازی در خصوص شایعه"),
    ("material: sales-price rise", r"نرخ فروش|افزایش نرخ"),
    ("material: major contract", r"انعقاد قرارداد"),
    ("material: auction held/won", r"نتایج برگزاری مزایده|برگزاری مزایده"),
    ("material: auction failed", r"عدم حصول نتیجه"),
    ("material: asset/stake sale", r"واگذاری"),
    ("material: stake purchase", r"تحصیل سهام"),
    ("material: discovery", r"کشف منابع"),
    ("material: pledge", r"توثیق|رهن|مسدود"),
    ("material: other", r"افشای اطلاعات بااهمیت"),
    ("EPS forecast", r"پیش بینی درآمد هر سهم"),
    ("monthly activity report", r"گزارش فعالیت ماهانه"),
    ("interim statements", r"میاندوره ای"),
    ("annual statements", r"صورت های مالی|صورتهای مالی"),
    ("AGM invitation", r"دعوت به مجمع عمومی عادی سالیانه"),
    ("AGM decisions", r"تصمیمات مجمع عمومی عادی سالیانه"),
    ("dividend schedule", r"زمانبندی پرداخت سود"),
    ("EGM decisions", r"تصمیمات مجمع عمومی فوق العاده"),
    ("board/CEO change", r"هیئت مدیره|مدیر عامل"),
    ("investor conference", r"کنفرانس اطلاع رسانی"),
    ("symbol halted/suspended", r"توقف نماد|تعلیق نماد"),
    ("listing warning", r"اعطای فرصت به ناشر|تمدید فرصت"),
    ("portfolio statement", r"صورت وضعیت پورتفوی"),
]
PATTERNS = [(k, re.compile(p)) for k, p in KINDS]


def kind_of(title: str) -> str | None:
    for k, p in PATTERNS:
        if p.search(title):
            return k
    return None


def letters(ids: dict[int, str]) -> pl.DataFrame:
    rows = (
        sqlite3.connect(DB, uri=True)
        .execute(
            "select instrument_id, symbol, title, published_at from codal_letters "
            "where published_at >= '2017-01-01'"
        )
        .fetchall()
    )
    by_sym = {v: k for k, v in ids.items()}
    out = []
    for iid, sym, title, pub in rows:
        iid = iid if iid in ids else by_sym.get(sym)
        k = kind_of(title or "")
        if iid is None or k is None:
            continue
        out.append({G: iid, "kind": k, "pub": pub[:10]})
    return (
        pl.DataFrame(out)
        .with_columns(C("pub").str.to_date())
        .unique([G, "kind", "pub"])
        .sort("pub")
    )


def main() -> None:
    a, ids = panel(drop_queue=False)
    c = C("adj_close")
    a = a.sort(G, "date").with_columns(
        **{f"f{h}": (c.shift(-h) / c - 1).over(G) for h in (5, 20, 60)},
        r0=(c / c.shift(1) - 1).over(G),
        locked=((C("high") == C("low")) & (C("close") > C("close").shift(1))).over(G),
    )
    a = a.with_columns(
        **{f"x{h}": C(f"f{h}") - C(f"f{h}").mean().over("date") for h in (5, 20, 60)},
        x0=C("r0") - C("r0").mean().over("date"),
    )
    ev = letters(ids)
    # entry day: first trading day strictly after the publish date
    days = a.select(G, "date").sort("date")
    ev = ev.with_columns(after=C("pub") + pl.duration(days=1)).sort("after")
    ev = ev.join_asof(
        days.rename({"date": "entry"}).sort("entry"),
        left_on="after",
        right_on="entry",
        by=G,
        strategy="forward",
        tolerance="10d",
    ).drop_nulls("entry")
    react = a.select(G, C("date").alias("pub"), "x0")
    e = (
        ev.join(
            a.select(G, C("date").alias("entry"), "x5", "x20", "x60", "locked"), on=[G, "entry"]
        )
        .join(react, on=[G, "pub"], how="left")
        .filter(~C("locked").fill_null(False))
    )
    mid = e["entry"].sort()[e.height // 2]
    res = []
    for (k,), g in e.group_by("kind"):
        h1, h2 = g.filter(C("entry") < mid), g.filter(C("entry") >= mid)
        row = {
            "kind": k,
            "n": g.height,
            "symbols": g[G].n_unique(),
            "react_day0": g["x0"].mean(),
            **{f"x{h}": g[f"x{h}"].mean() for h in (5, 20, 60)},
            "x20_median": g["x20"].median(),
            "x20_beat": (g["x20"] > 0).mean(),
            "x20_h1": h1["x20"].mean(),
            "x20_h2": h2["x20"].mean(),
            "n_h1": h1.height,
            "n_h2": h2.height,
        }
        both = [row["x20_h1"], row["x20_h2"]]
        ok = all(v is not None for v in both) and min(row["n_h1"], row["n_h2"]) >= 30
        row["label"] = (
            "better" if ok and min(both) > COST
            else "worse" if ok and max(both) < -COST
            else "unstable" if ok
            else "few"
        )  # fmt: skip
        res.append(row)
    res.sort(key=lambda r: -(r["x20"] or 0))
    for r in res:
        print(
            f"{r['kind']:40s} n {r['n']:5d} day0 {r['react_day0'] * 100:+5.1f}% "
            f"x5 {r['x5'] * 100:+5.1f} x20 {r['x20'] * 100:+5.1f} (med {r['x20_median'] * 100:+5.1f}, "
            f"h1 {(r['x20_h1'] or 0) * 100:+5.1f} h2 {(r['x20_h2'] or 0) * 100:+5.1f}) "
            f"x60 {(r['x60'] or 0) * 100:+5.1f}  {r['label']}"
        )
    print("split at", mid)
    fund = fundamentals_on_picks(a)
    (HERE / "results_codal_events.json").write_text(
        json.dumps({"split": str(mid), "kinds": res, "fundamental_filter": fund}, ensure_ascii=False,
                   indent=1, default=str),
        encoding="utf-8",
    )  # fmt: skip


def fundamentals_on_picks(a: pl.DataFrame) -> dict:
    """Trend and dust picks (10 a day) with and without F >= 0.5, 20-day excess, by half."""
    import fundamental_model as fm

    p, _ = fm.build()
    f = p.select("date", G, "F").with_columns(C("date").cast(pl.Date))
    d = a.join(f, on=["date", G], how="left").filter(
        ~C("locked").shift(-1).over(G).fill_null(False)
    )
    cover = d.group_by("date").agg(k=C("F").is_not_null().sum())
    good = cover.filter(C("k") >= 10)["date"]
    d = d.filter(C("date").is_in(good.implode()) & C("F").is_not_null())
    if d.height == 0:
        return {"days": 0}
    out: dict = {"days": d["date"].n_unique(), "from": str(d["date"].min())}
    mid = d["date"].unique().sort()
    mid = mid[len(mid) // 2]
    rules = {
        "trend": ((C("q_r120") == 4) & (C("q_pos60") >= 3), "r120", True),
        "dust": (C("q_dd") == 0, "dd", False),
    }
    for name, (filt, rank, desc) in rules.items():
        for tag, extra in (
            ("all", pl.lit(True)),
            ("F>=0.5", C("F") >= 0.5),
            ("F<0.5", C("F") < 0.5),
        ):
            x = (
                d.filter(filt & extra)
                .sort("date", rank, descending=[False, desc], nulls_last=True)
                .group_by("date", maintain_order=True)
                .head(10)
                .group_by("date")
                .agg(x=C("x20").mean())
            )
            out[f"{name} {tag}"] = {
                "h1": x.filter(C("date") < mid)["x"].mean(),
                "h2": x.filter(C("date") >= mid)["x"].mean(),
                "days": x.height,
            }
            print(name, tag, {k: v for k, v in out[f"{name} {tag}"].items()})
    return out


if __name__ == "__main__":
    main()
