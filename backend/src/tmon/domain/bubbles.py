"""What kind a listed fund is, and the bubble of a right issue against its base stock (docs/06)."""

from __future__ import annotations

import re

# TSETMC subsector codes of fund instruments (instrument tags)
_SUBSECTOR_KIND = {
    "6810": "صندوق مختلط",
    "6811": "صندوق سهامی",
    "6812": "صندوق درآمد ثابت",
    "6815": "صندوق جسورانه",
    "6816": "صندوق خصوصی",
    "6817": "صندوق در صندوق",
    "6818": "صندوق املاک و مستغلات",
    "6819": "صندوق سهامی بخشی",
    "6821": "صندوق اهرمی",
    "6822": "صندوق طلا",
    "6823": "صندوق نقره",
    "6824": "صندوق کالایی",
}
_TYPE_KIND = {
    "etf_equity": "صندوق سهامی",
    "etf_fixed_income": "صندوق درآمد ثابت",
    "etf_mixed": "صندوق مختلط",
    "etf_leveraged": "صندوق اهرمی",
    "etf_commodity": "صندوق کالایی",
}
# fipiran ``fundType`` codes, named after the funds that carry them (2026-11-19); used only when
# the TSETMC instrument says nothing, as for funds that are not listed
_FIPIRAN_KIND = {
    4: "صندوق درآمد ثابت",
    5: "صندوق کالایی",
    6: "صندوق سهامی",
    7: "صندوق مختلط",
    12: "صندوق جسورانه",
    13: "صندوق پروژه",
    14: "صندوق زمین و ساختمان",
    16: "صندوق خصوصی",
    17: "صندوق در صندوق",
    18: "صندوق املاک و مستغلات",
    21: "صندوق سهامی بخشی",
    22: "صندوق اهرمی",
    23: "صندوق سهامی",
    24: "صندوق تضمین اصل سرمایه",
    25: "صندوق بازنشستگی",
}
INDEX_FUND_TYPE = 23
# a right buys one new share at the nominal price, in rials
RIGHT_NOMINAL = 1000.0


def fund_kind(
    subsector: str | None,
    fund_type: int | None,
    instrument_type: str | None,
    fund_desc: str | None,
) -> tuple[str, str | None]:
    """(kind, industry). The industry is only known for sector funds that state it."""
    kind = (
        _SUBSECTOR_KIND.get(subsector or "")
        or _TYPE_KIND.get(instrument_type or "")
        or _FIPIRAN_KIND.get(fund_type or 0)
        or "صندوق"
    )
    if kind == "صندوق سهامی" and fund_type == INDEX_FUND_TYPE:
        kind = "صندوق سهامی شاخصی"
    industry = None
    if subsector == "6819" and fund_desc:
        m = re.search(r"در\s*صنعت\s*(.+)", fund_desc)
        if m:
            industry = m.group(1).strip(" .،") or None
    return kind, industry


def right_base_symbol(symbol: str) -> str | None:
    """«فجهانح» and «بارانح2» → the base symbol; None when the symbol is not a right's."""
    m = re.fullmatch(r"(.+?)ح\d*", symbol.strip())
    return m.group(1) if m else None


def right_bubble(price: float, base_close: float) -> float | None:
    """(price − value) / value, where value = base close − nominal. None when the base is at or
    below the nominal price, since the value is then zero or negative."""
    value = base_close - RIGHT_NOMINAL
    if value <= 0:
        return None
    return (price - value) / value
