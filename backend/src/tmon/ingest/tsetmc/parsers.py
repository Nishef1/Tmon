"""Pure parsers for TSETMC payloads. No I/O; every function takes text/JSON."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from tmon.core.timeutil import yyyymmdd_to_date

# Arabic -> Persian letter normalisation (TSETMC mixes both).
_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک", "‌": " "})


def normalize_fa(text: str) -> str:
    return " ".join(text.translate(_ARABIC_TO_PERSIAN).split())


class ParseError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Market watch -> instrument list
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WatchInstrument:
    ins_code: str
    isin: str
    symbol_fa: str
    name_fa: str


def parse_market_watch_init(text: str) -> list[WatchInstrument]:
    """``MarketWatchInit.aspx``: groups separated by ``@``; group 2 holds instruments
    separated by ``;``, fields by ``,`` (0=ins_code, 1=isin, 2=symbol, 3=name)."""
    groups = text.split("@")
    if len(groups) < 3:
        raise ParseError("market watch payload has fewer than 3 groups")
    out: list[WatchInstrument] = []
    seen: set[str] = set()
    for chunk in groups[2].split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        f = chunk.split(",")
        if len(f) < 4 or not f[0].strip().isdigit():
            continue
        code = f[0].strip()
        if code in seen:
            continue
        seen.add(code)
        out.append(
            WatchInstrument(
                ins_code=code,
                isin=f[1].strip(),
                symbol_fa=normalize_fa(f[2]),
                name_fa=normalize_fa(f[3]),
            )
        )
    if not out:
        raise ParseError("market watch payload contained no instruments")
    return out


@dataclass(frozen=True)
class WatchQuote:
    """Live quote of one instrument from the market-watch payload.

    Column positions follow the open-source reference clients (``finpy-tse``): 4 time, 5 first,
    6 "final", 7 "close", 8 trades, 9 volume, 10 value, 11 low, 12 high, 13 yesterday's final.
    They are NOT verified against the live site; ``tmon.ingest.tsetmc.probe`` cross-checks them
    against the daily history (docs/OPEN_QUESTIONS.md)."""

    ins_code: str
    time_hhmmss: str
    first: float
    final: float
    close: float
    trades: int
    volume: float
    value: float
    low: float
    high: float
    yesterday: float


_QUOTE_MIN_FIELDS = 14


def _num(s: str) -> float:
    return float(s.strip() or 0)


def parse_market_watch_quotes(text: str) -> list[WatchQuote]:
    """Quotes for every instrument in the ``MarketWatchInit`` payload (same row layout as
    :func:`parse_market_watch_init`). Rows that do not parse are skipped; if most do not, the
    layout has changed and this raises instead of storing nonsense."""
    groups = text.split("@")
    if len(groups) < 3:
        raise ParseError("market watch payload has fewer than 3 groups")
    out: list[WatchQuote] = []
    rows = bad = 0
    for chunk in groups[2].split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        f = chunk.split(",")
        if not f[0].strip().isdigit():
            continue
        rows += 1
        if len(f) < _QUOTE_MIN_FIELDS:
            bad += 1
            continue
        try:
            q = WatchQuote(
                ins_code=f[0].strip(),
                time_hhmmss=f[4].strip(),
                first=_num(f[5]),
                final=_num(f[6]),
                close=_num(f[7]),
                trades=int(_num(f[8])),
                volume=_num(f[9]),
                value=_num(f[10]),
                low=_num(f[11]),
                high=_num(f[12]),
                yesterday=_num(f[13]),
            )
        except ValueError:
            bad += 1
            continue
        if q.high < q.low or min(q.volume, q.value, q.trades) < 0:
            bad += 1
            continue
        out.append(q)
    if not rows:
        raise ParseError("market watch payload contained no instruments")
    if bad > rows * 0.2:
        raise ParseError(f"market watch quote layout not recognised ({bad}/{rows} rows invalid)")
    return out


# --------------------------------------------------------------------------- #
# Instrument info (cdn JSON)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InstrumentInfo:
    ins_code: str
    isin: str | None
    symbol_fa: str | None
    name_fa: str | None
    sector_code: str | None
    sector_title: str | None
    group_code: str | None
    group_title: str | None
    flow: int | None
    flow_title: str | None
    base_volume: float | None
    shares: float | None
    # TSETMC's own instrument-type code and, for funds, the fund-type text
    type_code: str | None = None
    fund_desc: str | None = None


def parse_instrument_info(payload: str | dict[str, Any]) -> InstrumentInfo:
    data = json.loads(payload) if isinstance(payload, str) else payload
    info = data.get("instrumentInfo")
    if not isinstance(info, dict):
        raise ParseError("missing instrumentInfo")

    def _s(key: str) -> str | None:
        v = info.get(key)
        return None if v in (None, "") else str(v)

    def _f(key: str) -> float | None:
        v = info.get(key)
        return None if v in (None, "") else float(v)

    def _fa(key: str) -> str | None:
        v = info.get(key)
        return normalize_fa(str(v)) if v else None

    sector = info.get("sector") or {}
    return InstrumentInfo(
        ins_code=str(info.get("insCode", "")),
        isin=_s("cIsin"),
        symbol_fa=_fa("lVal18AFC"),
        name_fa=_fa("lVal30"),
        sector_code=str(sector["cSecVal"]).strip() if sector.get("cSecVal") else None,
        sector_title=normalize_fa(str(sector["lSecVal"])) if sector.get("lSecVal") else None,
        group_code=_s("cgrValCot"),
        group_title=_fa("cgrValCotTitle"),
        flow=int(info["flow"]) if info.get("flow") not in (None, "") else None,
        flow_title=_fa("flowTitle"),
        base_volume=_f("baseVol"),
        shares=_f("zTitad"),
        type_code=_s("yVal"),
        fund_desc=_fa("faraDesc"),
    )


# --------------------------------------------------------------------------- #
# Daily history (Export-txt CSV)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DailyBar:
    date: date
    open: float
    high: float
    low: float
    close: float  # official final price (<CLOSE>, پایانی)
    last: float  # last trade price (<LAST>, آخرین)
    prev_close: float  # <OPEN> in this export = previous final price
    volume: float
    value: float
    trades: int


_HISTORY_COLUMNS = {
    "date": "<DTYYYYMMDD>",
    "open": "<FIRST>",
    "high": "<HIGH>",
    "low": "<LOW>",
    "close": "<CLOSE>",
    "last": "<LAST>",
    "prev_close": "<OPEN>",
    "volume": "<VOL>",
    "value": "<VALUE>",
    "trades": "<OPENINT>",
}


def parse_daily_history(text: str) -> list[DailyBar]:
    """Parse the CSV export, oldest first. Columns are matched by header name."""
    text = text.strip().lstrip("﻿")
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    missing = [raw for raw in _HISTORY_COLUMNS.values() if raw not in header]
    if missing:
        raise ParseError(f"daily history header missing columns: {missing}")
    bars: list[DailyBar] = []
    for row in reader:
        try:
            bars.append(
                DailyBar(
                    date=yyyymmdd_to_date(row[_HISTORY_COLUMNS["date"]]),
                    open=float(row[_HISTORY_COLUMNS["open"]]),
                    high=float(row[_HISTORY_COLUMNS["high"]]),
                    low=float(row[_HISTORY_COLUMNS["low"]]),
                    close=float(row[_HISTORY_COLUMNS["close"]]),
                    last=float(row[_HISTORY_COLUMNS["last"]]),
                    prev_close=float(row[_HISTORY_COLUMNS["prev_close"]]),
                    volume=float(row[_HISTORY_COLUMNS["volume"]]),
                    value=float(row[_HISTORY_COLUMNS["value"]]),
                    trades=int(float(row[_HISTORY_COLUMNS["trades"]])),
                )
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise ParseError(f"bad history row {row!r}: {exc}") from exc
    bars.sort(key=lambda b: b.date)
    return bars


# --------------------------------------------------------------------------- #
# Client types (real = I / legal = N)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClientTypeRow:
    date: date
    buy_count_i: int
    buy_count_n: int
    sell_count_i: int
    sell_count_n: int
    buy_volume_i: float
    buy_volume_n: float
    sell_volume_i: float
    sell_volume_n: float
    buy_value_i: float | None = None
    buy_value_n: float | None = None
    sell_value_i: float | None = None
    sell_value_n: float | None = None


def parse_client_types(text: str) -> list[ClientTypeRow]:
    """Rows separated by ``;``; fields by ``,``:
    date, buy_count I, N, sell_count I, N, buy_vol I, N, sell_vol I, N, then (optional)
    buy_val I, N, sell_val I, N."""
    rows: list[ClientTypeRow] = []
    for chunk in text.strip().split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        f = [p.strip() for p in chunk.split(",")]
        if len(f) < 9:
            continue  # e.g. an "empty" marker row
        try:
            vals = [float(x) for x in f[1:]]
            d = yyyymmdd_to_date(f[0])
        except ValueError as exc:
            raise ParseError(f"bad client-type row {chunk!r}: {exc}") from exc
        has_values = len(vals) >= 12
        rows.append(
            ClientTypeRow(
                date=d,
                buy_count_i=int(vals[0]),
                buy_count_n=int(vals[1]),
                sell_count_i=int(vals[2]),
                sell_count_n=int(vals[3]),
                buy_volume_i=vals[4],
                buy_volume_n=vals[5],
                sell_volume_i=vals[6],
                sell_volume_n=vals[7],
                buy_value_i=vals[8] if has_values else None,
                buy_value_n=vals[9] if has_values else None,
                sell_value_i=vals[10] if has_values else None,
                sell_value_n=vals[11] if has_values else None,
            )
        )
    rows.sort(key=lambda r: r.date)
    return rows


# --------------------------------------------------------------------------- #
# Order book (cdn BestLimits JSON)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BookLevel:
    row: int
    bid_price: float
    bid_volume: float
    bid_count: int
    ask_price: float
    ask_volume: float
    ask_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "row": self.row,
            "bid_price": self.bid_price,
            "bid_volume": self.bid_volume,
            "bid_count": self.bid_count,
            "ask_price": self.ask_price,
            "ask_volume": self.ask_volume,
            "ask_count": self.ask_count,
        }


def parse_best_limits(payload: str | dict[str, Any]) -> list[BookLevel]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = data.get("bestLimits")
    if rows is None:
        raise ParseError("missing bestLimits")
    try:
        levels = [
            BookLevel(
                row=int(r["number"]),
                bid_price=float(r["pMeDem"]),
                bid_volume=float(r["qTitMeDem"]),
                bid_count=int(r["zOrdMeDem"]),
                ask_price=float(r["pMeOf"]),
                ask_volume=float(r["qTitMeOf"]),
                ask_count=int(r["zOrdMeOf"]),
            )
            for r in rows
        ]
    except (KeyError, ValueError, TypeError) as exc:
        raise ParseError(f"bad bestLimits row: {exc}") from exc
    return sorted(levels, key=lambda lv: lv.row)


@dataclass(frozen=True)
class IndexBar:
    """One day of an index. ``xNivInuClMresIbs`` close, ``xNivInuPhMresIbs`` high and
    ``xNivInuPbMresIbs`` low (checked against the live payload: low <= close <= high)."""

    day: date
    close: float
    high: float
    low: float


def parse_index_history(payload: str | dict[str, Any]) -> list[IndexBar]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = data.get("indexB2")
    if rows is None:
        raise ParseError("missing indexB2")
    out: list[IndexBar] = []
    for r in rows:
        try:
            bar = IndexBar(
                day=yyyymmdd_to_date(int(r["dEven"])),
                close=float(r["xNivInuClMresIbs"]),
                high=float(r["xNivInuPhMresIbs"]),
                low=float(r["xNivInuPbMresIbs"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ParseError(f"bad index row {r!r}: {exc}") from exc
        if bar.close > 0 and bar.low <= bar.high:
            out.append(bar)
    return out


# --------------------------------------------------------------------------- #
# TSETMC's own adjusted daily series (chart data, a=1)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AdjustedBar:
    """``yyyymmdd,high,low,open,last,volume,final`` as served by ``Financial.aspx?t=ph&a=1``
    (field order checked against the raw ``a=0`` variant: same dates, the last day equals the
    Export-txt bar). Prices are integer-rounded by the source."""

    day: date
    high: float
    low: float
    open: float
    last: float
    volume: float
    close: float


def parse_adjusted_history(text: str) -> list[AdjustedBar]:
    out: list[AdjustedBar] = []
    for chunk in text.strip().split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        f = chunk.split(",")
        if len(f) != 7:
            raise ParseError(f"adjusted history row has {len(f)} fields: {chunk!r}")
        try:
            out.append(
                AdjustedBar(
                    day=yyyymmdd_to_date(f[0]),
                    high=float(f[1]),
                    low=float(f[2]),
                    open=float(f[3]),
                    last=float(f[4]),
                    volume=float(f[5]),
                    close=float(f[6]),
                )
            )
        except (ValueError, TypeError) as exc:
            raise ParseError(f"bad adjusted history row {chunk!r}: {exc}") from exc
    out.sort(key=lambda b: b.day)
    return out
