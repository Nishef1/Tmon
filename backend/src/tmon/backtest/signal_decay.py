"""R1 (ADR 0003): how fast does the information in each baseline signal decay with the horizon?

For each of the four signals of the v2 baseline score (``ind_buy_power``, ``-rv_20``,
``dist_high_52w``, 12-1 month momentum) and each horizon h in (5, 20, 40, 60) trading days:

* the daily cross-sectional rank correlation (Spearman IC) between the signal at ``t`` and the
  adjusted return from the close of ``t+1`` to the close of ``t+1+h`` (the ADR 0003 label, so the
  entry is the next day, never ``t``);
* its mean, standard deviation, share of positive days and a t-statistic. Daily ICs of overlapping
  horizons are autocorrelated, so the t-statistic is divided by ``sqrt(h)``-effective sample size
  (``n_days / h`` independent observations), a conservative rule that is stated in the report;
* the IC by calendar year at h = 20, to show instability;
* the mean pairwise cross-sectional rank correlation between the signals;
* the equal-weight composite of the four percentile ranks: its IC and the gross mean return of its
  top decile minus the universe median, per horizon (the assumption behind the "40% turnover"
  column of docs/reports/research-engine-v2.md).

Everything is vectorised with Polars; there is no loop over rows of market data. The universe of a
day is the engine's: eligible and not in an excluded queue state.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.features.builder import KEYS

HORIZONS: tuple[int, ...] = (5, 20, 40, 60)
MIN_CROSS_SECTION = 30  # a day with fewer ranked symbols gives no IC
MOM_SKIP, MOM_LOOKBACK = 21, 252  # 12-1 month momentum in trading days

# signal column -> sign (+1: higher is better)
SIGNALS: dict[str, int] = {
    "ind_buy_power": 1,
    "rv_20": -1,
    "dist_high_52w": 1,
    "mom_12_1": 1,
}


def forward_returns(adj: pl.DataFrame, horizons: Sequence[int]) -> pl.DataFrame:
    """``fwd_{h}`` = adj close ``t+1+h`` over adj close ``t+1`` minus one, per instrument, and the
    12-1 month momentum. ``adj`` needs ``instrument_id, date, adj_close`` (halt days removed)."""
    g = "instrument_id"
    c = pl.col("adj_close")
    return adj.sort(KEYS).with_columns(
        *[(c.shift(-(1 + h)) / c.shift(-1) - 1.0).over(g).alias(f"fwd_{h}") for h in horizons],
        (c.shift(MOM_SKIP) / c.shift(MOM_LOOKBACK) - 1.0).over(g).alias("mom_12_1"),
    )


def _pct_rank(col: str) -> pl.Expr:
    """Percentile rank (0..1) inside the date's cross-section, nulls stay null."""
    r = pl.col(col).rank("average").over("date")
    n = pl.col(col).count().over("date")
    return (r - 0.5) / n


def build_panel(
    features: pl.DataFrame,
    adj: pl.DataFrame,
    cfg: EngineConfig | None = None,
    horizons: Sequence[int] = HORIZONS,
) -> pl.DataFrame:
    """Universe rows with signals (sign-adjusted percentile ranks ``r_*``), the composite score
    and the forward returns."""
    c = cfg or get_engine_config()
    fwd = forward_returns(adj, horizons).select(*KEYS, "mom_12_1", *[f"fwd_{h}" for h in horizons])
    d = features.filter(~pl.col("market_halt")).select(
        *KEYS, "eligible", "queue_state", "ind_buy_power", "rv_20", "dist_high_52w"
    )
    d = d.join(fwd, on=list(KEYS), how="left").filter(
        pl.col("eligible") & ~pl.col("queue_state").is_in(c.universe.exclude_queue_states)
    )
    # only symbols with every signal present enter the cross-section, so ranks are comparable
    d = d.filter(
        pl.all_horizontal([pl.col(s).is_not_null() & pl.col(s).is_finite() for s in SIGNALS])
    )
    d = d.with_columns(
        *[
            (_pct_rank(s) if sign > 0 else 1.0 - _pct_rank(s)).alias(f"r_{s}")
            for s, sign in SIGNALS.items()
        ]
    )
    return d.with_columns(
        pl.mean_horizontal([f"r_{s}" for s in SIGNALS]).alias("composite")
    ).with_columns(_pct_rank("composite").alias("r_composite"))


