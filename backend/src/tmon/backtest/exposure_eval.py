"""R2 (ADR 0003): does the exposure layer beat holding the equal-weight index through a drawdown,
and does it still earn more than the treasury bill?

The equity sleeve is the *official equal-weight index* and the rest sits in the treasury bill (the
fixed-income fund stand-in, OPEN_QUESTIONS 63/83). The exposure decided at the close of ``t`` is
applied to the return of ``t+1``. The only cost modelled is the configured slippage on the part of
the book that changes (``slippage_fraction / 2`` per side); commissions, tax and the fund's own fee
are not, and the report says so.

No parameter is fitted here: windows come from the literature (``v2.exposure`` in engine.yaml), so
the whole span is out of sample for them. The one number that is a free choice, the target
volatility, is shown as a sensitivity table, never selected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.metrics import portfolio_metrics
from tmon.core.engine_config import EngineConfig, ExposureCfg, get_engine_config
from tmon.engine.exposure import compute_exposure, trading_days_per_year


def sell_queue_share(features: pl.DataFrame) -> pl.DataFrame:
    """Share of the day's eligible, trading symbols that closed in a sell queue (``date, share``).
    Measured before the universe filter, which already drops those symbols."""
    return (
        features.filter(~pl.col("market_halt") & pl.col("eligible"))
        .group_by("date")
        .agg((pl.col("queue_state") == "sell_queue").mean().alias("share"))
        .sort("date")
    )


def simulate(
    exposure: pl.DataFrame,
    index_ret: pl.DataFrame,
    rf_daily: pl.DataFrame,
    *,
    cost_per_side: float,
    column: str = "exposure",
) -> pl.DataFrame:
    """Daily return of the exposure-managed book: ``date, ret, ew_ret, rf_ret, e`` where ``e`` is
    the exposure held *during* the day (decided at the previous close)."""
    d = (
        exposure.select("date", pl.col(column).alias("e_dec"))
        .join(index_ret.rename({"ret": "ew_ret"}), on="date", how="inner")
        .join(rf_daily.rename({"ret": "rf_ret"}), on="date", how="inner")
        .sort("date")
        .with_columns(pl.col("e_dec").shift(1).alias("e"))
        .with_columns(pl.col("e").shift(1).alias("e_prev"))
    )
    d = d.filter(pl.col("e").is_not_null() & pl.col("e_prev").is_not_null())
    return d.select(
        "date",
        (
            pl.col("e") * pl.col("ew_ret")
            + (1 - pl.col("e")) * pl.col("rf_ret")
            - (pl.col("e") - pl.col("e_prev")).abs() * cost_per_side
        ).alias("ret"),
        "ew_ret",
        "rf_ret",
        "e",
    )


def _stats(daily: pl.DataFrame, rf_annual: float | None) -> dict[str, Any]:
    m = portfolio_metrics(daily.select("date", "ret"), risk_free_annual=rf_annual)
    e = daily["e"].to_numpy() if "e" in daily.columns else None
    if e is not None:
        m["avg_exposure"] = float(np.mean(e))
        m["share_days_zero"] = float(np.mean(e == 0.0))
        years = m.get("years") or 0.0
        m["exposure_turnover_per_year"] = (
            float(np.abs(np.diff(e)).sum() / years) if years > 0 else None
        )
    return m


def _fixed(daily: pl.DataFrame, level: float | None, col: str) -> pl.DataFrame:
    """A benchmark on the same dates: the index (``level`` None, ``col='ew_ret'``), the bill or a
    constant mix."""
    if level is None:
        return daily.select("date", pl.col(col).alias("ret"))
    return daily.select(
        "date", (level * pl.col("ew_ret") + (1 - level) * pl.col("rf_ret")).alias("ret")
    )


def yearly_returns(daily: pl.DataFrame) -> dict[int, float]:
    out: dict[int, float] = {}
    for (y,), g in daily.with_columns(pl.col("date").dt.year().alias("y")).group_by("y"):
        out[int(y)] = float(np.prod(1.0 + g["ret"].to_numpy()) - 1.0)
    return dict(sorted(out.items()))


@dataclass
class ExposureResult:
    first: date
    last: date
    n_days: int
    rf_annual: float | None
    strategies: dict[str, dict[str, Any]]
    yearly: dict[str, dict[int, float]]
    sensitivity: dict[str, dict[str, Any]]
    acceptance: dict[str, Any]
    components: dict[str, Any]
    cost_per_side: float
    target_vol: float | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def _variant(exp: pl.DataFrame, kind: str) -> pl.DataFrame:
    expr = {
        "full": pl.col("exposure"),
        "trend": pl.col("trend"),
        "abs_mom": pl.col("abs_mom"),
        "trend_abs_mom": 0.5 * (pl.col("trend") + pl.col("abs_mom")),
    }[kind]
    return exp.select("date", expr.alias("x"))


def evaluate(
    index: pl.DataFrame,
    rf_daily: pl.DataFrame,
    sell_share: pl.DataFrame,
    rf_annual: float | None,
    cfg: EngineConfig | None = None,
) -> ExposureResult:
    c = cfg or get_engine_config()
    ex_cfg: ExposureCfg = c.v2.exposure
    cost = c.costs.slippage_fraction / 2
    ret = (
        index.sort("date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"))
        .filter(pl.col("ret").is_not_null())
        .select("date", "ret")
    )
    exp = compute_exposure(index, rf_daily, sell_share, ex_cfg)
    full = simulate(exp, ret, rf_daily, cost_per_side=cost)
    full = full.filter(pl.col("e").is_not_null())
    dates = full["date"]
    window = pl.col("date").is_in(dates.implode())

    def run(frame: pl.DataFrame) -> pl.DataFrame:
        return simulate(frame, ret, rf_daily, cost_per_side=cost, column="x").filter(window)

    strategies: dict[str, dict[str, Any]] = {}
    series: dict[str, pl.DataFrame] = {}
    labels = {
        "full": "لایهٔ مواجهه (کامل)",
        "trend_abs_mom": "روند + تکانهٔ مطلق (بدون فشار صف و حد نوسان)",
        "trend": "فقط روند",
        "abs_mom": "فقط تکانهٔ مطلق",
    }
    for kind, label in labels.items():
        s = full if kind == "full" else run(_variant(exp, kind))
        series[label] = s
        strategies[label] = _stats(s, rf_annual)
    base = series[labels["full"]]
    for label, frame in {
        "شاخص هم‌وزن (نگه‌داشتن)": _fixed(base, None, "ew_ret"),
        "اخزا (نگه‌داشتن)": _fixed(base, None, "rf_ret"),
        "۵۰٪ شاخص + ۵۰٪ اخزا (ثابت)": _fixed(base, 0.5, "ew_ret"),
    }.items():
        series[label] = frame
        strategies[label] = portfolio_metrics(frame, risk_free_annual=rf_annual)

    sens: dict[str, dict[str, Any]] = {}
    for tv in ex_cfg.sensitivity_target_vols:
        e2 = compute_exposure(index, rf_daily, sell_share, ex_cfg, target_vol_annual=tv)
        s = simulate(e2, ret, rf_daily, cost_per_side=cost, column="exposure").filter(window)
        sens[f"{tv:.2f}"] = _stats(s, rf_annual)

    ew = strategies["شاخص هم‌وزن (نگه‌داشتن)"]
    bill = strategies["اخزا (نگه‌داشتن)"]
    me = strategies[labels["full"]]
    acceptance = {
        "max_drawdown_exposure": me["max_drawdown"],
        "max_drawdown_index": ew["max_drawdown"],
        "lower_drawdown_than_index": me["max_drawdown"] > ew["max_drawdown"],
        "total_return_exposure": me["total_return"],
        "total_return_bill": bill["total_return"],
        "total_return_index": ew["total_return"],
        "beats_bill": me["total_return"] > bill["total_return"],
    }
    acceptance["passed"] = bool(
        acceptance["lower_drawdown_than_index"] and acceptance["beats_bill"]
    )

    e_all = exp.filter(window)
    components = {
        "trend_on_share": float(e_all["trend"].mean()),  # type: ignore[arg-type]
        "abs_mom_on_share": float(e_all["abs_mom"].mean()),  # type: ignore[arg-type]
        "stress_mean": float(e_all["stress"].mean()),  # type: ignore[arg-type]
        "stress_min": float(e_all["stress"].min()),  # type: ignore[arg-type]
        "n_exposure_values": sorted({round(float(v), 3) for v in e_all["exposure"].drop_nulls()})[
            :12
        ],
        "index_vol_annual": float(np.std(ret.filter(window)["ret"].to_numpy(), ddof=1))
        * math.sqrt(trading_days_per_year(ret["date"])),
        "index_first_date": index["date"].min().isoformat(),  # type: ignore[union-attr]
        "rf_first_date": rf_daily["date"].min().isoformat(),  # type: ignore[union-attr]
        "sell_share_first_date": sell_share["date"].min().isoformat(),  # type: ignore[union-attr]
    }
    return ExposureResult(
        first=dates.min(),  # type: ignore[arg-type]
        last=dates.max(),  # type: ignore[arg-type]
        n_days=full.height,
        rf_annual=rf_annual,
        strategies=strategies,
        yearly={k: yearly_returns(v) for k, v in series.items()},
        sensitivity=sens,
        acceptance=acceptance,
        components=components,
        cost_per_side=cost,
        target_vol=ex_cfg.target_vol_annual,
    )


def _p(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{d}f}٪"


def render_markdown(r: ExposureResult) -> str:
    a = r.acceptance
    out = [
        "# R2 — لایهٔ مواجهه روی شاخص هم‌وزن و اخزا (دادهٔ واقعی)",
        "",
        f"- بازه: {r.first} تا {r.last}؛ {r.n_days} روز معاملاتی. بازه با کوتاه‌ترین ورودی تعیین شد: "
        f"اخزا از {r.components['rf_first_date']} (تکانهٔ مطلق ۱۲۶ روز به همین اندازه تاریخچه اخزا نیاز دارد)، "
        f"شاخص از {r.components['index_first_date']}، فشار صف از {r.components['sell_share_first_date']}.",
        "- سهم سهام = شاخص هم‌وزن رسمی؛ باقی = اخزا (جایگزین صندوق درآمد ثابت). مواجههٔ تصمیم‌گرفته‌شده در "
        "پایانی `t` روی بازدهٔ `t+1` اعمال می‌شود.",
        f"- هزینه: فقط لغزش پیکربندی ({_p(r.cost_per_side, 3)} برای هر طرف) روی بخشی از سبد که تغییر می‌کند. "
        "کارمزد، مالیات و کارمزد صندوق در مدل نیست.",
        "- هیچ پارامتری روی این داده تنظیم نشد (پنجره‌ها از ادبیات؛ `v2.exposure` در engine.yaml)، پس کل بازه "
        "خارج از نمونه است. نوسان هدف: "
        + (
            f"{_p(r.target_vol, 0)}"
            if r.target_vol
            else "تعیین نشده؛ حد نوسان خاموش است (OPEN_QUESTIONS 85)"
        )
        + ".",
        f"- میانگین نرخ بدون ریسک (اخزا) در بازه: {_p(r.rf_annual, 1)} سالانه.",
        "",
        "## نتیجهٔ معیار پذیرش",
        "",
        f"- حداکثر افت: لایهٔ مواجهه {_p(a['max_drawdown_exposure'])} در برابر شاخص {_p(a['max_drawdown_index'])} "
        f"→ {'کمتر ✔' if a['lower_drawdown_than_index'] else 'کمتر نیست ✘'}.",
        f"- بازده کل: لایهٔ مواجهه {_p(a['total_return_exposure'])}، اخزا {_p(a['total_return_bill'])}، "
        f"شاخص {_p(a['total_return_index'])} → "
        f"{'بیشتر از اخزا ✔' if a['beats_bill'] else 'بیشتر از اخزا نیست ✘'}.",
        f"- حکم R2: **{'گذشت' if a['passed'] else 'نگذشت'}** (فقط روی همین بازهٔ کوتاه؛ بخش محدودیت‌ها را ببینید).",
        "",
        "## مقایسه",
        "",
        "| سبد | بازده کل | بازده سالانه | نوسان سالانه | حداکثر افت | شارپ | متوسط مواجهه | گردش مواجهه/سال |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k, m in r.strategies.items():
        # the bill is the risk-free leg itself: its Sharpe (excess over its own mean) is noise
        sh = None if k.startswith("اخزا") else m.get("sharpe")
        out.append(
            f"| {k} | {_p(m.get('total_return'))} | {_p(m.get('annualized_return'))} | "
            f"{_p(m.get('annualized_volatility'))} | {_p(m.get('max_drawdown'))} | "
            f"{'—' if sh is None else f'{sh:.2f}'} | {_p(m.get('avg_exposure'), 0)} | "
            f"{'—' if m.get('exposure_turnover_per_year') is None else f'{m["exposure_turnover_per_year"]:.1f}'} |"
        )
    years = sorted({y for v in r.yearly.values() for y in v})
    out += ["", "## بازده تقویمی", "", "| سبد | " + " | ".join(str(y) for y in years) + " |"]
    out.append("|---|" + "---|" * len(years))
    for k, v in r.yearly.items():
        out.append(f"| {k} | " + " | ".join(_p(v.get(y)) for y in years) + " |")
    out += [
        "",
        "سال‌های ابتدا و انتها ناقص‌اند (بازه از وسط سال شروع/تمام می‌شود).",
        "",
        "## حساسیت به نوسان هدف (انتخاب نشده؛ فقط نمایش)",
        "",
        f"نوسان تحقق‌یافتهٔ شاخص در این بازه: {_p(r.components['index_vol_annual'])} سالانه.",
        "",
        "| نوسان هدف | بازده کل | حداکثر افت | نوسان سالانه | متوسط مواجهه |",
        "|---|---|---|---|---|",
    ]
    for tv, m in r.sensitivity.items():
        out.append(
            f"| {float(tv) * 100:.0f}٪ | {_p(m.get('total_return'))} | {_p(m.get('max_drawdown'))} | "
            f"{_p(m.get('annualized_volatility'))} | {_p(m.get('avg_exposure'), 0)} |"
        )
    c = r.components
    out += [
        "",
        "## اجزا",
        "",
        f"- روزهایی که روند روشن بود: {_p(c['trend_on_share'], 0)}؛ تکانهٔ مطلق روشن: {_p(c['abs_mom_on_share'], 0)}.",
        f"- ضریب فشار صف: میانگین {c['stress_mean']:.3f}، کمینه {c['stress_min']:.3f} "
        "(نزدیک ۱ یعنی تقریباً هیچ نمادی در صف فروش نبوده است).",
        "",
        "## محدودیت‌ها (بدون تعارف)",
        "",
        "- بازه حدود دو تا سه سال است و یک چرخهٔ تورمی-رونق را می‌بیند؛ این **گواه** نیست، فقط وارسی اولیه است. "
        "حتی «گذشت» به معنای سودآوری آینده نیست.",
        "- شاخص هم‌وزن رسمی ممکن است سود نقدی را شامل نکند؛ در این صورت بازده سهام کمتر از واقع برآورد شده و "
        "مقایسه با اخزا به ضرر سهام است (باز و مستند نشده).",
        "- شاخص قابل خرید مستقیم نیست؛ اجرای واقعی با سبد ۱۵–۲۰ نمادی متفاوت است (R3).",
        "- گردش مواجهه تنها با لغزش پیکربندی هزینه شده؛ کارمزد صندوق و کارمزد کارگزار نه.",
        "- سوگیری بقا در خود شاخص رسمی وجود ندارد، اما جهان R3 را تحت تأثیر قرار می‌دهد (OPEN_QUESTIONS 65).",
        "",
        "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="tmon-exposure-eval")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    from tmon.backtest.runner import mean_risk_free, risk_free_daily
    from tmon.core.db import session_scope
    from tmon.domain.rules import RuleBook
    from tmon.features.builder import build_features
    from tmon.features.store import load_benchmark_inputs, load_inputs

    cfg = get_engine_config()
    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        rules = RuleBook.from_session(session)
        index_daily, rf = load_benchmark_inputs(session)
    code = cfg.benchmarks.indices["equal_weight"]
    index = index_daily.filter(pl.col("index_code") == code).select("date", "close").sort("date")
    feats = build_features(prices, clients, rules, sectors=sectors)
    first_rf = rf["date"].min()
    rf_daily = risk_free_daily(rf, index.filter(pl.col("date") >= first_rf)["date"])
    rf_annual = mean_risk_free(rf, rf["date"].min(), rf["date"].max(), cfg)
    res = evaluate(index, rf_daily, sell_queue_share(feats), rf_annual, cfg)
    md = render_markdown(res)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(
            json.dumps(res.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
