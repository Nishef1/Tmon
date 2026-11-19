"""The per-symbol verdict of ADR 0004 section 7, as pure functions over stored documents.

Nothing here reads a database, the object store or the network: ``final_verdict`` takes the ranking
document (and the turning-point document for the state veto) as plain dicts. The API routers, the
portfolio advice and the tests all import it from here, so there is one definition of the verdict.
The only outside input is the engine config, read as a fallback when a ranking document predates
its ``verdict`` block. Wording is plain Persian; thresholds are in ``config/engine.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tmon.backtest.turning import STATE_BY_KEY
from tmon.core.engine_config import get_engine_config


def fa_number(x: float, digits: int = 1, sign: bool = False) -> str:
    """A number with the Persian decimal separator."""
    return f"{x:{'+' if sign else ''}.{digits}f}".replace(".", ".")


def signed_pct(x: float) -> str:
    return f"{x * 100:+.2f}٪".replace(".", ".")


def state_meta(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """State names and meanings: the code's wording wins over the stored document's, so a
    renamed state reads the same everywhere before the nightly document is rewritten."""
    meta = {m["key"]: m for m in (doc or {}).get("states", [])}
    for k, st in STATE_BY_KEY.items():
        meta[k] = {**meta.get(k, {"key": k}), "title": st.title, "meaning": st.meaning}
    return meta


STATE_MIN_N = 2000  # symbol-days behind a state's statistic before it may overrule a score
STATE_EXEMPT = frozenset({"normal"})  # the baseline state: it has no evidence of its own


def state_veto(
    turn_doc: dict[str, Any] | None, instrument_id: int, h: int
) -> dict[str, Any] | None:
    """Why a high score must not become a "buy": the symbol's current state (a run-up that doubled
    in 60 days, ...) trailed the same-day market on average over the same ``h`` days in the past.

    The score's edge is an average over the whole top tenth; it says nothing about a symbol whose
    state history is flat or negative at that horizon. This can only lower a buy to a wait, never
    raise anything. Only horizons the state table has (20 and 60 days) can veto, only states with
    at least ``STATE_MIN_N`` symbol-days, and the baseline "normal" state never does. ``None``
    when nothing speaks against the buy."""
    if not turn_doc or h not in (20, 60):
        return None
    cur = (turn_doc.get("symbols") or {}).get(str(instrument_id)) or {}
    key = cur.get("state")
    if not key or key in STATE_EXEMPT:
        return None
    hist = turn_doc.get("history") or {}
    st = (hist.get("states") or {}).get(key) or {}
    stat = st.get(f"h{h}") or {}
    mean, n = stat.get("excess_mean"), stat.get("n")
    if mean is None or not n or n < STATE_MIN_N or mean > 0:
        return None
    base = (hist.get("base") or {}).get(f"h{h}") or {}
    return {
        "key": key,
        "title": state_meta(turn_doc).get(key, {}).get("title", key),
        "mean": float(mean),
        "n": int(n),
        "p_dn20": stat.get("p_dn20"),
        "base_dn20": base.get("p_dn20"),
    }


def _veto_sentence(v: dict[str, Any], label: str) -> str:
    def per100(x: float) -> str:
        return f"{round(x * 100)}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    tail = ""
    if v.get("p_dn20") is not None and v.get("base_dn20") is not None:
        tail = (
            f" و از هر ۱۰۰ سهم هم‌حالت {per100(v['p_dn20'])} تا بیش از ۲۰٪ ریزش کردند "
            f"(برای همهٔ سهم‌ها {per100(v['base_dn20'])})"
        )
    return (
        f"برای {label}: فعلاً نخرید؛ امتیاز بالاست، ولی این سهم در حالت «{v['title']}» است و "
        f"سهم‌های هم‌حالت در گذشته در همین مدت به‌طور میانگین از بازار جلو نزده‌اند "
        f"(میانگین سود اضافه {signed_pct(v['mean'])})" + tail + "؛ برتری گروه پرامتیاز دربارهٔ "
        "چنین سهمی ثابت نشده."
    )


GRADE_FA = {"proven": "ثابت‌شده", "probable": "احتمالی", "unproven": "ثابت‌نشده"}
# The codes of the ADR 0004 section 7 table, with the words each is shown as and a colour key.
CODE_FA = {
    "buy": "خرید",
    "candidate": "نامزد خرید",
    "candidate_queue": "نامزد، ولی در صف خرید",
    "wait": "صبر",
    "with_market": "همراه بازار",
    "avoid": "پرهیز",
    "wait_market": "صبر: بازار",
    "hold": "نگه‌دار",
    "consider_sell": "فروش را بسنجید",
}
CODE_KEY = {
    "buy": "buy",
    "candidate": "candidate",
    "candidate_queue": "candidate",
    "wait": "hold",
    "with_market": "hold",
    "avoid": "sell",
    "wait_market": "hold",
    "hold": "hold",
    "consider_sell": "sell",
}
BACKED_GRADES = ("probable", "proven")  # an avoid zone with this grade may say "avoid"


@dataclass(frozen=True)
class Verdict:
    """The answer for one symbol: ``code`` for someone who does not own it and ``holder_code`` for
    an owner, as in the ADR 0004 section 7 table."""

    code: str
    holder_code: str
    band: str  # candidate / middle / avoid: the place inside the liquid basket
    grade: str | None  # proven / probable / unproven for the zone of ``band``; None in the middle
    vetoed: bool  # a candidate lowered to a wait by the symbol's own state
    market_warning: bool  # exposure is zero: the market itself says stay out
    headline: str
    holder_headline: str

    @property
    def label(self) -> str:
        return CODE_FA[self.code]

    @property
    def holder_label(self) -> str:
        return CODE_FA[self.holder_code]

    @property
    def key(self) -> str:
        return CODE_KEY[self.code]

    @property
    def holder_key(self) -> str:
        return CODE_KEY[self.holder_code]

    def for_holder(self, held: bool) -> str:
        """The colour key of the answer the reader should see."""
        return self.holder_key if held else self.key


def verdict_config(doc: dict[str, Any]) -> dict[str, Any]:
    """The verdict's fixed numbers: from the ranking document, else straight from the config."""
    return doc.get("verdict") or get_engine_config().v2.verdict.model_dump()