def daily_ic(panel: pl.DataFrame, signal: str, horizon: int) -> pl.DataFrame:
    """Spearman IC per date: Pearson correlation of the date's ranks."""
    fwd = f"fwd_{horizon}"
    d = panel.filter(pl.col(fwd).is_not_null() & pl.col(fwd).is_finite()).with_columns(
        pl.col(signal).rank("average").over("date").alias("_a"),
        pl.col(fwd).rank("average").over("date").alias("_b"),
    )
    return (
        d.group_by("date")
        .agg(pl.len().alias("n"), pl.corr("_a", "_b").alias("ic"))
        .filter((pl.col("n") >= MIN_CROSS_SECTION) & pl.col("ic").is_not_null())
        .sort("date")
    )


def summarize_ic(ic: pl.DataFrame, horizon: int) -> dict[str, Any]:
    n = ic.height
    if n < 2:
        return {"n_days": n, "mean": None, "std": None, "t": None, "positive_share": None}
    mean = float(ic["ic"].mean())  # type: ignore[arg-type]
    std = float(ic["ic"].std())  # type: ignore[arg-type]
    eff = max(n / horizon, 1.0)  # overlapping windows: about n/h independent observations
    t = mean / (std / math.sqrt(eff)) if std > 0 else None
    return {
        "n_days": n,
        "mean": mean,
        "std": std,
        "t": t,
        "positive_share": float((ic["ic"] > 0).mean()),  # type: ignore[arg-type]
        "avg_cross_section": float(ic["n"].mean()),  # type: ignore[arg-type]
    }


def ic_by_year(ic: pl.DataFrame) -> dict[int, dict[str, float]]:
    out = (
        ic.with_columns(pl.col("date").dt.year().alias("year"))
        .group_by("year")
        .agg(pl.col("ic").mean().alias("mean"), pl.len().alias("n"))
        .sort("year")
    )
    return {int(r["year"]): {"mean": float(r["mean"]), "n": int(r["n"])} for r in out.to_dicts()}


def signal_correlations(panel: pl.DataFrame) -> dict[str, dict[str, float | None]]:
    """Mean over dates of the pairwise rank correlation of the sign-adjusted signals."""
    names = list(SIGNALS)
    exprs = [
        pl.corr(f"r_{a}", f"r_{b}").alias(f"{a}|{b}")
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    ]
    per_day = panel.group_by("date").agg(*exprs, pl.len().alias("n"))
    per_day = per_day.filter(pl.col("n") >= MIN_CROSS_SECTION)
    out: dict[str, dict[str, float | None]] = {a: {} for a in names}
    for i, a in enumerate(names):
        out[a][a] = 1.0
        for b in names[i + 1 :]:
            m = per_day[f"{a}|{b}"].drop_nulls().mean()
            v = None if m is None else float(m)  # type: ignore[arg-type]
            out[a][b] = v
            out[b][a] = v
    return out


def top_decile_spread(panel: pl.DataFrame, horizon: int) -> dict[str, Any]:
    """Gross mean return of the composite's top decile minus the universe median, per date,
    averaged over dates; also the same for the bottom decile (symmetry check)."""
    fwd = f"fwd_{horizon}"
    d = panel.filter(pl.col(fwd).is_not_null() & pl.col(fwd).is_finite())
    per = (
        d.group_by("date")
        .agg(
            pl.len().alias("n"),
            pl.col(fwd).median().alias("med"),
            pl.col(fwd).filter(pl.col("r_composite") > 0.9).mean().alias("top"),
            pl.col(fwd).filter(pl.col("r_composite") <= 0.1).mean().alias("bottom"),
        )
        .filter(pl.col("n") >= MIN_CROSS_SECTION)
        .with_columns(
            (pl.col("top") - pl.col("med")).alias("top_excess"),
            (pl.col("bottom") - pl.col("med")).alias("bottom_excess"),
        )
    )
    n = per.height
    if not n:
        return {"n_days": 0, "top_excess": None, "bottom_excess": None}
    top = per["top_excess"].drop_nulls()
    eff = max(n / horizon, 1.0)
    sd = top.std()
    t = None if not sd else float(top.mean()) / (float(sd) / math.sqrt(eff))  # type: ignore[arg-type]
    return {
        "n_days": n,
        "top_excess": float(top.mean()),  # type: ignore[arg-type]
        "bottom_excess": float(per["bottom_excess"].drop_nulls().mean()),  # type: ignore[arg-type]
        "t": t,
    }


