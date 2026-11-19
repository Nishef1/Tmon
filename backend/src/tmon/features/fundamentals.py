"""Growth, margins, returns on capital and valuation multiples from the filed statements.

Only symbols whose filings are stored have these (about eighty); every other symbol gets nothing
here, never a guess. Statements are in million rial, so a market cap in rial is divided by a
million before it meets them. Income rows are cumulative inside a fiscal year (3, 6, 9, 12 months),
so a quarter is the difference of two filings and a trailing twelve months is the current filing
plus the last full year minus the same period a year earlier.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.storage.models import FinancialStatement

Value = float | str | None

_STRIP = re.compile(r"[\s()‌]")
FY_TOLERANCE_DAYS = (
    20  # two filings are of the same fiscal year when their year ends are this close
)


def key(label: object) -> str:
    """Row labels differ in spaces and brackets between filings; compare them stripped."""
    return _STRIP.sub("", str(label))


REVENUE = key("درآمدهای عملیاتی")
GROSS = key("سود(زیان) ناخالص")
OPERATING = key("سود(زیان) عملیاتی")
NET = key("سود(زیان) خالص")
ASSETS = key("جمع دارایی ها")
LIABILITIES = key("جمع بدهی ها")
EQUITY = key("جمع حقوق مالکانه")
CUR_ASSETS = key("جمع دارایی های جاری")
CUR_LIABILITIES = key("جمع بدهی های جاری")
DEBT = key("تسهیلات مالی")
DEBT_LONG = key("تسهیلات مالی بلندمدت")


@dataclass(frozen=True)
class Stmt:
    published_at: dt.datetime
    kind: str
    period_end: dt.date | None
    fiscal_year_end: dt.date | None
    months: int | None
    balance: dict[str, list[float | None]]
    income: dict[str, list[float | None]]


def _table(rows: list[list[object]]) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {}
    for r in rows:
        if not r:
            continue
        k = key(r[0])
        # the first row of a label wins: later rows with the same label are sub-tables
        out.setdefault(k, [None if v is None else float(v) for v in r[1:]])  # type: ignore[arg-type]
    return out


def load_statements(session: Session) -> dict[int, list[Stmt]]:
    out: dict[int, list[Stmt]] = {}
    for s in session.scalars(select(FinancialStatement)):
        out.setdefault(s.instrument_id, []).append(
            Stmt(
                s.published_at,
                s.kind,
                s.period_end,
                s.fiscal_year_end,
                s.period_months,
                _table(s.balance or []),
                _table(s.income or []),
            )
        )
    return out


def _cell(table: dict[str, list[float | None]], k: str, col: int = 0) -> float | None:
    row = table.get(k)
    return row[col] if row is not None and len(row) > col else None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _growth(cur: float | None, prior: float | None) -> float | None:
    """Change against a positive base; a loss or zero base has no meaningful growth."""
    if cur is None or prior is None or prior <= 0:
        return None
    return cur / prior - 1.0


def _same_year(a: dt.date | None, b: dt.date | None, years_back: int = 0) -> bool:
    if a is None or b is None:
        return False
    shifted = b - dt.timedelta(days=round(365.25 * years_back))
    return abs((a - shifted).days) <= FY_TOLERANCE_DAYS


def _find(
    stmts: list[Stmt], kind: str, fy_end: dt.date | None, months: int, years_back: int = 0
) -> Stmt | None:
    for s in stmts:
        if (
            s.kind == kind
            and s.months == months
            and _same_year(s.fiscal_year_end, fy_end, years_back)
        ):
            return s
    return None


def _cum(
    stmts: list[Stmt], kind: str, fy_end: dt.date | None, months: int, k: str, back: int
) -> float | None:
    """Cumulative value of ``k`` for ``months`` of the fiscal year ``back`` years before."""
    if months == 0:
        return 0.0
    s = _find(stmts, kind, fy_end, months, back)
    return _cell(s.income, k) if s else None


def _quarter(
    stmts: list[Stmt], kind: str, fy_end: dt.date | None, months: int, k: str, back: int = 0
) -> float | None:
    """The 3-month figure that ends at ``months`` of the fiscal year ``back`` years before."""
    if months <= 0:  # the quarter before the first one is the last of the year before
        return _quarter(stmts, kind, fy_end, 12 + months, k, back + 1)
    hi = _cum(stmts, kind, fy_end, months, k, back)
    lo = _cum(stmts, kind, fy_end, months - 3, k, back)
    return None if hi is None or lo is None else hi - lo


def _ttm(stmts: list[Stmt], latest: Stmt, k: str) -> float | None:
    cur = _cell(latest.income, k)
    if cur is None or latest.months is None:
        return None
    if latest.months == 12:
        return cur
    prior_same = _cell(latest.income, k, 1)
    last_year = _find(stmts, latest.kind, latest.fiscal_year_end, 12, 1)
    full = _cell(last_year.income, k) if last_year else None
    if prior_same is None or full is None:
        return None
    return cur + full - prior_same


def latest_statement(stmts: list[Stmt]) -> Stmt | None:
    """The newest period, taking consolidated figures when the company files them."""
    if not stmts:
        return None
    kind = "consolidated" if any(s.kind == "consolidated" for s in stmts) else "separate"
    pool = [s for s in stmts if s.kind == kind and s.period_end is not None]
    if not pool:
        return None
    return max(pool, key=lambda s: (s.period_end or dt.date.min, s.published_at))


def ratios(stmts: list[Stmt], mcap: float | None) -> dict[str, Value]:
    """Every fundamental column of one symbol; empty when it has no usable statement."""
    latest = latest_statement(stmts)
    if latest is None:
        return {}
    same = [s for s in stmts if s.kind == latest.kind]
    inc, bal = latest.income, latest.balance
    rev, net = _cell(inc, REVENUE), _cell(inc, NET)
    assets, liab, equity = _cell(bal, ASSETS), _cell(bal, LIABILITIES), _cell(bal, EQUITY)
    debt = (_cell(bal, DEBT) or 0.0) + (_cell(bal, DEBT_LONG) or 0.0)
    net_ttm, rev_ttm = _ttm(same, latest, NET), _ttm(same, latest, REVENUE)
    m = latest.months or 0
    qoq: dict[str, float | None] = {}
    for name, k in (("rev_qoq", REVENUE), ("net_qoq", NET)):
        now = _quarter(same, latest.kind, latest.fiscal_year_end, m, k)
        before = _quarter(same, latest.kind, latest.fiscal_year_end, m - 3, k)
        qoq[name] = _growth(now, before)
    mcap_m = None if mcap is None else mcap / 1e6
    out: dict[str, Value] = {
        "statement_kind": latest.kind,
        "statement_period_end": latest.period_end.isoformat() if latest.period_end else None,
        "statement_months": float(m) if m else None,
        "fiscal_year_end": latest.fiscal_year_end.isoformat() if latest.fiscal_year_end else None,
        "rev_yoy": _growth(rev, _cell(inc, REVENUE, 1)),
        "net_yoy": _growth(net, _cell(inc, NET, 1)),
        **qoq,
        "gross_margin": _ratio(_cell(inc, GROSS), rev),
        "op_margin": _ratio(_cell(inc, OPERATING), rev),
        "net_margin": _ratio(net, rev),
        "roe": _ratio(net_ttm, equity),
        "roa": _ratio(net_ttm, assets),
        "debt_to_assets": _ratio(liab, assets),
        "fin_debt_to_equity": _ratio(debt, equity),
        "current_ratio": _ratio(_cell(bal, CUR_ASSETS), _cell(bal, CUR_LIABILITIES)),
        "pe_ttm": _ratio(mcap_m, net_ttm),
        "ps_ttm": _ratio(mcap_m, rev_ttm),
        "pb": _ratio(mcap_m, equity),
    }
    out["fund_score"] = fund_score(out)
    return out


def fund_score(r: dict[str, Value]) -> float | None:
    """Share of six plain yes/no conditions that hold, 0 to 100. A count, not a forecast: each
    condition is a sign test with no tuned threshold, and the score is untested as a predictor."""
    checks: list[bool | None] = []
    for k in ("rev_yoy", "net_yoy", "net_margin", "roe"):
        v = r.get(k)
        checks.append(None if not isinstance(v, float) else v > 0)
    cr, da = r.get("current_ratio"), r.get("debt_to_assets")
    checks.append(None if not isinstance(cr, float) else cr > 1)
    checks.append(None if not isinstance(da, float) else da < 1)
    known = [c for c in checks if c is not None]
    if len(known) < 3:
        return None
    return 100.0 * sum(known) / len(known)