def zone_of(doc: dict[str, Any], band: str, h: int) -> dict[str, Any] | None:
    zones = (doc.get("zones") or {}).get(str(h)) or {}
    return zones.get("candidate" if band == "candidate" else "avoid") or None


def _zone_sentence(z: dict[str, Any] | None, h: int, what: str, *, avoided: bool = False) -> str:
    """The zone's measured record net of the round trip: whole period, each half and t. For a zone
    to avoid, the number is the gain of avoiding it (its shortfall against the market, after cost).
    """
    if not z or z.get("net") is None:
        return ""
    t = z.get("t")
    spread = (
        f"(نیمهٔ اول {signed_pct(z['net_h1'])}، نیمهٔ دوم {signed_pct(z['net_h2'])}"
        + (f"، t = {fa_number(t)}" if t is not None else "")
        + ")."
    )
    if avoided:
        return (
            f"در گذشته پرهیز از {what} پس از کارمزد، {h} روز بعد به‌طور میانگین "
            f"{signed_pct(z['net'])} "
            f"نسبت به نگه‌داشتن بازار سود داشته {spread}"
        )
    return (
        f"در گذشته {what} پس از کارمزد، {h} روز بعد به‌طور میانگین {signed_pct(z['net'])} نسبت به "
        f"بازار داشته {spread}"
    )


def market_off(doc: dict[str, Any]) -> bool:
    exposure = (doc.get("exposure") or {}).get("exposure")
    return exposure is not None and exposure <= 1e-9


