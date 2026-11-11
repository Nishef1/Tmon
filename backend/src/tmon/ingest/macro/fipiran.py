"""fipiran.ir fund data (docs/06).

The fund pages of www.fipiran.ir are a React app whose API base is ``/services``. ``POST
/services/fund/fundcompare`` with ``{}`` returns ``{"status", "totalCount", "items": [...]}``
with one item per fund (498 on 2026-11-12), each carrying ``regNo``, ``name``, ``fundType``,
``typeOfInvest`` (``Negotiable`` = listed ETF, ``IssuanceAndCancellation`` = unlisted),
``cancelNav``, ``issueNav``, ``statisticalNav``, ``netAsset``, ``date`` (ISO, the NAV day) and,
for listed units, ``insCode`` (the TSETMC instrument code). Sample (real items):
``tests/fixtures/macro/fipiran_fundcompare.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from tmon.ingest.tsetmc.parsers import ParseError

COMPARE_URL = "https://www.fipiran.ir/services/fund/fundcompare"
SOURCE = "fipiran"


@dataclass(frozen=True)
class FundRow:
    reg_no: str
    date: date
    name: str | None
    ins_code: str | None
    fund_type: int | None
    type_of_invest: str | None
    cancel_nav: float | None
    issue_nav: float | None
    statistical_nav: float | None
    net_asset: float | None


def _f(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and v > 0 else None


def parse_compare(payload: bytes) -> list[FundRow]:
    try:
        items = json.loads(payload)["items"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError(f"fipiran: not a fundcompare payload: {payload[:120]!r}") from exc
    out = []
    for it in items:
        if not it.get("regNo") or not it.get("date"):
            continue
        out.append(
            FundRow(
                reg_no=str(it["regNo"]),
                date=datetime.fromisoformat(it["date"]).date(),
                name=it.get("name"),
                ins_code=str(it["insCode"]) if it.get("insCode") else None,
                fund_type=it.get("fundType"),
                type_of_invest=it.get("typeOfInvest"),
                cancel_nav=_f(it.get("cancelNav")),
                issue_nav=_f(it.get("issueNav")),
                statistical_nav=_f(it.get("statisticalNav")),
                net_asset=_f(it.get("netAsset")),
            )
        )
    return out


def bubble(market_price: float | None, cancel_nav: float | None) -> float | None:
    """docs/06: ``(P_market − NAV_redemption) / NAV_redemption``."""
    if not market_price or not cancel_nav:
        return None
    return (market_price - cancel_nav) / cancel_nav
