"""Corporate events from the Codal letter index (docs/05).

The letter-code meanings below were read off real index rows (800 market-wide letters and the
full history of فملی, captured 2026-11-11), not assumed. A code not listed here is not an event
we track. Letters without a code (fund announcements) are ignored.

The index gives the event's kind, stage and publication time. Amounts (DPS, increase percent and
source) live in the letter body and are not parsed here.
"""

from __future__ import annotations

from dataclasses import dataclass

AGM = "agm_dividend"
CAPITAL_INCREASE = "egm_capital_increase"
RIGHTS = "rights_offering"
OTHER = "other"

_EXTRAORDINARY_ORDINARY = ("بطور فوق العاده", "به طور فوق العاده")


@dataclass(frozen=True)
class EventKind:
    type: str
    stage: str


# code -> (type, stage); titles seen for each code are in the comment.
_BY_CODE: dict[str, EventKind] = {
    # "آگهی دعوت به مجمع عمومی عادی سالیانه"
    "ن-۵۰": EventKind(AGM, "invitation"),
    # "تصمیمات مجمع عمومی عادی سالیانه"
    "ن-۵۲": EventKind(AGM, "decisions"),
    # "زمانبندی پرداخت سود"
    "ن-۱۳": EventKind(AGM, "dividend_schedule"),
    # "زمانبندی پرداخت سود سنوات گذشته"
    "ن-۸۵": EventKind(AGM, "dividend_schedule_prior_years"),
    # "آگهی دعوت به مجمع عمومی عادی بطور فوق العاده"
    "ن-۵۴": EventKind(OTHER, "ordinary_extraordinary_invitation"),
    # "تصمیمات مجمع عمومی عادی به طور فوق العاده"
    "ن-۵۵": EventKind(OTHER, "ordinary_extraordinary_decisions"),
    # "آگهی دعوت به مجمع عمومی فوق العاده" (the title does not say whether capital changes)
    "ن-۵۶": EventKind(OTHER, "egm_invitation"),
    # "تصمیمات مجمع عمومی فوق العاده"
    "ن-۵۷": EventKind(OTHER, "egm_decisions"),
    # "لغو  آگهی (اطلاعیه) دعوت به مجمع عمومی"
    "ن-۵۸": EventKind(OTHER, "meeting_cancelled"),
    # "پیشنهاد هیئت مدیره به مجمع عمومی فوق العاده در خصوص افزایش سرمایه"
    "ن-۶۰": EventKind(CAPITAL_INCREASE, "board_proposal"),
    # "اظهارنظر حسابرس و بازرس قانونی نسبت به گزارش توجیهی هیئت مدیره در خصوص ..."
    "ن-۶۱": EventKind(CAPITAL_INCREASE, "auditor_opinion"),
    # "مدارک و مستندات درخواست افزایش سرمایه"
    "ن-۶۲": EventKind(CAPITAL_INCREASE, "documents"),
    # "آگهی ثبت افزایش سرمایه"
    "ن-۶۷": EventKind(CAPITAL_INCREASE, "registered"),
    # "تصمیم هیئت مدیره به انجام افزایش سرمایه تفویض شده در مجمع فوق العاده"
    "ن-۷۰": EventKind(CAPITAL_INCREASE, "board_decision_delegated"),
    # "زمان تشکیل جلسه هیئت مدیره درخصوص افزایش سرمایه"
    "ن-۷۱": EventKind(CAPITAL_INCREASE, "board_meeting_scheduled"),
    # "تصمیمات هیئت مدیره درخصوص افزایش سرمایه"
    "ن-۷۳": EventKind(CAPITAL_INCREASE, "board_decision"),
    # "تمدید مهلت استفاده از حق تقدم خرید سهام"
    "ن-۶۴": EventKind(RIGHTS, "rights_deadline_extended"),
    # "تمدید اعلامیه پذیره نویسی عمومی"
    "ن-۶۵": EventKind(RIGHTS, "public_subscription_extended"),
}

EVENT_LETTER_CODES: tuple[str, ...] = (*_BY_CODE, "ن-۵۱", "ن-۴۲")


def classify_letter(letter_code: str, title: str) -> EventKind | None:
    """Event kind of a Codal letter, or None when it is not a corporate event we track."""
    code = letter_code.strip()
    extraordinary = any(m in title for m in _EXTRAORDINARY_ORDINARY)
    if code == "ن-۵۱":
        # "خلاصه تصمیمات مجمع عمومی عادی سالیانه" / "... عادی به طور فوق العاده"
        if extraordinary:
            return EventKind(OTHER, "ordinary_extraordinary_decisions_summary")
        return EventKind(AGM, "decisions_summary")
    if code == "ن-۴۲":
        # "آگهی ثبت تصمیمات مجمع عادی سالیانه" / "... عمومی عادی بطور فوق العاده" /
        # "... مجمع عمومی فوق العاده (بجز تغییرات سرمایه)"
        if "سالیانه" in title and not extraordinary:
            return EventKind(AGM, "decisions_registered")
        return EventKind(OTHER, "decisions_registered")
    if code == "ن-۵۷" and "افزایش سرمایه" in title:
        return EventKind(CAPITAL_INCREASE, "egm_decisions")
    return _BY_CODE.get(code)