@dataclass(frozen=True)
class DecayResult:
    horizons: tuple[int, ...]
    n_rows: int
    n_days: int
    first_date: str
    last_date: str
    ic: dict[str, dict[int, dict[str, Any]]]  # signal (+ composite) -> horizon -> summary
    by_year_h20: dict[str, dict[int, dict[str, float]]]
    correlations: dict[str, dict[str, float | None]]
    spread: dict[int, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizons": list(self.horizons),
            "n_rows": self.n_rows,
            "n_days": self.n_days,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "ic": {s: {str(h): v for h, v in hs.items()} for s, hs in self.ic.items()},
            "by_year_h20": {
                s: {str(y): v for y, v in ys.items()} for s, ys in self.by_year_h20.items()
            },
            "correlations": self.correlations,
            "spread": {str(h): v for h, v in self.spread.items()},
        }


def analyse(panel: pl.DataFrame, horizons: Sequence[int] = HORIZONS) -> DecayResult:
    names = [f"r_{s}" for s in SIGNALS] + ["r_composite"]
    ic: dict[str, dict[int, dict[str, Any]]] = {}
    by_year: dict[str, dict[int, dict[str, float]]] = {}
    for col in names:
        key = col[2:]
        ic[key] = {}
        for h in horizons:
            series = daily_ic(panel, col, h)
            ic[key][h] = summarize_ic(series, h)
            if h == 20:
                by_year[key] = ic_by_year(series)
    dates = panel["date"]
    return DecayResult(
        horizons=tuple(horizons),
        n_rows=panel.height,
        n_days=int(dates.n_unique()),
        first_date=str(dates.min()),
        last_date=str(dates.max()),
        ic=ic,
        by_year_h20=by_year,
        correlations=signal_correlations(panel),
        spread={h: top_decile_spread(panel, h) for h in horizons},
    )


def adjusted_close(prices: pl.DataFrame) -> pl.DataFrame:
    """``instrument_id, date, adj_close`` with the same corporate-action adjustment the features
    use (``tmon.features.adjustment``)."""
    from tmon.features.adjustment import apply_adjustments

    d = prices.sort(KEYS)
    for optional, dtype in (("base_volume", pl.Float64), ("market_halt", pl.Boolean)):
        if optional not in d.columns:
            d = d.with_columns(pl.lit(None, dtype=dtype).alias(optional))
    d = d.with_columns(pl.col("market_halt").fill_null(False))
    return apply_adjustments(d).select(*KEYS, "adj_close")


def _f(x: float | None, digits: int = 3, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f}٪" if pct else f"{x:+.{digits}f}"


