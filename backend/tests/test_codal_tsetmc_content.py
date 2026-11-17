"""The TSETMC copy of a Codal decisions letter: dividend and earnings per share from its table."""

import json

from tmon.ingest.codal.tsetmc_content import decisions_of, parse_profit_table

TABLE = (
    '<Root><tr><td>سود (زیان) خالص هر سهم- ریال</td><td id="a">۱,۴۳۴</td></tr>'
    '<tr><td>سود نقدی هر سهم (ریال)</td><td id="b">450</td></tr></Root>'
)


def test_profit_table_reads_dps_and_eps() -> None:
    assert parse_profit_table(TABLE) == {"dps": 450.0, "eps": 1434.0}


def test_missing_rows_are_none() -> None:
    assert parse_profit_table("<Root></Root>") == {"dps": None, "eps": None}


def test_only_ordinary_assemblies_are_kept() -> None:
    payload = json.dumps(
        {
            "statemetnContent": [
                {
                    "title": "تصمیمات مجمع عمومی عادی سالیانه دوره 12 ماهه منتهی به 1404/12/29",
                    "publishDateTime_DEven": 20260729,
                    "content": TABLE,
                },
                {
                    "title": "تصمیمات مجمع عمومی فوق العاده دوره 12 ماهه منتهی به 1404/12/29",
                    "publishDateTime_DEven": 20260729,
                    "content": TABLE,
                },
            ]
        }
    )
    rows = decisions_of(payload)
    assert len(rows) == 1
    assert rows[0]["day"] == 20260729 and rows[0]["dps"] == 450.0