def final_verdict(
    doc: dict[str, Any],
    entry: dict[str, Any],
    turn_doc: dict[str, Any] | None = None,
    instrument_id: int | None = None,
) -> Verdict | None:
    """The per-symbol verdict of ADR 0004 section 7 for one ranking entry (a row or a universe
    item of the ranking document); ``None`` when it has no band (no score, or a sell queue).

    The band is the symbol's place in the liquid basket (candidate / middle / avoid), the grade
    of that zone comes from the verdict config (the Phase 2 report), exposure from the document.
    A candidate in a buy queue is never called buyable; the state veto, read at the verdict
    horizon, only lowers a candidate to a wait; with exposure zero nobody is told to buy. Only a
    grade "proven" turns a candidate into "buy". A plain "sell" is not made here: it comes from the
    portfolio switch rule and exit alerts. One definition for every list."""
    band = entry.get("band")
    if band not in ("candidate", "middle", "avoid"):
        return None
    vc = verdict_config(doc)
    h = int(vc["horizon_days"])
    off = market_off(doc)
    queue = entry.get("queue_state") == "buy_queue"
    veto = None if instrument_id is None else state_veto(turn_doc, instrument_id, h)
    wait_market = "امروز بازار می‌گوید سهام نخرید (سهم سرمایه در سهام صفر است)؛ صبر کنید."
    grade: str | None = None
    vetoed = False
    if band == "candidate":
        grade = str(vc["candidate_grade"])
        rec = _zone_sentence(zone_of(doc, band, h), h, "نیمهٔ بالای سهم‌های پرمعامله")
        code, holder = "candidate", "hold"
        if off:
            code = "wait_market"
        elif queue:
            code = "candidate_queue"
        elif veto is not None:
            code, vetoed = "wait", True
        elif grade == "proven":
            code = "buy"
        head = {
            "buy": "بخرید؛ " + rec,
            "candidate": (
                f"نامزد خرید است، نه توصیه؛ شواهد این ناحیه {GRADE_FA[grade]} است. " + rec
            ),
            "candidate_queue": (
                "نامزد خرید است ولی در صف خرید است و سفارش امروز احتمالاً پر نمی‌شود؛ به سقف "
                "صف نخرید. " + rec
            ),
            "wait": _veto_sentence(veto, "این سهم") if veto else "",
            "wait_market": wait_market,
        }[code]
        held_head = "اگر دارید، نگه دارید و هشدارهای پرتفوی را دنبال کنید. " + rec
    elif band == "avoid":
        grade = str(vc["avoid_grade"])
        rec = _zone_sentence(zone_of(doc, band, h), h, "ناحیهٔ پایین (کم‌امتیازها)", avoided=True)
        backed = grade in BACKED_GRADES
        code = "avoid" if backed else "with_market"
        holder = "consider_sell" if backed else "hold"
        if off and not backed:
            code = "wait_market"
        head = {
            "avoid": "نخرید؛ " + rec,
            "with_market": (
                "امتیازش در ناحیهٔ پایین است، ولی عقب‌ماندگی این ناحیه هنوز ثابت نشده "
                f"(شواهد {GRADE_FA[grade]})؛ نه دلیلی برای پرهیز است نه برای خرید. همراه بازار "
                "بمانید. " + rec
            ),
            "wait_market": wait_market,
        }[code]
        held_head = (
            "فروش را بسنجید؛ " + rec
            if backed
            else "اگر دارید نگه دارید؛ عقب‌ماندگی ناحیهٔ پایین هنوز ثابت نشده، پس فروش لازم "
            "نیست. " + rec
        )
    else:
        code, holder = ("wait_market" if off else "with_market"), "hold"
        head = (
            wait_market
            if off
            else "امتیازش میانه است: نه نامزد خرید است نه پرهیز؛ همراه بازار بمانید."
        )
        held_head = "اگر دارید، نگه دارید."
    if off:
        held_head += " هشدار بازار: سهم سرمایه در سهام امروز صفر است؛ بازار در کل خوب نیست."
    return Verdict(code, holder, band, grade, vetoed, off, head.strip(), held_head.strip())


def verdict_fields(v: Verdict | None) -> dict[str, Any]:
    """The ``VerdictFields`` of a list row (screener, ranking, search, peers) from its verdict."""
    if v is None:
        return {}
    return {
        "code": v.code,
        "holder_code": v.holder_code,
        "holder_verdict": v.holder_key,
        "holder_label": v.holder_label,
        "band": v.band,
        "grade": v.grade,
        "grade_label": None if v.grade is None else GRADE_FA[v.grade],
    }
