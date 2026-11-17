"""TSETMC financial-statement parser: merges the two pages, skips subsidiaries, normalises."""

from __future__ import annotations

import json
from datetime import date

from tmon.ingest.tsetmc.statements import (
    normalize_label,
    parse_jalali,
    parse_number,
    parse_statements,
    parse_table,
)

INCOME = (
    "<Root><YearEndToDate>1404/12/29</YearEndToDate><Period>6</Period>"
    "<IsAudited>حسابرسی نشده</IsAudited><PeriodEndToDate>1405/06/31</PeriodEndToDate>"
    "<table><tr><td>شرح</td><td>دوره 1405/06/31</td><td>دوره 1404/06/31</td>"
    "<td>دوره 1404/12/29</td><td>درصد تغییر</td></tr>"
    "<tr><td>درآمدهای عملیاتی</td><td>2509422184</td><td>1608734238</td>"
    "<td>3668860246</td><td>56</td></tr>"
    "<tr><td>هزینه\u200f هاى مالى</td><td>-113379943</td><td>-96633010</td>"
    "<td>-219159168</td><td>-17</td></tr></table></Root>"
)
# income pages carry an empty first value column; balance rows carry an extra zero column
INCOME_EMPTY_COL = INCOME.replace(
    "<td>دوره 1405/06/31</td>", "<td /><td>دوره 1405/06/31</td>"
).replace("<td>2509422184</td>", "<td /><td>2509422184</td>")
BALANCE = (
    "<Root><YearEndToDate>1404/12/29</YearEndToDate><Period>6</Period>"
    "<IsAudited>حسابرسی نشده</IsAudited><PeriodEndToDate>1405/06/31</PeriodEndToDate>"
    "<table><tr><td>شرح</td><td>به تاريخ 1405/06/31</td><td>به تاريخ 1404/12/29</td>"
    "<td>درصد تغییر</td></tr>"
    "<tr><td>جمع دارایی\u200cها</td><td>5689017096</td><td>4452432038</td><td>0</td>"
    "<td>28</td></tr>"
    "<tr><td></td><td>3448483844</td><td>2691911237</td><td>0</td><td>28</td></tr>"
    "</table></Root>"
)


def payload(title: str, content: str, published: str = "2026-10-22T14:37:13") -> str:
    item = {"title": title, "publishDateTime_Gregorian": published, "content": content}
    return json.dumps({"statemetnContent": [item]}, ensure_ascii=False)


def test_label_normalisation_unifies_letters_and_half_spaces() -> None:
    assert normalize_label("هزینه\u200f هاى مالى") == "هزینه های مالی"
    assert normalize_label("سود(زیان) عملیاتي") == "سود(زیان) عملیاتی"


def test_numbers_and_jalali_dates() -> None:
    assert parse_number("۱٬۲۳۴") == 1234.0
    assert parse_number("(25)") == -25.0
    assert parse_number("") is None
    assert parse_jalali("1405/06/31") == date(2026, 9, 22)
    # a 30th of Esfand in a non-leap year falls back to the 29th instead of failing
    assert parse_jalali("1404/12/30") == parse_jalali("1404/12/29")


def test_income_table_drops_percent_and_empty_columns() -> None:
    rows = parse_table(INCOME_EMPTY_COL)
    assert rows[0] == ["درآمدهای عملیاتی", 2509422184.0, 1608734238.0, 3668860246.0]
    assert rows[1][0] == "هزینه های مالی"


def test_balance_table_skips_unlabelled_subtotal_rows() -> None:
    rows = parse_table(BALANCE)
    assert rows == [["جمع دارایی ها", 5689017096.0, 4452432038.0]]


def test_pages_merge_into_one_statement_with_header_facts() -> None:
    title = "اطلاعات و صورت\u200cهای مالی میاندوره\u200cای دوره 6 ماهه منتهی به 1405/06/31 (حسابرسی نشده)"
    a = parse_statements(payload(title, BALANCE), 0)
    b = parse_statements(payload(title, INCOME), 1)
    assert list(a) == list(b)
    (key,) = a
    st = a[key]
    st.income = b[key].income
    assert st.kind == "separate"
    assert st.period_months == 6
    assert st.audited is False
    assert st.period_end == date(2026, 9, 22)
    assert st.balance[0][1] == 5689017096.0
    assert st.income[0][1] == 2509422184.0
    assert st.published_at.utcoffset() is not None


def test_consolidated_flag_and_subsidiary_filings_are_skipped() -> None:
    cons = parse_statements(
        payload("صورت\u200cهای مالی تلفیقی سال مالی منتهی به 1404/12/29", INCOME), 1
    )
    assert [k[1] for k in cons] == ["consolidated"]
    sub = parse_statements(
        payload("صورت\u200cهای مالی سال مالی منتهی به 1404/12/29 (شرکت دانا فولاد سمنان)", INCOME),
        1,
    )
    assert sub == {}


def test_interim_income_rows_with_leading_empty_cell_but_no_header_placeholder() -> None:
    content = (
        "<Root><table><tr><td>شرح</td><td>دوره 1405/06/31</td><td>دوره 1404/06/31</td>"
        "<td>دوره 1404/12/29</td><td>درصد تغییر</td></tr>"
        "<tr><td>درآمدهای عملیاتی</td><td /><td>2509422184</td><td>1608734238</td>"
        "<td>3668860246</td><td>56</td></tr></table></Root>"
    )
    assert parse_table(content) == [["درآمدهای عملیاتی", 2509422184.0, 1608734238.0, 3668860246.0]]
