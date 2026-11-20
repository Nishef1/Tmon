"""Parsers of the fund-website collector (tmon.ingest.macro.fund_sites), on small fixtures."""

from __future__ import annotations

import io
import zipfile
from datetime import date

from tmon.core.timeutil import from_jalali
from tmon.ingest.macro.fund_sites import (
    ZWNJ,
    jdate,
    num,
    parse_rayan,
    parse_tadbir_asset,
    parse_tadbir_nav,
    read_xlsx,
)

D = from_jalali(1405, 8, 26)


def _xlsx(rows: list[list[str]]) -> bytes:
    """A minimal workbook: shared strings for every cell, one sheet, B-column gaps allowed."""
    shared: list[str] = []
    body = []
    for i, row in enumerate(rows, start=1):
        cells = []
        for j, v in enumerate(row):
            if v == "":
                continue  # missing cell: read_xlsx must place the next one by its ref
            shared.append(v)
            cells.append(f'<c r="{chr(65 + j)}{i}" t="s"><v>{len(shared) - 1}</v></c>')
        body.append(f'<row r="{i}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sst = "".join(f"<si><t>{s}</t></si>" for s in shared)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sst}</sst>")
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {ns}><sheetData>{''.join(body)}</sheetData></worksheet>",
        )
    return buf.getvalue()


def test_num_and_jdate_read_persian_text() -> None:
    assert num("۱۵,۷۵۷") == 15757
    assert num("%26.33") == 26.33
    assert num("-") is None and num(None) is None and num("abc") is None
    assert jdate("۱۴۰۵/۰۸/۲۶") == D
    assert jdate("1405/13/01") is None and jdate("") is None


def test_read_xlsx_places_cells_by_column_ref() -> None:
    rows = read_xlsx(_xlsx([["a", "", "c"], ["x", "y", "z"]]))
    assert rows == [["a", None, "c"], ["x", "y", "z"]]


def test_tadbir_nav_leveraged_takes_the_premium_unit() -> None:
    head = [
        "تاریخ",
        "قیمت صدور واحد های ممتاز",
        f"قیمت ابطال واحد{ZWNJ} های ممتاز",  # a ZWNJ in the site's label must not matter
        "قیمت اسمی واحد های ممتاز",
        "قیمت واحد های عادی",
        "نسبت اهرمی",
    ]
    rows = read_xlsx(
        _xlsx([["گزارش"], head, ["1405/08/26", "77,247", "76,123", "76,123", "26,858.61", "0.45"]])
    )
    got = parse_tadbir_nav(rows)[D]
    assert got["cancel_nav"] == 76123 and got["issue_nav"] == 77247
    assert got["base_nav"] == 26858.61 and got["leverage"] == 0.45


def test_tadbir_nav_plain_fund() -> None:
    head = ["تاریخ", "قیمت صدور", "قیمت ابطال", "قیمت آماری", "کل خالص ارزش دارایی‌ها"]
    got = parse_tadbir_nav([head, ["1405/08/26", "1,010", "1,000", "1,005", "5,000,000"]])[D]
    assert got == {
        "issue_nav": 1010,
        "cancel_nav": 1000,
        "statistical_nav": 1005,
        "units": None,
        "units_issued": None,
        "units_revoked": None,
        "net_asset": 5_000_000,
    }


def test_tadbir_asset_sums_top5_with_other_stock_and_cash_with_deposits() -> None:
    head = [
        "تاریخ",
        "پنج سهم برتر به کل دارایی",
        "سایر سهام به کل دارایی",
        "وجه نقد به کل دارایی",
        "اوراق سپرده به کل دارایی",
        "اوراق مشارکت به کل دارایی",
    ]
    got = parse_tadbir_asset([head, ["1405/08/26", "30", "45.5", "2", "3", "%10"]])[D]
    assert got["top5_pct"] == 30 and got["stock_pct"] == 75.5
    assert got["cash_pct"] == 5 and got["bond_pct"] == 10
    assert got["commodity_pct"] is None


def test_rayan_merges_nav_and_asset_by_day() -> None:
    nav = [
        {
            "jalaliDate": "1405/08/26",
            "sellNAVPerShare": 1000,
            "purchaseNAVPerShare": 1010,
            "nav": 9e9,
        }
    ]
    asset = [
        {
            "date": "1405/08/26",
            "stockTodayPercent": 80,
            "depositTodayPercent": 4,
            "cashTodayPercent": 1,
        },
        {"date": "bad", "stockTodayPercent": 1},
    ]
    out = parse_rayan(nav, asset)
    assert list(out) == [D]
    assert out[D]["cancel_nav"] == 1000 and out[D]["net_asset"] == 9e9
    assert out[D]["stock_pct"] == 80 and out[D]["cash_pct"] == 5
    assert isinstance(next(iter(out)), date)
