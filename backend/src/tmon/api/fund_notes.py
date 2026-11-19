"""What was measured about funds, as plain sentences for the fund page.

A tradable fund gets the same sections as a stock (score, verdict, trend ride, ranges, checklist).
Each section carries the result of testing that part on funds, so a part that failed is shown with
its result instead of being hidden. The numbers are from docs/reports/fund-verdict-2026-11.md
(code: backend/research/market_method/fund_full_analysis.py); change them only with that report.
"""

from __future__ import annotations

from dataclasses import dataclass

# instrument_type -> the group the study measured
GROUP = {
    "etf_equity": "equity_mixed",
    "etf_mixed": "equity_mixed",
    "etf_leveraged": "leveraged",
    "etf_commodity": "commodity",
    "etf_fixed_income": "fixed_income",
}
GROUP_FA = {
    "equity_mixed": "سهامی و مختلط",
    "leveraged": "اهرمی",
    "commodity": "کالایی",
    "fixed_income": "درآمد ثابت",
}
VERDICT_LINE = "روی صندوق‌ها آزموده شد و از نگه‌داشتنِ ساده بهتر نبود؛ رتبه‌بندی مدل، توصیه نیست."


@dataclass(frozen=True)
class ScoreStudy:
    funds: int  # funds scored inside the stock ranking
    candidate_share: float  # share of fund-days the stock rule calls a candidate
    cand_minus_all_net: float  # candidates minus all funds, 20 days, after the round trip
    ic: float  # rank correlation of the score with the next 20 days


@dataclass(frozen=True)
class RideStudy:
    funds: int
    strategy: float  # median total return of the rule over each fund's own span
    hold: float  # median total return of holding
    ahead: int  # funds where the rule ended ahead of holding
    dd_strategy: float  # median worst fall
    dd_hold: float


SCORE = {
    "equity_mixed": ScoreStudy(97, 0.83, -0.0034, 0.04),
    "leveraged": ScoreStudy(9, 0.30, -0.0057, -0.09),
    "commodity": ScoreStudy(25, 0.77, -0.0032, 0.04),
    "fixed_income": ScoreStudy(82, 0.99, -0.0029, 0.28),
}
RIDE = {
    "equity_mixed": RideStudy(111, 1.77, 2.23, 7, -0.25, -0.25),
    "leveraged": RideStudy(8, 0.86, 5.42, 0, -0.46, -0.52),
    "commodity": RideStudy(23, 1.97, 3.69, 0, -0.32, -0.32),
    "fixed_income": RideStudy(92, 0.0, 0.98, 3, 0.0, 0.0),
}
SMALL = 12  # fewer funds than this: say the sample is small


def _fa(x: float, digits: int = 0) -> str:
    return f"{x:.{digits}f}".translate(str.maketrans("0123456789.-", "۰۱۲۳۴۵۶۷۸۹.−"))


def _pct(x: float, digits: int = 0) -> str:
    return f"{_fa(x * 100, digits)}٪"


@dataclass(frozen=True)
class FundNotes:
    group: str
    group_fa: str
    verdict_line: str
    score: str
    ride: str
    ranges: str
    checks: str


def fund_notes(instrument_type: str) -> FundNotes | None:
    g = GROUP.get(instrument_type)
    if g is None:
        return None
    s, r = SCORE[g], RIDE[g]
    small = " نمونه کوچک است؛ نتیجه سست است." if min(s.funds, r.funds) < SMALL else ""
    score = (
        f"امتیاز با همان چهار سیگنال و در همان فهرست سهم‌ها حساب شده. روی {_fa(s.funds)} صندوق "
        f"{GROUP_FA[g]} آزموده شد (۲۰ روز بعد، پس از هزینه): {_pct(s.candidate_share)} روزِ "
        f"صندوق‌ها «نامزد» شدند، نامزدها {_pct(abs(s.cand_minus_all_net), 2)} "
        f"{'کمتر' if s.cand_minus_all_net < 0 else 'بیشتر'} از میانگین صندوق‌ها بازده دادند و "
        f"همبستگی رتبه‌ای امتیاز با بازده بعدی {_fa(s.ic, 2)} بود." + small
    )
    if g == "fixed_income":
        score += (
            " در درآمد ثابت امتیاز صندوق‌ها را مرتب می‌کند، ولی فاصلهٔ بازدهشان آن‌قدر کم است که "
            "پس از هزینه چیزی نمی‌ماند."
        )
    ride = (
        f"قاعدهٔ ورود و خروج روند را روی هر یک از {_fa(r.funds)} صندوق {GROUP_FA[g]} جدا آزمودیم "
        f"(با هزینه، تا آخرین روز): میانهٔ سود قاعده {_pct(r.strategy)} در برابر "
        f"{_pct(r.hold)} برای فقط نگه‌داشتن؛ قاعده {_fa(r.ahead)} صندوق از {_fa(r.funds)} را "
        "جلو زد. بیشترین افت "
        f"{_pct(r.dd_strategy)} در برابر {_pct(r.dd_hold)}." + small
    )
    return FundNotes(
        group=g,
        group_fa=GROUP_FA[g],
        verdict_line=VERDICT_LINE,
        score=score,
        ride=ride,
        ranges=(
            "بازه‌ها از خودِ تاریخچهٔ همین صندوق ساخته می‌شوند و فقط دامنهٔ گذشته را نشان می‌دهند؛ "
            "آزموده نشده که برای صندوق‌ها بهتر از حدس ساده باشند."
        ),
        checks=(
            "چک‌لیست همان سیگنال‌های سهم را نشان می‌دهد؛ هیچ‌کدام برای صندوق‌ها جدا آزموده نشده‌اند "
            "(آزموده نشده)، فقط مجموعشان که در بالا آمده."
        ),
    )
