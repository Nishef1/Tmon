"""Order-book and queue research document for the site.

``python -m tmon.tools.orderbook_research`` condenses the two study files that
``tmon.backtest.realistic_study`` and ``tmon.backtest.book_study`` write into ``docs/data`` into
one JSON document (object store key ``v2/orderbook_research.json``). ``/research/orderbook-queue``
serves it to the model page; nothing in it is recomputed here, every number is copied from those
files.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from tmon.core.config import get_settings
from tmon.features.book_signal import DROPPED, REDUNDANT, SHORT_FEATURES
from tmon.storage.objectstore import get_object_store

KEY = "v2/orderbook_research.json"
DATA_DIR = Path(__file__).resolve().parents[4] / "docs" / "data"

# Persian name and plain-language meaning of every studied feature.
FEATURES: dict[str, tuple[str, str]] = {
    "tw_imbalance": (
        "عدم‌تعادل میانگین تابلو در طول جلسه",
        "(حجم صف خرید − حجم صف فروش) ÷ مجموع، در پنج سطح تابلو، میانگین وزن‌دار با زمان از ۹:۰۰ تا ۱۲:۳۰.",
    ),
    "close_imbalance": (
        "عدم‌تعادل تابلو در پایان روز",
        "همان نسبت، فقط روی تابلوی لحظهٔ بسته‌شدن بازار.",
    ),
    "tw_size_ratio": (
        "نسبت اندازهٔ سفارش‌ها",
        "لگاریتم نسبت میانگین حجم هر سفارش خرید به فروش در بهترین سطح؛ مثبت یعنی خریدارها درشت‌تر سفارش گذاشته‌اند.",
    ),
    "open_imbalance": (
        "عدم‌تعادل تابلو در شروع",
        "همان نسبت، روی تابلو در لحظهٔ شروع معاملهٔ پیوسته.",
    ),
    "last_close_gap": (
        "فاصلهٔ آخرین معامله تا قیمت پایانی",
        "(آخرین قیمت معامله − قیمت پایانی) ÷ قیمت پایانی؛ نشان می‌دهد معاملهٔ آخر روز به کدام سو کشیده شد.",
    ),
    "early_imbalance": (
        "عدم‌تعادل نیم‌ساعت اول",
        "میانگین زمانی عدم‌تعادل تابلو در ۳۰ دقیقهٔ اول؛ با عدم‌تعادل شروع و میانگین روز هم‌پوشان است.",
    ),
    "frac_buy_queue": (
        "سهم زمان در صف خرید",
        "کسری از جلسه که سمت فروش خالی و سمت خرید پُر بوده است.",
    ),
    "frac_sell_queue": (
        "سهم زمان در صف فروش",
        "کسری از جلسه که سمت خرید خالی و سمت فروش پُر بوده است.",
    ),
    "peak_queue_volume": (
        "بیشترین حجم صف",
        "بزرگ‌ترین حجم صف در طول روز؛ مثبت برای صف خرید، منفی برای صف فروش.",
    ),
    "queue_to_median": (
        "حجم صف نسبت به معاملات معمول",
        "ارزش بیشترین صف ÷ میانهٔ ارزش معاملات ۲۰ روز گذشته.",
    ),
    "depth_to_median": (
        "عمق تابلو نسبت به معاملات معمول",
        "ارزش پنج سطح تابلو ÷ میانهٔ ارزش معاملات ۲۰ روز گذشته.",
    ),
    "tw_depth_value": ("عمق تابلو (ارزش)", "مجموع ارزش پنج سطح خرید و فروش، میانگین زمانی."),
    "tw_spread": ("شکاف خرید و فروش", "(بهترین فروش − بهترین خرید) ÷ میانه، میانگین زمانی."),
    "queue_flip": (
        "چرخش تابلو در طول روز",
        "عدم‌تعادل پایان روز − عدم‌تعادل شروع روز؛ نشان می‌دهد تابلو در طول روز به کدام سو چرخیده است.",
    ),
    "days_in_queue": (
        "روزهای پیاپی در صف",
        "تعداد روزهای پشت‌سرهم نماد در صف خرید یا فروش بوده است.",
    ),
    "ret_1_norm": ("بازده روز نسبت به حدّ نوسان", "بازده امروز ÷ سقف مجاز نوسان روزانهٔ همان نماد."),
    "ind_net_flow_ratio": (
        "خالص جریان حقیقی",
        "(ارزش خرید حقیقی − ارزش فروش حقیقی) ÷ ارزش معاملات روز.",
    ),
    "ind_net_flow_z": ("خالص جریان حقیقی (استاندارد)", "خالص جریان حقیقی نسبت به معمول خود نماد."),
    "vol_to_base": ("حجم روز به حجم مبنا", "حجم معاملات امروز ÷ حجم مبنای نماد."),
    "rel_volume": ("حجم نسبی", "حجم امروز ÷ میانگین ۲۰ روز."),
    "intraday_range_pos": (
        "جای قیمت پایانی در دامنهٔ روز",
        "(پایانی − کمترین) ÷ (بیشترین − کمترین) همان روز.",
    ),
}

LIMITS = [
    "داده‌های تابلو فقط برای ۱۰۰ نمادِ پرمعامله و از حدود مرداد ۱۴۰۴ در دسترس است (۲۵۵ روز)؛ بازهٔ کوتاهی است.",
    "این بازه تقریباً یک‌سره صعودی بود (بازدهٔ سالانهٔ میانهٔ بازار بیش از ۲۰۰٪)؛ در بازار نزولی یا خنثی نتیجه ممکن است بسیار متفاوت باشد.",
    "شبیه‌ساز صف را ساده می‌گیرد: فرض می‌شود سفارش خرید در صف خرید فقط تا ۳ روز و سفارش فروش در صف فروش تا ۱۰ روز منتظر می‌ماند و حداکثر ۱۰٪ ارزش معاملات روز قابل اجراست.",
    "همهٔ عددهای حاصل از شبیه‌ساز پس از کارمزد و نسبت به نمادِ میانهٔ بازار است، نه نسبت به شاخص.",
    "این‌ها نتیجهٔ آزمایش روی تاریخ است، نه پیش‌بینی و نه توصیهٔ سرمایه‌گذاری؛ ما مشاور دارای مجوز نیستیم.",
]


def _pt(d: dict[str, Any]) -> dict[str, Any]:
    """The few fields of one simulation the site shows."""
    return {
        "excess": d["net_excess_annual"],
        "t": d["t"],
        "cagr": d.get("cagr"),
        "cagr_benchmark": d.get("cagr_benchmark"),
        "early": d.get("early"),
        "late": d.get("late"),
        "turnover": d.get("turnover"),
        "n": d.get("n"),
    }


def _ladder(real: dict[str, Any]) -> list[dict[str, Any]]:
    lad = real["ladder"]
    out = []
    for universe in ("all", "liquid100"):
        for review in (5, 20):
            base = f"{universe}_R{review}"
            out.append(
                {
                    "universe": universe,
                    "review": review,
                    "ideal": _pt(lad[f"{base}_ideal"]),
                    "locks": _pt(lad[f"{base}_locks"]),
                    "missed_buys": lad[f"{base}_locks"].get("missed_buys"),
                }
            )
    return out


def _capacity(real: dict[str, Any]) -> list[dict[str, Any]]:
    lad = real["ladder"]
    out = []
    for n in (1e7, 1e8, 1e9, 1e10, 1e11):
        cells = {
            f"{u}_R{r}": _pt(lad[f"{u}_R{r}_locks_N{n:.0e}"])
            for u in ("all", "liquid100")
            for r in (5, 20)
        }
        out.append({"notional_rial": n, "cells": cells})
    return out


def _features(book: dict[str, Any]) -> list[dict[str, Any]]:
    kept = [c for c, _ in SHORT_FEATURES]
    out = []
    for name, (label, meaning) in FEATURES.items():
        feat = book["features"].get(name)
        if feat is None:
            continue
        add = feat["added"]["w0.1_+" if feat["added"]["w0.1_+"]["5"]["mean"] >= 0 else "w0.1_-"]
        status = "kept" if name in kept else "redundant" if name in REDUNDANT else "dropped"
        if name not in kept and name not in REDUNDANT and name not in DROPPED:
            status = "dropped"
        out.append(
            {
                "key": name,
                "label": label,
                "meaning": meaning,
                "status": status,
                "alone_ic5": feat["alone"]["5"]["mean"],
                "d1": add["1"]["mean"],
                "t1": add["1"]["t"],
                "d5": add["5"]["mean"],
                "t5": add["5"]["t"],
                "d20": add["20"]["mean"],
                "t20": add["20"]["t"],
                "early5": add["5"]["early"],
                "late5": add["5"]["late"],
            }
        )
    order = {"kept": 0, "redundant": 1, "dropped": 2}
    kept_pos = {c: i for i, c in enumerate(kept)}
    out.sort(key=lambda r: (order[r["status"]], kept_pos.get(r["key"], 99), -r["d5"]))
    return out


def _sel(d: dict[str, Any], test: str) -> dict[str, Any]:
    return {
        "chosen": [c["feature"] for c in d["chosen"]],
        "d1": d[test]["1"]["mean"],
        "d5": d[test]["5"]["mean"],
        "t5": d[test]["5"]["t"],
        "d20": d[test]["20"]["mean"],
        "t20": d[test]["20"]["t"],
    }


def _score_sim(book: dict[str, Any]) -> list[dict[str, Any]]:
    s = book["simulation"]
    return [
        {
            "label": "بازبینی روزانه، کل بازه",
            "base": _pt(s["R1_all_dates_base"]),
            "book": _pt(s["R1_all_dates_book"]),
        },
        {
            "label": "بازبینی روزانه، نیمهٔ دوم (ویژگی‌ها با نیمهٔ اول انتخاب شده)",
            "base": _pt(s["R1_late_base"]),
            "book": _pt(s["R1_late_book_pick_early"]),
        },
        {
            "label": "بازبینی ۵ روزه، کل بازه",
            "base": _pt(s["R5_all_dates_base"]),
            "book": _pt(s["R5_all_dates_book"]),
        },
        {
            "label": "بازبینی ۵ روزه، نیمهٔ دوم (ویژگی‌ها با نیمهٔ اول انتخاب شده)",
            "base": _pt(s["R5_late_base"]),
            "book": _pt(s["R5_late_book_pick_early"]),
        },
    ]


def build(real: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    rb = real["random_baseline"]
    sel = book["selection"]
    return {
        "generated": date.today().isoformat(),
        "book_days": book["dates"],
        "book_rows": book["rows"],
        "split": sel["split"],
        "assumptions": {
            "cost_per_side": real["cost"],
            "max_wait_buy": real["max_wait_buy"],
            "max_wait_sell": real["max_wait_sell"],
            "participation": real["participation"],
        },
        "ladder": _ladder(real),
        "capacity": _capacity(real),
        "random": {
            "r5_zero_cost": rb["R5_zero_cost"]["net_excess_annual"],
            "r5_with_cost": rb["R5_with_cost"]["net_excess_annual"],
            "r20_zero_cost": rb["R20_zero_cost"]["net_excess_annual"],
            "r20_with_cost": rb["R20_with_cost"]["net_excess_annual"],
            "turnover": rb["R5_with_cost"]["turnover"],
        },
        "base_ic": {h: {"ic": v["mean"], "t": v["t"]} for h, v in book["base"].items()},
        "features": _features(book),
        "selection": {
            "pick_early_test_late": _sel(sel["h5_w0.1_pick_early"], "test_late"),
            "pick_late_test_early": _sel(sel["h5_w0.1_pick_late"], "test_early"),
            "all": {
                "chosen": [c["feature"] for c in sel["h5_w0.1_all"]["chosen"]],
                "d1": sel["h5_w0.1_all"]["gain"]["1"]["mean"],
                "d5": sel["h5_w0.1_all"]["gain"]["5"]["mean"],
                "t5": sel["h5_w0.1_all"]["gain"]["5"]["t"],
                "d20": sel["h5_w0.1_all"]["gain"]["20"]["mean"],
                "t20": sel["h5_w0.1_all"]["gain"]["20"]["t"],
            },
        },
        "score_sim": _score_sim(book),
        "limits": LIMITS,
    }


def build_document(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    real = json.loads((data_dir / "realistic-study.json").read_text(encoding="utf8"))
    book = json.loads((data_dir / "book-study.json").read_text(encoding="utf8"))
    return build(real, book)


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-orderbook-research")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    a = ap.parse_args()
    doc = build_document(Path(a.data_dir))
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    get_object_store().put(get_settings().minio_artifact_bucket, KEY, data, "application/json")
    if a.out:
        Path(a.out).write_bytes(data)
    print(f"{KEY}: {len(data)} bytes")


if __name__ == "__main__":
    main()
