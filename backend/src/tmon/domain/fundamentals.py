"""Price-to-earnings figures from the exchange's own EPS and its industry-group P/E.

Pure functions: the numbers come from the instrument's stored TSETMC fields, nothing is
estimated here. P/E is price divided by EPS, so it follows today's close."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fundamental:
    eps: float | None  # rial per share, the issuer's estimate as published by TSETMC
    pe: float | None  # close / eps; None when EPS is missing or not positive
    sector_pe: float | None  # the group's P/E as published by TSETMC
    vs_sector: float | None  # pe / sector_pe - 1
    verdict: str  # cheap | fair | expensive | loss | unknown, against the group
    text: str  # plain-language reading


CHEAP, EXPENSIVE = 0.8, 1.25  # P/E below 80% of the group's is "cheaper", above 125% "dearer"


def _fmt(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", "٬").replace(".", "٫")


def fundamental(
    eps: float | None, sector_pe: float | None, close: float | None, group: str | None
) -> Fundamental:
    sp = sector_pe if sector_pe and sector_pe > 0 else None
    if eps is None:
        return Fundamental(
            None,
            None,
            sp,
            None,
            "unknown",
            "سود هر سهم (EPS) این نماد در بورس ثبت نشده است؛ نسبت قیمت به سود قابل محاسبه نیست.",
        )
    if eps < 0:
        return Fundamental(
            eps,
            None,
            sp,
            None,
            "loss",
            f"طبق برآورد ناشر، شرکت زیان‌ده است (سود هر سهم {_fmt(eps, 0)} ریال)؛ "
            "نسبت قیمت به سود (P/E) برایش معنا ندارد.",
        )
    if not close or close <= 0:
        return Fundamental(eps, None, sp, None, "unknown", "قیمت این نماد برای محاسبهٔ P/E نیست.")
    pe = close / eps
    head = (
        f"هر سهم طبق برآورد ناشر سالانه {_fmt(eps, 0)} ریال سود می‌سازد و قیمتش {_fmt(pe)} برابر "
        f"آن است؛ یعنی اگر سود ثابت بماند حدود {_fmt(pe, 0)} سال طول می‌کشد تا سود شرکت پول سهم "
        "را برگرداند."
    )
    if sp is None:
        return Fundamental(eps, pe, None, None, "unknown", head + " P/E گروه در بورس ثبت نشده است.")
    rel = pe / sp
    if rel < CHEAP:
        verdict, word = "cheap", "ارزان‌تر از میانگین گروه"
    elif rel > EXPENSIVE:
        verdict, word = "expensive", "گران‌تر از میانگین گروه"
    else:
        verdict, word = "fair", "نزدیک به میانگین گروه"
    where = f"گروه «{group}»" if group else "گروه"
    text = (
        f"{head} میانگین P/E {where} {_fmt(sp)} است؛ این سهم {word} معامله می‌شود. "
        "ارزان یا گران‌بودن P/E به‌تنهایی دلیل خرید یا فروش نیست و در امتیاز مدل دخالت ندارد."
    )
    return Fundamental(eps, pe, sp, rel - 1, verdict, text)