def render_markdown(r: DecayResult) -> str:
    out: list[str] = []
    out.append("# R1 — افت سیگنال با افق: چهار سیگنال مبنای v2 (دادهٔ واقعی)")
    out.append("")
    out.append(
        f"- بازه: {r.first_date} تا {r.last_date}؛ {r.n_days} روز معاملاتی، "
        f"{r.n_rows} ردیف نماد-روز در جهان موتور (واجد شرایط، بدون صف فروش، هر چهار سیگنال موجود)."
    )
    out.append(
        "- IC = همبستگی رتبه‌ای اسپیرمن مقطعی روزانهٔ سیگنال در `t` با بازده تعدیل‌شده از پایانی "
        "`t+1` تا `t+1+h` (بدون هزینه). آمارهٔ t با `n_days / h` مشاهدهٔ مستقل محاسبه شده، چون "
        "ICهای روزانهٔ افق‌های هم‌پوشان خودهمبسته‌اند."
    )
    out.append(
        "- سیگنال‌ها هم‌جهت‌شده‌اند (`rv_20` با علامت منفی). ترکیبی = میانگین هم‌وزن چهار رتبهٔ صدکی."
    )
    out.append("- هیچ پارامتری روی این داده تنظیم نشده؛ تعداد آزمون‌ها: ۵ سیگنال × ۴ افق = ۲۰.")
    out.append("")
    out.append("## IC میانگین به تفکیک افق (t داخل پرانتز)")
    out.append("")
    out.append("| سیگنال | " + " | ".join(f"h={h}" for h in r.horizons) + " | نسبت IC(40)/IC(20) |")
    out.append("|---|" + "---|" * (len(r.horizons) + 1))
    for s, hs in r.ic.items():
        cells = []
        for h in r.horizons:
            m, t = hs[h].get("mean"), hs[h].get("t")
            cells.append(f"{_f(m, 4)} ({_f(t, 2)})")
        a, b = hs.get(20, {}).get("mean"), hs.get(40, {}).get("mean")
        ratio = _f(b / a, 2) if a and b is not None else "—"
        out.append(f"| {s} | " + " | ".join(cells) + f" | {ratio} |")
    out.append("")
    out.append("## سهم روزهای با IC مثبت (h=20) و میانگین اندازهٔ مقطع")
    out.append("")
    out.append("| سیگنال | روزهای IC مثبت | انحراف معیار IC | متوسط تعداد نماد در روز |")
    out.append("|---|---|---|---|")
    for s, hs in r.ic.items():
        x = hs.get(20, {})
        pos = x.get("positive_share")
        out.append(
            f"| {s} | {_f(pos, 1, pct=True) if pos is not None else '—'} | {_f(x.get('std'), 4)} "
            f"| {x.get('avg_cross_section', 0):.0f} |"
        )
    out.append("")
    out.append("## IC به تفکیک سال تقویمی (h=20، میلادی)")
    out.append("")
    years = sorted({y for ys in r.by_year_h20.values() for y in ys})
    out.append("| سیگنال | " + " | ".join(str(y) for y in years) + " |")
    out.append("|---|" + "---|" * len(years))
    for s, ys in r.by_year_h20.items():
        out.append(
            f"| {s} | " + " | ".join(_f(ys[y]["mean"], 3) if y in ys else "—" for y in years) + " |"
        )
    out.append("")
    out.append("## همبستگی رتبه‌ای میانگین بین سیگنال‌ها")
    out.append("")
    names = list(SIGNALS)
    out.append("| | " + " | ".join(names) + " |")
    out.append("|---|" + "---|" * len(names))
    for a in names:
        out.append(f"| {a} | " + " | ".join(_f(r.correlations[a].get(b), 2) for b in names) + " |")
    out.append("")
    out.append("## دهک بالای امتیاز ترکیبی: بازده ناخالص مازاد بر میانهٔ جهان")
    out.append("")
    out.append("| افق | مازاد دهک بالا | مازاد دهک پایین | t | روزها |")
    out.append("|---|---|---|---|---|")
    for h in r.horizons:
        sp = r.spread[h]
        top = _f(sp.get("top_excess"), 2, pct=True)
        bottom = _f(sp.get("bottom_excess"), 2, pct=True)
        out.append(f"| {h} | {top} | {bottom} | {_f(sp.get('t'), 2)} | {sp.get('n_days', 0)} |")
    out.append("")
    out.append(
        "مازاد ناخالص است؛ رفت‌وبرگشت ≈ ۱٫۷۵٪ باید از آن کم شود. این گزارش فقط می‌گوید اطلاعات "
        "سیگنال‌ها با افق چگونه می‌ماند یا می‌میرد، نه اینکه سبد سودده است (گام R3)."
    )
    out.append("")
    out.append("## محدودیت‌های این اندازه‌گیری (مستقل از عددها)")
    out.append("")
    out.append(
        "- **سوگیری بقا (OQ 65):** نمادهای حذف‌شده از بورس در پایگاه داده نیستند؛ مازاد دهک بالا "
        "احتمالاً خوش‌بینانه است و کران آن اندازه‌گیری نشده است."
    )
    out.append(
        "- **قابل‌اجرا بودن:** نمادهای در صف خرید یا با حجم ناچیز در این گزارش حذف نشده‌اند مگر "
        "با قید جهان موتور؛ اجرای واقعی با صف و سقف نقدشوندگی در R3 سنجیده می‌شود."
    )
    out.append(
        "- **چندآزمونی:** ۲۰ ترکیب سیگنال-افق آزموده شد؛ آستانهٔ t دوطرفهٔ بونفرونی ≈ ۳٫۰۲. "
        "ترکیبی پنج سیگنال در همین برآورد است و جدا از آن‌ها ۲۰ حساب نشده است."
    )
    out.append("- آمارهٔ t با `n_days / h` مشاهدهٔ مستقل، تقریب است، نه Newey–West.")
    out.append("")
    out.append("> ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="tmon-signal-decay")
    ap.add_argument("--md", type=Path, help="Markdown report (docs/reports)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    from tmon.core.db import session_scope
    from tmon.domain.rules import RuleBook
    from tmon.features.builder import build_features
    from tmon.features.store import load_inputs

    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        rules = RuleBook.from_session(session)
    feats = build_features(prices, clients, rules, sectors=sectors)
    panel = build_panel(feats, adjusted_close(prices))
    res = analyse(panel)
    md = render_markdown(res)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(
            json.dumps(res.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
