"""Backtest reports: a metrics-only Markdown/JSON summary (committed to ``docs/reports``) and a
self-contained HTML page with equity curves (not committed)."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.runner import BacktestRun

METRIC_ROWS: Sequence[tuple[str, str, str, str]] = (
    # label, section, key, format
    ("تعداد معاملات", "trades", "n_trades", "int"),
    ("نرخ برد (پس از هزینه)", "trades", "win_rate", "pct"),
    ("نرخ برخورد به TP", "trades", "barrier_hit_rate", "pct"),
    ("میانگین برد", "trades", "avg_win", "pct"),
    ("میانگین باخت", "trades", "avg_loss", "pct"),
    ("نسبت برد به باخت", "trades", "payoff_ratio", "num"),
    ("امید ریاضی هر معامله (خالص)", "trades", "expectancy_net", "pct"),
    ("امید ریاضی هر معامله (ناخالص)", "trades", "expectancy_gross", "pct"),
    ("میانگین هزینهٔ رفت‌وبرگشت", "trades", "avg_round_trip_cost", "pct"),
    ("بازده کل", "portfolio", "total_return", "pct"),
    ("بازده سالانه", "portfolio", "annualized_return", "pct"),
    ("نوسان سالانه", "portfolio", "annualized_volatility", "pct"),
    ("نسبت شارپ", "portfolio", "sharpe", "num"),
    ("نسبت سورتینو", "portfolio", "sortino", "num"),
    ("حداکثر افت", "portfolio", "max_drawdown", "pct"),
)


def _fmt(v: Any, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "int":
        return f"{int(v):,}"
    if kind == "pct":
        return f"{100 * float(v):.2f}%"
    return f"{float(v):.2f}"


def _cell(section: dict[str, Any], key: str, kind: str) -> str:
    return _fmt(section.get(key), kind)


def to_dict(run: BacktestRun) -> dict[str, Any]:
    return {
        "meta": run.meta,
        "warnings": run.warnings,
        "strategies": {n: s.summary for n, s in run.strategies.items()},
        "benchmarks": run.benchmarks,
        "folds": [
            {"i": f.index, "train_cutoff": f.train_cutoff.isoformat(),
             "test_start": f.test_start.isoformat(), "test_end": f.test_end.isoformat(),
             "train_samples": n}
            for f, n in zip(run.folds, run.train_sizes, strict=False)
        ],
    }  # fmt: skip


def verdicts(run: BacktestRun, challenger: str, baseline: str | None) -> list[str]:
    """Plain statements the numbers support. Never softer than the numbers."""
    out: list[str] = []
    ch = run.strategies.get(challenger)
    if ch is None:
        return ["بدون نتیجهٔ قابل‌گزارش: دورهٔ آزمون خارج از نمونه وجود نداشت."]
    exp = ch.summary["trades"].get("expectancy_net")
    tr = ch.summary["portfolio"].get("total_return")
    if ch.summary["trades"].get("n_trades", 0) == 0:
        out.append(
            f"{challenger}: در دورهٔ خارج از نمونه هیچ سیگنالی از آستانه‌های موتور عبور نکرد؛ "
            "نتیجهٔ صادقانه «توصیه‌ای وجود ندارد» است."
        )
    if exp is not None:
        out.append(
            f"{challenger}: امید ریاضی هر معامله پس از هزینه {_fmt(exp, 'pct')} "
            + ("(مثبت)." if exp > 0 else "(منفی یا صفر: لبهٔ معنادار ثابت نشد).")
        )
    ew = run.benchmarks.get("equal_weight_universe", {}).get("portfolio", {}).get("total_return")
    if tr is not None and ew is not None:
        out.append(
            f"بازده کل {challenger} ({_fmt(tr, 'pct')}) "
            + ("بالاتر" if tr > ew else "پایین‌تر")
            + f" از خرید و نگهداری هم‌وزن بازار نقدشونده ({_fmt(ew, 'pct')}) است."
        )
    if baseline and baseline in run.strategies and baseline != challenger:
        b = run.strategies[baseline]
        be = b.summary["trades"].get("expectancy_net")
        btr = b.summary["portfolio"].get("total_return")
        if exp is not None and be is not None:
            better = exp > be and (tr is None or btr is None or tr > btr)
            out.append(
                f"نسبت به {baseline}: امید ریاضی {_fmt(exp, 'pct')} در برابر {_fmt(be, 'pct')}"
                + ("؛ مدل بهتر بود." if better else "؛ مدل از baseline بهتر نبود.")
            )
    return out


def _calibration_section(name: str, prob: dict[str, Any]) -> list[str]:
    lines = [f"## کالیبراسیون {name} (همهٔ ردیف‌های خارج از نمونه)", ""]
    if "auc" not in prob:
        return [*lines, "دادهٔ کافی برای ارزیابی احتمال‌ها نبود.", ""]
    skill = prob.get("brier_skill")
    lines += [
        f"- تعداد: {prob['n']:,} — نرخ پایهٔ برخورد به TP: {_fmt(prob['base_rate'], 'pct')} — "
        f"AUC: {prob['auc']:.3f}",
        f"- Brier: {prob['brier']:.4f} در برابر پیش‌بینی ثابت نرخ پایه {prob['brier_base_rate']:.4f}"
        f" (مهارت {_fmt(skill, 'num')})",
        "",
        "| بازهٔ p | تعداد | میانگین p | نرخ واقعی |",
        "| --- | --- | --- | --- |",
    ]
    for r in prob["calibration"]:
        if r["n"]:
            lines.append(
                f"| {r['bucket']} | {r['n']:,} | {_fmt(r['mean_p'], 'pct')} | "
                f"{_fmt(r['hit_rate'], 'pct')} |"
            )
    return [*lines, ""]


def render_markdown(
    run: BacktestRun,
    title: str,
    *,
    synthetic: bool = False,
    challenger: str | None = None,
    gate: dict[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> str:
    names = list(run.strategies)
    challenger = challenger or (names[-1] if names else "")
    baseline = names[0] if len(names) > 1 else None
    lines: list[str] = [f"# {title}", ""]
    if synthetic:
        lines += [
            "> **داده مصنوعی.** این گزارش فقط درستی خط لولهٔ بک‌تست را روی بازار تصادفی نشان می‌دهد "
            "و هیچ نتیجه‌ای دربارهٔ بازار واقعی نیست.",
            "",
        ]
    m = run.meta
    lines += [
        f"- تایم‌فریم: {m.get('timeframe')} — نمادها: {m.get('instruments')} — "
        f"تعداد fold: {m.get('folds')} (بازآموزی هر {m.get('retrain_every_days')} روز، "
        f"حداقل آموزش {m.get('min_train_days')} روز، purging + embargo = افق)",
        f"- لغزش (slippage) رفت‌وبرگشت: {_fmt(m.get('slippage_fraction'), 'pct')}",
        "",
    ]
    if run.warnings:
        lines += ["## هشدارها", ""] + [f"- {w}" for w in run.warnings] + [""]

    cols = [*names, *run.benchmarks]
    labels = {
        "equal_weight_all": "شاخص هم‌وزن (همهٔ نمادها)",
        "equal_weight_universe": "هم‌وزن بازار نقدشونده",
        "fixed_income": "درآمد ثابت",
    }
    lines += ["## مقایسهٔ کلی (خارج از نمونه، پس از هزینه)", ""]
    lines += ["| معیار | " + " | ".join(labels.get(c, c) for c in cols) + " |"]
    lines += ["| --- |" + " --- |" * len(cols)]
    for label, section, key, kind in METRIC_ROWS:
        cells = []
        for c in cols:
            if c in run.strategies:
                sec = run.strategies[c].summary.get(section, {})
            else:
                sec = run.benchmarks[c].get(section, {}) if section == "portfolio" else {}
            cells.append(_cell(sec, key, kind))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines.append("")

    for name, sr in run.strategies.items():
        reg = sr.summary.get("by_regime", {})
        lines += [f"## {name} به تفکیک رژیم", ""]
        lines += ["| رژیم | معاملات | نرخ برد | امید ریاضی (خالص) | بازده کل | حداکثر افت |"]
        lines += ["| --- | --- | --- | --- | --- | --- |"]
        for rname in ("normal", "halt", "post_reopen"):
            r = reg.get(rname)
            if not r:
                lines.append(f"| {rname} | 0 | — | — | — | — |")
                continue
            t, p = r["trades"], r["portfolio"]
            lines.append(
                f"| {rname} | {_fmt(t.get('n_trades', 0), 'int')} | {_cell(t, 'win_rate', 'pct')} | "
                f"{_cell(t, 'expectancy_net', 'pct')} | {_cell(p, 'total_return', 'pct')} | "
                f"{_cell(p, 'max_drawdown', 'pct')} |"
            )
        c = sr.summary.get("counts", {})
        lines += [
            "",
            f"سیگنال‌ها: {c.get('signals', 0):,} — انتخاب‌شده: {c.get('selected', 0):,} — "
            f"بدون برچسب (انتهای داده): {c.get('unresolved', 0):,} — "
            f"خرید ناممکن (صف خرید): {c.get('unfilled_buy_queue', 0):,} — "
            f"معاملهٔ انجام‌شده: {c.get('trades', 0):,}",
            "",
        ]
    for name, sr in run.strategies.items():
        if "probabilistic" in sr.summary:
            lines += _calibration_section(name, sr.summary["probabilistic"])
    if gate is not None:
        lines += ["## دروازهٔ سطح A", ""]
        lines.append(
            "- سطح A **مجاز** است."
            if gate["tier_a_allowed"]
            else "- سطح A **مجاز نیست**؛ هیچ سیگنال سطح A منتشر نمی‌شود."
        )
        lines += [f"  - {r}" for r in gate["reasons"]] + [""]
    if notes:
        lines += ["## یادداشت‌ها", ""] + [f"- {n}" for n in notes] + [""]
    if run.strategies:
        lines += ["## جمع‌بندی", ""] + [f"- {v}" for v in verdicts(run, challenger, baseline)] + [""]
    lines += [
        "رژیم `halt` (تعطیلی بازار) معامله ندارد و از آموزش و ارزیابی حذف شده است.",
        "",
    ]
    return "\n".join(lines)


def _svg_equity(series: dict[str, pl.DataFrame], width: int = 860, height: int = 280) -> str:
    colors = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"]
    curves: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, df in series.items():
        if df.is_empty():
            continue
        eq = np.cumprod(1.0 + df["ret"].to_numpy().astype(float))
        d = df["date"].to_numpy().astype("datetime64[D]").astype(int)
        curves[name] = (d, eq)
    if not curves:
        return ""
    x0 = min(c[0].min() for c in curves.values())
    x1 = max(c[0].max() for c in curves.values())
    y0 = min(c[1].min() for c in curves.values())
    y1 = max(c[1].max() for c in curves.values())
    pad = 30

    def sx(v: np.ndarray) -> np.ndarray:
        return np.asarray(pad + (v - x0) / max(x1 - x0, 1) * (width - 2 * pad))

    def sy(v: np.ndarray) -> np.ndarray:
        return np.asarray(height - pad - (v - y0) / max(y1 - y0, 1e-9) * (height - 2 * pad))

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" style="width:100%;direction:ltr">']
    for i, (name, (d, eq)) in enumerate(curves.items()):
        step = max(1, len(d) // 600)
        pts = " ".join(
            f"{a:.1f},{b:.1f}" for a, b in zip(sx(d[::step]), sy(eq[::step]), strict=True)
        )
        col = colors[i % len(colors)]
        parts.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.6" points="{pts}"/>')
        parts.append(
            f'<text x="{pad + 6}" y="{pad + 14 * (i + 1)}" fill="{col}" font-size="12">{html.escape(name)}</text>'
        )
    parts.append(
        f'<text x="{pad}" y="{height - 8}" font-size="11" fill="#666">'
        f"{date(1970, 1, 1).fromordinal(date(1970, 1, 1).toordinal() + int(x0))} → "
        f"{date(1970, 1, 1).fromordinal(date(1970, 1, 1).toordinal() + int(x1))}</text></svg>"
    )
    return "".join(parts)


def render_html(run: BacktestRun, title: str, *, synthetic: bool = False) -> str:
    md = render_markdown(run, title, synthetic=synthetic)
    series = {n: s.sim.daily for n, s in run.strategies.items()} | run.benchmark_daily
    body = html.escape(md)
    return (
        '<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:Vazirmatn,Tahoma,sans-serif;max-width:960px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.7}pre{white-space:pre-wrap}</style>"
        f"<h1>{html.escape(title)}</h1>{_svg_equity(series)}<pre>{body}</pre></html>"
    )


def write_reports(
    run: BacktestRun,
    *,
    title: str,
    md_path: Path | None = None,
    json_path: Path | None = None,
    html_path: Path | None = None,
    synthetic: bool = False,
    challenger: str | None = None,
    gate: dict[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> None:
    if md_path:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            render_markdown(
                run, title, synthetic=synthetic, challenger=challenger, gate=gate, notes=notes
            ),
            encoding="utf-8",
        )
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(to_dict(run), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    if html_path:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(run, title, synthetic=synthetic), encoding="utf-8")
