"""Run the ADR 0004 study on the live data and write the report and the JSON.

``python -m tmon.tools.invested_study --md docs/reports/invested-book-2026-11-17.md
--json docs/data/invested-study.json``

Nothing is tuned and nothing is decided here: it measures S0-S6 and the decile profile and prints
what the pre-registered rules say. The site's verdict code is not touched by this tool.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.exposure_eval import sell_queue_share
from tmon.backtest.invested_study import (
    CODES,
    LABELS,
    StudyData,
    decile_table,
    profile_summary,
    run_study,
    verdict_horizon,
)
from tmon.backtest.runner import risk_free_daily
from tmon.backtest.signal_decay import adjusted_close, build_panel
from tmon.backtest.v2_gates import basket_index, build_matrices, restrict_top_liquid
from tmon.core.db import session_scope
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.engine.exposure import compute_exposure
from tmon.features.builder import build_features
from tmon.features.store import load_benchmark_inputs, load_inputs

BASKET = 100


def _align(dates: list[Any], frame: pl.DataFrame, col: str) -> np.ndarray:
    base = pl.DataFrame({"date": dates, "_i": np.arange(len(dates))})
    j = base.join(frame.select("date", col), on="date", how="left").sort("_i")
    return j[col].cast(pl.Float64).fill_null(float("nan")).to_numpy()


def _fill_short_gaps(x: np.ndarray, max_gap: int = 10) -> np.ndarray:
    """Carry the last decided value across runs of at most ``max_gap`` unknown days (days the
    index has no row, such as holidays with a price bar). Longer gaps stay unknown."""
    out = x.copy()
    bad = np.flatnonzero(~np.isfinite(x))
    if not bad.size:
        return out
    for run in np.split(bad, np.flatnonzero(np.diff(bad) > 1) + 1):
        if run[0] > 0 and np.isfinite(out[run[0] - 1]) and run.size <= max_gap:
            out[run] = out[run[0] - 1]
    return out


def build_study(
    phases: list[int], cfg: EngineConfig | None = None, log: Any = None
) -> dict[str, Any]:
    cfg = cfg or get_engine_config()
    inv = cfg.v2.invested
    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        rules = RuleBook.from_session(session)
        index_daily, rf = load_benchmark_inputs(session)
    code = cfg.benchmarks.indices["equal_weight"]
    ew = index_daily.filter(pl.col("index_code") == code).select("date", "close").sort("date")
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    horizons = tuple(inv.profile_horizons)
    panel = build_panel(feats, adj, cfg, horizons=horizons)
    m = restrict_top_liquid(
        build_matrices(feats, adj, panel, sectors, rules, cfg),
        inv.profile_top_n,
        cfg.v2.portfolio.min_cross_section,
    )
    rf_daily = risk_free_daily(rf, ew.filter(pl.col("date") >= rf["date"].min())["date"])
    exposure = compute_exposure(ew, rf_daily, sell_queue_share(feats), cfg.v2.exposure)
    n = len(m.dates)
    official = ew.with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"))
    own = basket_index(m, cfg.v2.portfolio.review_every_days)
    rf_arr = _align(m.dates, rf_daily.rename({"ret": "rf"}), "rf")
    data = StudyData(
        m=m,
        expo=_fill_short_gaps(_align(m.dates, exposure.rename({"exposure": "e"}), "e")),
        rf=np.nan_to_num(rf_arr),
        rf_known=np.isfinite(rf_arr),
        official=_align(m.dates, official, "ret"),
        own_index=_align(m.dates, own, "ret"),
        cfg=cfg,
    )
    t0 = time.time()
    done = {"n": 0}

    def progress(c: str, ph: int, cost: float) -> None:
        done["n"] += 1
        if log and done["n"] % 20 == 0:
            log(f"  {done['n']} runs, {time.time() - t0:.0f}s (last {c} phase {ph} x{cost})")

    study = run_study(data, phases, progress=progress)
    sens = run_study(data, phases, redeploy_idle=True, progress=progress)
    study["sensitivity_redeploy"] = {
        "judged": sens["judged"],
        "winner": sens["winner"],
        "winner_exposure_rule": sens["winner_exposure_rule"],
        "configs": {
            c: {k: v for k, v in sens["configs"][c]["base"].items() if k != "years"} for c in CODES
        },
    }

    lo = m.start + inv.warmup_days + max(phases)
    round_trip = float((m.buy_cost[lo:] + m.sell_cost[lo:]).mean())
    liquidity = feats.select("instrument_id", "date", "median_value_20")
    profiles: dict[str, Any] = {}
    for h in horizons:
        primary = profile_summary(
            decile_table(panel, liquidity, h, top_n=inv.profile_top_n), round_trip, cfg
        )
        glob = profile_summary(decile_table(panel, liquidity, h, top_n=None), round_trip, cfg)
        profiles[str(h)] = {"basket": primary, "global": glob}
    h_best, why = verdict_horizon({h: profiles[str(h)]["basket"] for h in horizons})
    study.update(
        {
            "profiles": profiles,
            "verdict_horizon": h_best,
            "verdict_horizon_basis": why,
            "round_trip_cost": round_trip,
            "basket_size": inv.profile_top_n,
            "inflation_yoy": _inflation(),
            "universe_days": n,
            "last_date": m.dates[-1].isoformat(),
        }
    )
    return study


def _inflation() -> dict[str, Any] | None:
    path = Path(__file__).resolve().parents[4] / "docs" / "data" / "inflation.csv"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        yoy = [r for r in csv.DictReader(f) if r["series"] == "cpi_yoy"]
    if not yoy:
        return None
    row = max(yoy, key=lambda r: r["ref_period"])
    return {"value": float(row["value"]), "ref_period": row["ref_period"]}


# ------------------------------------------------------------------------------- the report


def _p(x: float | None, d: int = 1) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{d}f}٪"


def _n(x: float | None, d: int = 2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def _ok(b: bool) -> str:
    return "✔" if b else "✘"


def _summary(r: dict[str, Any]) -> list[str]:
    cf, j, refs = r["configs"], r["judged"], r["refs"]
    s0 = cf["S0"]["base"]["ann"]
    off = refs["full"]["official"]["ann"]
    bill = refs["exposure"]["bill"]["ann"]
    passed = [c for c in CODES[1:] if j[c]["passes"]]
    wn = r["winner"]
    sv = r["sensitivity_redeploy"]
    return [
        f"- بازدهٔ سالانهٔ S0 (معیار): {_p(s0)}؛ شاخص هم‌وزن رسمی {_p(off)}؛ اخزای بدون ریسک {_p(bill)}. "
        + (
            "معیار از اخزا کمتر بود، یعنی نگه‌داشتن سبد هم‌وزن در این بازه نسبت به اخزا ضرر داشته است."
            if s0 < bill
            else "معیار از اخزا بیشتر بود."
        ),
        "- پیکربندی‌هایی که قاعدهٔ داوری را گذراندند: "
        + ("، ".join(passed) if passed else "هیچ‌کدام")
        + ".",
        f"- برندهٔ مکانیکی: {wn}."
        + (
            f" S3 در اجرای پایه {_p(cf['S3']['base']['ann'])} در برابر {_p(off)} شاخص رسمی بود؛ "
            "از شاخص رسمی جلو نیست."
            if cf["S3"]["base"]["ann"] < off
            else ""
        ),
        "- لایهٔ مواجهه: "
        + (
            "اعمال شود."
            if r["winner_exposure_rule"]["apply_exposure"]
            else "اعمال نشود (شرط‌ها در بخش «قاعدهٔ داوری» آمده است)."
        ),
        f"- حساسیت به قاعدهٔ پول بی‌کار: برنده {sv['winner']}"
        + (" (همان)." if sv["winner"] == wn else " (فرق دارد؛ بخش حساسیت را ببینید)."),
        "- همهٔ این‌ها در یک رژیم صعودی تورمی و با سوگیری بقای باز (G6) است؛ هیچ‌کدام توصیه نیست.",
    ]


def render_markdown(r: dict[str, Any], cfg: EngineConfig) -> str:
    inv = cfg.v2.invested
    w, we = r["windows"]["full"], r["windows"]["exposure"]
    cf, j = r["configs"], r["judged"]
    s0e = r["s0_on_exposure_window"]
    refs = r["refs"]
    same = w == we
    out: list[str] = [
        "# مطالعهٔ سبد همیشه سرمایه‌گذاری‌شده (ADR 0004، مرحلهٔ ۲)",
        "",
        "> رتبه‌بندی مدل، توصیه نیست. این گزارش فقط اندازه می‌گیرد؛ هیچ حکمی در سایت را عوض نمی‌کند.",
        "",
        "هفت پیکربندی S0 تا S6 و فقط همین‌ها، با عددهای از پیش ثبت‌شدهٔ ADR 0004 و "
        "`v2.invested` در `engine.yaml`، روی دادهٔ واقعی اجرا شد. هیچ عددی روی این داده تنظیم نشد. "
        "تعداد پیکربندی‌های این مطالعه برای شمارش G4: "
        f"{r['n_configs_run']} (افزون بر ۵ پیکربندی R3 و ۲۰ ترکیب سیگنال-افق R1).",
        "",
        "## خلاصه",
        "",
        *_summary(r),
        "",
        "## روش در یک نگاه",
        "",
        f"- جهان قابل‌معامله: {r['basket_size']} نماد پرنقدشونده در هر روز، بدون نماد در صف خرید. "
        "سفارش روز `t` در پایانی `t+1` اجرا می‌شود؛ خرید در صف خرید لغو و فروش در صف فروش به روز بعد "
        "می‌رود؛ هزینه از `market_rules` به‌اضافهٔ لغزش، فقط روی مقدار معامله‌شده.",
        f"- S0 هر {inv.core_review_days} روز معاملاتی عضویت را بازبینی می‌کند و بین بازبینی‌ها نمی‌فروشد.",
        "- هر پیکربندی با چند فاز شروع (شروع چند روز دیرتر) اجرا شد: "
        f"{len(r['phases'])} فاز، از {r['phases'][0]} تا {r['phases'][-1]} روز دیرتر. همهٔ فازها روی "
        "یک بازهٔ ثابت سنجیده می‌شوند. اجرای پایه فاز صفر است؛ شرط‌های ۱ و ۲ و ۴ روی آن و شرط ۳ روی همهٔ فازها خوانده شد.",
        f"- بازهٔ سنجش: {w['first']} تا {w['last']} (شروع سبد {w['book_start']}). "
        + (
            "مواجهه برای همهٔ این روزها شناخته است، پس هر هفت پیکربندی روی یک بازه‌اند."
            if same
            else f"S4 تا S6 به لایهٔ مواجهه نیاز دارند که فقط از {we['book_start']} شناخته است، پس بازه‌شان "
            f"کوتاه‌تر است: {we['first']} تا {we['last']}؛ S0 روی همین روزها هم برای مقایسهٔ منصفانه اجرا شد."
        ),
        "- بازده‌ها اسمی‌اند. سری تورم فقط یک نقطه دارد (آخرین دورهٔ مرجع)، پس بازدهٔ واقعی فقط برای "
        "۲۵۲ روز آخر و به‌صورت تقریبی آمده است.",
        "",
        "## نتیجهٔ اجرای پایه (بازهٔ کامل)",
        "",
        "| کد | راهبرد | بازده سالانهٔ خالص | تفاوت با S0 | نیمهٔ اول | نیمهٔ دوم | حداکثر افت | نوسان | گردش یک‌طرفهٔ ماهانه | سهم سهام | نماد | بازده با هزینهٔ ۱٫۵× |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in CODES[:4]:
        b = cf[c]["base"]
        d = None if c == "S0" else j[c]["ann_diff_base"]
        out.append(
            f"| {c} | {LABELS[c]} | {_p(b['ann'])} | {_p(d)} | {_p(b['ann_h1'])} | {_p(b['ann_h2'])} | "
            f"{_p(b['mdd'])} | {_p(b['vol'])} | {_p(b['turnover_monthly'], 0)} | {_p(b['equity_share'], 0)} | "
            f"{_n(b['names'], 1)} | {_p(cf[c]['heavy']['ann'])} |"
        )
    for lab, src in (
        ("شاخص هم‌وزن رسمی (مرجع)", refs["full"]["official"]),
        ("شاخص خودِ سبد با بازتعادل ۵ روزه (معیار G1)", refs["full"]["own_index"]),
    ):
        out.append(
            f"| — | {lab} | {_p(src['ann'])} | | {_p(src['ann_h1'])} | {_p(src['ann_h2'])} | "
            f"{_p(src['mdd'])} | | | | | |"
        )
    out += [
        "",
        f"## S4 تا S6 ({we['first']} تا {we['last']})",
        "",
        "| کد | راهبرد | بازده سالانهٔ خالص | تفاوت با S0 | نیمهٔ اول | نیمهٔ دوم | حداکثر افت | نوسان | سهم سهام | بازده با ۱٫۵× |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| S0 | همان معیار روی این روزها | {_p(s0e['base']['ann'])} | | {_p(s0e['base']['ann_h1'])} | "
        f"{_p(s0e['base']['ann_h2'])} | {_p(s0e['base']['mdd'])} | {_p(s0e['base']['vol'])} | "
        f"{_p(s0e['base']['equity_share'], 0)} | {_p(s0e['heavy']['ann'])} |",
    ]
    for c in CODES[4:]:
        b = cf[c]["base"]
        out.append(
            f"| {c} | {LABELS[c]} | {_p(b['ann'])} | {_p(j[c]['ann_diff_base'])} | {_p(b['ann_h1'])} | "
            f"{_p(b['ann_h2'])} | {_p(b['mdd'])} | {_p(b['vol'])} | {_p(b['equity_share'], 0)} | "
            f"{_p(cf[c]['heavy']['ann'])} |"
        )
    for lab, k in (("شاخص هم‌وزن رسمی (مرجع)", "official"), ("اخزا (بدون ریسک)", "bill")):
        src = refs["exposure"][k]
        out.append(
            f"| — | {lab} | {_p(src['ann'])} | | {_p(src['ann_h1'])} | {_p(src['ann_h2'])} | "
            f"{_p(src['mdd'])} | | | |"
        )
    out += [
        "",
        "## همهٔ فازهای شروع",
        "",
        "تفاوت بازدهٔ سالانهٔ خالص با S0 (همان فاز و همان روزها)؛ شرط ۳ می‌خواهد "
        f"دست‌کم {_p(inv.min_phase_share, 0)} فازها هر سه بازه (کل و دو نیمه) را ببرند.",
        "",
        "| کد | میانه | بدترین | بهترین | سهم فازهای برنده |",
        "|---|---|---|---|---|",
    ]
    for c in CODES[1:]:
        x = j[c]
        out.append(
            f"| {c} | {_p(x['ann_diff_median'])} | {_p(x['ann_diff_worst'])} | "
            f"{_p(x['ann_diff_best'])} | {_p(x['phase_share'], 0)} |"
        )
    out += [
        "",
        "## قاعدهٔ داوری (بند ۴ ADR)",
        "",
        "| کد | ۱: بازده بیشتر در کل و هر دو نیمه | ۲: افت بیشتر نیست | ۳: سه‌چهارم فازها | ۴: با هزینهٔ ۱٫۵× | گذشت | t مازاد ماهانه (ماه) |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in CODES[1:]:
        x = j[c]
        out.append(
            f"| {c} | {_ok(x['c1'])} | {_ok(x['c2'])} | {_ok(x['c3'])} | {_ok(x['c4'])} | "
            f"**{_ok(x['passes'])}** | {_n(x['excess_t'])} ({x['excess_months']}) |"
        )
    wn = r["winner"]
    rule = r["winner_exposure_rule"]
    out += [
        "",
        f"**برندهٔ مکانیکی: {wn}** ({LABELS[wn]}). "
        + (
            "هیچ راهبرد انتخابی همهٔ چهار شرط را نگذراند، پس معیار می‌ماند."
            if wn == "S0"
            else "این راهبرد هر چهار شرط را گذراند."
        ),
        "",
        "لایهٔ مواجهه فقط وقتی روی برنده اعمال می‌شود که افت S4 از S0 بیشتر نباشد و S4 در هر دو نیمه از اخزا جلو بزند: "
        f"افت بیشتر نیست {_ok(rule['mdd_not_deeper'])}؛ جلو از اخزا در هر دو نیمه {_ok(rule['beats_bill_both_halves'])}؛ "
        f"**نتیجه: {'اعمال شود' if rule['apply_exposure'] else 'اعمال نشود'}**.",
        "",
        "## بازدهٔ تقویمی (اجرای پایه)",
        "",
        "| سال | " + " | ".join(CODES[:4]) + " | روز |",
        "|---|" + "---|" * 5,
    ]
    years = sorted(cf["S0"]["base"]["years"], key=int)
    for y in years:
        cells = [_p(cf[c]["base"]["years"].get(y, {}).get("ret")) for c in CODES[:4]]
        out.append(f"| {y} | " + " | ".join(cells) + f" | {cf['S0']['base']['years'][y]['days']} |")
    out += [
        "",
        "## شمارش‌های سفارش (اجرای پایه)",
        "",
        "| کد | خرید اجراشده | خرید لغوشده | جایگزین | فروش موکول | معاملهٔ هسته که نشد |",
        "|---|---|---|---|---|---|",
    ]
    for c in CODES:
        b = cf[c]["base"]
        out.append(
            f"| {c} | {b['n_buys']} | {b['cancelled_buys']} | {b['replacements']} | "
            f"{b['postponed_sells']} | {b['core_skipped']} |"
        )
    infl = r.get("inflation_yoy")
    if infl:
        out += [
            "",
            "## بازدهٔ واقعی (تقریبی)",
            "",
            f"تنها نقطهٔ تورم موجود {_p(infl['value'])} برای دورهٔ مرجع {infl['ref_period']} است. "
            "این فقط برای نشان‌دادن مقیاس است و بازدهٔ واقعی هر سال را نمی‌دهد: بازدهٔ اسمی "
            f"S0 در کل بازه {_p(cf['S0']['base']['ann'])} در سال است و اگر تورم یک سال به‌اندازهٔ همین نقطه "
            f"بود، بازدهٔ واقعی تقریبی همان سال {_p((1 + cf['S0']['base']['ann']) / (1 + infl['value']) - 1)} می‌شد.",
        ]
    sv = r["sensitivity_redeploy"]
    out += [
        "",
        "## حساسیت: پول نقد بی‌کار به هسته برگردد",
        "",
        "در اجرای اصلی، سفارشی که اجرا نمی‌شود (مثلاً خرید هسته در صف خرید) تا بازبینی بعدی کنار می‌ماند و "
        "پولش اخزا می‌گیرد. این قاعده پیش از دیدن داده نوشته شد، ولی S0 فقط هر "
        f"{inv.core_review_days} روز معامله می‌کند و پول بی‌کارش دیرتر برمی‌گردد، در حالی که سبدهای انتخابی "
        "با هر فروش پول را به هسته برمی‌گردانند. برای دیدن اثر این نابرابری، همهٔ هفت پیکربندی یک بار هم "
        "با قاعدهٔ «پول بی‌کار فردا به هسته برگردد» اجرا شد. نتیجهٔ اصلی همان اجرای اول است.",
        "",
        "| کد | بازده سالانه | تفاوت با S0 | سهم سهام | گذشت |",
        "|---|---|---|---|---|",
        f"| S0 | {_p(sv['configs']['S0']['ann'])} | | {_p(sv['configs']['S0']['equity_share'], 0)} | |",
    ]
    for c in CODES[1:]:
        out.append(
            f"| {c} | {_p(sv['configs'][c]['ann'])} | {_p(sv['judged'][c]['ann_diff_base'])} | "
            f"{_p(sv['configs'][c]['equity_share'], 0)} | {_ok(sv['judged'][c]['passes'])} |"
        )
    out += [
        "",
        f"برندهٔ مکانیکی با این قاعده: **{sv['winner']}**"
        + (" (همان نتیجهٔ اصلی)." if sv["winner"] == wn else " (با نتیجهٔ اصلی فرق دارد)."),
    ]
    out += ["", "## نیم‌رخ دهک‌ها (بند ۵ ADR)", ""]
    out.append(
        f"مازاد میانگین بازدهٔ هر دهک امتیاز نسبت به میانگین جهان، پیش از هزینه؛ هزینهٔ رفت‌وبرگشت "
        f"{_p(r['round_trip_cost'], 2)}. جهان: {r['basket_size']} نماد پرنقدشونده بدون صف خرید، "
        "رتبه‌بندی دوباره درون همین سبد (روش اصلی)؛ نتیجهٔ دهک‌بندی امتیاز سراسری برای مقایسه آمده است."
    )
    for h, pr in r["profiles"].items():
        for kind, title in (("basket", "درون سبد (اصلی)"), ("global", "امتیاز سراسری (مقایسه)")):
            p = pr[kind]
            out += [
                "",
                f"### افق {h} روز — {title}",
                "",
                "| دهک | مازاد | نیمهٔ اول | نیمهٔ دوم | t |",
                "|---|---|---|---|---|",
            ]
            for d in reversed(p["deciles"]):
                out.append(
                    f"| {d['decile']}{' (بالا)' if d['decile'] == 10 else ' (پایین)' if d['decile'] == 1 else ''} | "
                    f"{_p(d['excess'], 2)} | {_p(d['h1'], 2)} | {_p(d['h2'], 2)} | {_n(d['t'])} |"
                )
            for key, name in (("candidate", "ناحیهٔ نامزد"), ("avoid", "ناحیهٔ پرهیز")):
                z = p[key]
                if not z["deciles"]:
                    out.append(f"\n{name}: خالی.")
                else:
                    out.append(
                        f"\n{name}: دهک‌های {'، '.join(map(str, z['deciles']))}؛ خالص {_p(z['net'], 2)} "
                        f"(نیمهٔ اول {_p(z['net_h1'], 2)}، نیمهٔ دوم {_p(z['net_h2'], 2)})، t = {_n(z['t'])}؛ "
                        f"**درجه: {z['grade']}**."
                    )
    vh = r["verdict_horizon"]
    out += [
        "",
        f"**افق حکم: {vh} روز** ({r['verdict_horizon_basis']}). "
        "قاعده: از ۲۰ و ۶۰ روز، افقی که مازاد خالص دهک بالا در آن بزرگ‌تر و در هر دو نیمه مثبت است؛ "
        "اگر هیچ‌کدام نبود، ۶۰ روز با درجهٔ «ثابت‌نشده».",
        "",
        "## آنچه آزموده نشد و محدودیت‌ها",
        "",
        "- دادهٔ ما عمدتاً یک رژیم صعودی تورمی را می‌بیند؛ نیمهٔ دوم زمان همان رژیم را ادامه می‌دهد، پس «هر دو نیمه» "
        "دو آزمون مستقل از رژیم نیست.",
        "- سوگیری بقا (G6) باز است: زیان روزهای پس از آخرین معامله (تعلیق و حذف) در سری نیست. "
        "این به نفع هر راهبرد نگه‌داری است، S0 هم.",
        "- سری اخزا در ۲۰۲۶-۱۱-۱۶ از ۲۰۱۹ به بعد تکمیل شد؛ پیش از ۲۰۲۳-۱۲ اخزای انتخاب‌شده عمرش بیشتر از یک سال "
        "بود (۳۷۲ تا ۷۵۸ روز)، پس بازدهٔ نقد و تکانهٔ مطلق در آن سال‌ها کمتر دقیق است. R2 با سری کوتاه‌تر اجرا شده بود و "
        "بازه‌اش از ۲۰۲۴-۰۶ بود؛ این مطالعه آن را تکرار نمی‌کند.",
        "- معیار G1 («شاخص خودِ سبد») عوض نشد (OQ ۱۰۹)؛ بالا در کنار S0 آمده است.",
        "- رتبهٔ S2 و S3 همان امتیاز سراسری R3 است، ولی دهک‌های نیم‌رخ و حذف ۳۰٪ پایین در S1 "
        "درون سبد دوباره رتبه‌بندی می‌شوند. این دو یکی نیستند و نتیجه‌ها را نباید یکی دانست.",
        "- مواجهه روی روز `t` تصمیم و در پایانی `t+1` اجرا می‌شود (محافظه‌کارتر از R2). S4 تا S6 بازهٔ کوتاه‌تری دارند "
        "و با S0 روی همان روزها مقایسه شدند.",
        "- فازها فقط شروع را جابه‌جا می‌کنند؛ بازبینی ۶۰ روزه و ۱۵ روزه هر کدام در همهٔ روزهای ممکن آزموده نشد "
        f"(گام فاز {r['phases'][1] - r['phases'][0] if len(r['phases']) > 1 else 0} روز).",
        "- پایین‌ترین دهک‌ها ممکن است نمادهای کم‌نقد یا نزدیک صف فروش باشند؛ فروش کوتاه‌مدت در این بازار ممکن نیست "
        "و «پرهیز» فقط یعنی نخر.",
        "- اندازهٔ هیچ‌یک از ناحیه‌ها وعدهٔ بازده بیشتر از بازار نیست.",
        "",
        "> این گزارش تحلیل فنی و آموزشی است، نه توصیهٔ سرمایه‌گذاری.",
        "",
    ]
    return "\n".join(out)


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-invested-study")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--phase-step", type=int, default=5, help="days between start phases (0..59)")
    ap.add_argument("--max-phase", type=int, default=59)
    args = ap.parse_args(argv)
    phases = list(range(0, args.max_phase + 1, args.phase_step))
    cfg = get_engine_config()
    res = build_study(phases, cfg, log=lambda s: print(s, file=sys.stderr, flush=True))
    md = render_markdown(res, cfg)
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(
            json.dumps(_clean(res), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
