"""Intraday detectors: what in the live market-watch feed means "a holding is in trouble now".

Everything here is pure. The monitor (``tmon.portfolio.monitor``) feeds one poll at a time (every
~20 seconds while the exchange is open) and turns the returned :class:`Finding` objects into
alerts. Thresholds come from each portfolio's ``settings`` merged over :data:`DEFAULTS`.

Detectors per holding:

* ``sell_queue``   the best ask sits at the lower price limit with buyers gone (a sell queue), sized
                   against the symbol's average daily volume. The case of a stock that is normal at
                   9:00 and has a billion shares queued for sale at 10:00.
* ``heavy_supply`` a large block offered on the 5 ask levels (not yet a queue).
* ``buy_queue_lost`` a buy queue at the upper limit dissolved: the buyers left.
* ``volume_surge`` traded volume of the last few minutes far above the symbol's normal pace.
* ``price_drop``   the day's change below the warning / urgent levels, or at the lower limit.
* ``stop_loss``    the last price reached the holding's stop.
* ``real_outflow`` individuals (حقیقی) are net sellers of a large part of the day's value.
* ``halt``         the symbol was stopped during trading hours (often a pending disclosure).
* ``supervisor``   a market-supervisor message names the symbol.

Market-wide: ``index_drop`` on the main index (sent to every portfolio that holds shares).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from tmon.ingest.tsetmc import quotes

DEFAULTS: dict[str, Any] = {
    "drop_warn_pct": -3.0,  # day change at or below: warning
    "drop_urgent_pct": -5.0,  # urgent (and always urgent at the lower limit)
    "stop_loss_pct": 10.0,  # stop below the average price when the holding has no stop_price
    "take_profit_pct": None,  # optional: info alert once the gain reaches this
    "volume_surge_x": 3.0,  # recent pace vs the normal pace
    "volume_window_minutes": 5,
    "sell_queue_warn_days": 0.1,  # queued volume / average daily volume
    "sell_queue_urgent_days": 0.5,
    "heavy_supply_days": 1.0,  # 5-level ask volume / average daily volume
    "real_outflow_ratio": 0.3,  # net individual selling / traded value
    "real_outflow_min_value": 5e9,  # rial: ignore thinly traded days
    "index_drop_warn_pct": -1.5,
    "index_drop_urgent_pct": -2.5,
    "index_slide_pct": 1.2,  # fall from the day's high
    "push_min_severity": 2,  # channels get warning and urgent; the page shows everything
}

INFO, WARN, URGENT = 1, 2, 3
MAIN_INDEX_CODE = "32097828799138957"  # شاخص کل (TSETMC insCode)


def settings_for(custom: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (custom or {}).items() if k in DEFAULTS})
    return out


@dataclass(frozen=True)
class Level:
    bid_price: float
    bid_volume: float
    ask_price: float
    ask_volume: float


@dataclass(frozen=True)
class Quote:
    """One row of ``GetMarketWatch`` with the fields the detectors read."""

    ins_code: str
    symbol: str
    last: float | None
    close: float | None
    yesterday: float | None
    limit_up: float | None
    limit_down: float | None
    volume: float
    value: float
    levels: tuple[Level, ...]

    @property
    def change_pct(self) -> float | None:
        if not self.last or not self.yesterday:
            return None
        return (self.last / self.yesterday - 1) * 100

    @property
    def in_sell_queue(self) -> bool:
        if not self.levels or not self.limit_down:
            return False
        top = self.levels[0]
        return top.ask_price > 0 and top.ask_price <= self.limit_down and top.bid_volume <= 0

    @property
    def in_buy_queue(self) -> bool:
        if not self.levels or not self.limit_up:
            return False
        top = self.levels[0]
        return top.bid_price >= self.limit_up and top.ask_volume <= 0


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_quote(row: dict[str, Any]) -> Quote:
    levels = tuple(
        Level(
            bid_price=_f(b.get("pmd")) or 0.0,
            bid_volume=_f(b.get("qmd")) or 0.0,
            ask_price=_f(b.get("pmo")) or 0.0,
            ask_volume=_f(b.get("qmo")) or 0.0,
        )
        for b in sorted(row.get("blDs") or [], key=lambda b: int(b.get("n") or 0))
    )
    r = quotes.read(row)
    return Quote(
        ins_code=str(row["insCode"]),
        symbol=r["symbol"],
        last=r["last"],
        close=r["close"],
        yesterday=r["yesterday"],
        limit_up=r["limit_up"],
        limit_down=r["limit_down"],
        volume=r["volume"] or 0.0,
        value=r["value"] or 0.0,
        levels=levels,
    )


@dataclass(frozen=True)
class HoldingView:
    """What a detector needs to know about one holding of one portfolio."""

    holding_id: int
    portfolio_id: int
    instrument_id: int
    ins_code: str
    symbol: str
    shares: float
    avg_price: float
    stop_price: float | None
    avg_daily_volume: float | None  # 20 trading days


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: int
    instrument_id: int | None
    title: str
    body: str
    key: str  # same key = same condition; a repeat alerts only when severity rises
    data: dict[str, Any] = field(default_factory=dict)
    ask_exit: bool = False  # the alert asks the owner whether to sell


@dataclass
class WatchState:
    """Kept between polls of one monitor process: recent volumes and queue states."""

    history: dict[str, deque[tuple[datetime, float, float | None]]] = field(default_factory=dict)
    buy_queue: dict[str, bool] = field(default_factory=dict)
    states: dict[str, str] = field(default_factory=dict)
    index_high: float | None = None
    seen_messages: set[str] = field(default_factory=set)

    def push(self, q: Quote, at: datetime, keep_minutes: int = 30) -> None:
        h = self.history.setdefault(q.ins_code, deque())
        h.append((at, q.volume, q.last))
        while h and at - h[0][0] > timedelta(minutes=keep_minutes):
            h.popleft()

    def window(
        self, ins_code: str, at: datetime, minutes: int
    ) -> tuple[float, float | None, float]:
        """(volume traded in the window, price at its start, window length in minutes)."""
        h = self.history.get(ins_code)
        if not h or len(h) < 2:
            return 0.0, None, 0.0
        start = next((x for x in h if at - x[0] <= timedelta(minutes=minutes)), h[0])
        if start is h[-1]:
            start = h[-2]
        span = (h[-1][0] - start[0]).total_seconds() / 60
        return max(0.0, h[-1][1] - start[1]), start[2], span


def _pct(x: float) -> str:
    return f"{x:+.1f}٪".replace("+-", "−").replace("-", "−")


def _num(x: float) -> str:
    for div, unit in ((1e9, " میلیارد"), (1e6, " میلیون"), (1e3, " هزار")):
        if abs(x) >= div:
            return f"{x / div:,.1f}{unit}"
    return f"{x:,.0f}"


def _bucket(at: datetime, minutes: int = 30) -> str:
    return at.strftime("%Y%m%d") + f"-{(at.hour * 60 + at.minute) // minutes}"


def _day(at: datetime) -> str:
    return at.strftime("%Y%m%d")


def detect_holding(
    h: HoldingView,
    q: Quote,
    state: WatchState,
    cfg: dict[str, Any],
    at: datetime,
    session_minutes: float,
) -> list[Finding]:
    """Everything wrong (or notably right) with one holding at this poll."""
    out: list[Finding] = []
    day = _day(at)
    base = f"{h.portfolio_id}:{h.instrument_id}"
    sym = h.symbol or q.symbol
    adv = h.avg_daily_volume or 0.0
    chg = q.change_pct
    top = q.levels[0] if q.levels else None

    # sell queue: the clearest "get out" signal of this market
    if q.in_sell_queue and top is not None:
        days = top.ask_volume / adv if adv > 0 else None
        sev = WARN
        if days is not None and days >= cfg["sell_queue_urgent_days"]:
            sev = URGENT
        elif days is not None and days < cfg["sell_queue_warn_days"]:
            sev = WARN
        size = f"{_num(top.ask_volume)} سهم" + (
            f" (حدود {days:.1f} برابر حجم روزانهٔ معمول)" if days is not None else ""
        )
        out.append(
            Finding(
                "sell_queue",
                sev,
                h.instrument_id,
                f"صف فروش در {sym}",
                f"{sym} در صف فروش است: {size} در قیمت کف دامنه برای فروش گذاشته شده و "
                "خریداری در سمت تقاضا نیست. آیا می‌خواهید از سهم خارج شوید؟",
                f"{base}:sell_queue:{day}",
                {"ask_volume": top.ask_volume, "queue_days": days, "price": top.ask_price},
                ask_exit=True,
            )
        )
    elif top is not None and adv > 0:
        supply = sum(lv.ask_volume for lv in q.levels)
        demand = sum(lv.bid_volume for lv in q.levels)
        ratio = supply / adv
        if ratio >= cfg["heavy_supply_days"] and supply > 3 * max(demand, 1.0):
            out.append(
                Finding(
                    "heavy_supply",
                    WARN,
                    h.instrument_id,
                    f"عرضهٔ سنگین در {sym}",
                    f"{_num(supply)} سهم {sym} در ۵ ردیف فروش است ({ratio:.1f} برابر حجم روزانهٔ "
                    f"معمول) در برابر {_num(demand)} سهم خرید. یک فروشندهٔ بزرگ وارد شده؛ "
                    "اگر خبری پشتش باشد ممکن است صف فروش شود.",
                    f"{base}:heavy_supply:{_bucket(at, 60)}",
                    {"supply": supply, "demand": demand, "supply_days": ratio},
                    ask_exit=True,
                )
            )

    # buy queue that dissolved
    was_bq = state.buy_queue.get(q.ins_code)
    now_bq = q.in_buy_queue
    state.buy_queue[q.ins_code] = now_bq
    if was_bq and not now_bq:
        out.append(
            Finding(
                "buy_queue_lost",
                WARN,
                h.instrument_id,
                f"صف خرید {sym} ریخت",
                f"صف خرید {sym} در سقف دامنه جمع شد؛ خریدارها کنار کشیدند. "
                "اگر سود گرفته‌ای، وقت تصمیم است.",
                f"{base}:buy_queue_lost:{_bucket(at, 60)}",
                {"price": q.last},
                ask_exit=True,
            )
        )

    # volume surge against the normal pace of the session
    vol, p0, span = state.window(q.ins_code, at, int(cfg["volume_window_minutes"]))
    if adv > 0 and span >= 1 and session_minutes > 0:
        expected = adv / session_minutes * span
        x = vol / expected if expected > 0 else 0.0
        if x >= cfg["volume_surge_x"]:
            falling = p0 is not None and q.last is not None and q.last < p0
            sev = WARN if falling or (chg is not None and chg < 0) else INFO
            if falling and chg is not None and chg <= cfg["drop_warn_pct"]:
                sev = URGENT
            move = (
                ""
                if p0 is None or not q.last
                else f" قیمت در همین مدت {_pct((q.last / p0 - 1) * 100)}"
            )
            out.append(
                Finding(
                    "volume_surge",
                    sev,
                    h.instrument_id,
                    f"جهش حجم در {sym}",
                    f"در {span:.0f} دقیقهٔ اخیر {_num(vol)} سهم {sym} معامله شد، {x:.1f} برابر "
                    f"روال معمول.{move}."
                    + (" فشار فروش است؛ خبرش را بررسی کن." if sev > INFO else ""),
                    f"{base}:volume_surge:{_bucket(at, 30)}",
                    {"window_volume": vol, "pace_x": x, "minutes": span},
                    ask_exit=sev >= WARN,
                )
            )

    # price
    if chg is not None:
        at_floor = bool(q.limit_down and q.last and q.last <= q.limit_down)
        if at_floor or chg <= cfg["drop_urgent_pct"]:
            sev = URGENT
        elif chg <= cfg["drop_warn_pct"]:
            sev = WARN
        else:
            sev = 0
        if sev:
            out.append(
                Finding(
                    "price_drop",
                    sev,
                    h.instrument_id,
                    f"افت {sym} {_pct(chg)}",
                    f"آخرین قیمت {sym} {_num(q.last or 0)} ریال، {_pct(chg)} نسبت به دیروز"
                    + (" و در کف دامنه است." if at_floor else "."),
                    f"{base}:price_drop:{day}",
                    {"change_pct": chg, "last": q.last, "at_floor": at_floor},
                    ask_exit=sev == URGENT,
                )
            )

    # stop loss and take profit (against the owner's own price)
    stop = h.stop_price or (
        h.avg_price * (1 - cfg["stop_loss_pct"] / 100) if cfg["stop_loss_pct"] else None
    )
    if stop and q.last and q.last <= stop:
        loss = (q.last / h.avg_price - 1) * 100 if h.avg_price else 0.0
        out.append(
            Finding(
                "stop_loss",
                URGENT,
                h.instrument_id,
                f"حد ضرر {sym} خورد",
                f"قیمت {sym} به {_num(q.last)} ریال رسید، زیر حد ضرر {_num(stop)} "
                f"({_pct(loss)} نسبت به میانگین خرید تو). خارج می‌شوی؟",
                f"{base}:stop_loss:{day}",
                {"stop": stop, "last": q.last, "pnl_pct": loss},
                ask_exit=True,
            )
        )
    tp = cfg.get("take_profit_pct")
    if tp and q.last and h.avg_price and (q.last / h.avg_price - 1) * 100 >= tp:
        out.append(
            Finding(
                "take_profit",
                INFO,
                h.instrument_id,
                f"{sym} به هدف سود رسید",
                f"{sym} {_pct((q.last / h.avg_price - 1) * 100)} بالای میانگین خرید توست.",
                f"{base}:take_profit:{day}",
                {"last": q.last},
            )
        )
    return out


def detect_real_flow(
    h: HoldingView, flow: dict[str, Any], q: Quote | None, cfg: dict[str, Any], at: datetime
) -> Finding | None:
    """Individuals' net selling from ``ClientType/GetClientTypeAll`` (one row per instrument)."""
    buy = _f(flow.get("buy_I_Volume")) or 0.0
    sell = _f(flow.get("sell_I_Volume")) or 0.0
    price = (q.last if q else None) or 0.0
    value = q.value if q else 0.0
    if not price or value < cfg["real_outflow_min_value"]:
        return None
    net = (buy - sell) * price
    ratio = net / value
    if ratio > -cfg["real_outflow_ratio"]:
        return None
    bc, sc = _f(flow.get("buy_CountI")) or 0.0, _f(flow.get("sell_CountI")) or 0.0
    power = (buy / bc) / (sell / sc) if bc and sc and sell else None
    sym = h.symbol
    tail = f" قدرت خریدار به فروشنده {power:.2f}." if power else ""
    return Finding(
        "real_outflow",
        WARN,
        h.instrument_id,
        f"خروج پول حقیقی از {sym}",
        f"حقیقی‌ها امروز {_num(-net)} ریال بیشتر از آنچه خریدند از {sym} فروختند "
        f"({abs(ratio) * 100:.0f}٪ ارزش معاملات).{tail}",
        f"{h.portfolio_id}:{h.instrument_id}:real_outflow:{_bucket(at, 60)}",
        {"net_value": net, "ratio": ratio, "power": power},
        ask_exit=True,
    )


def detect_state(
    h: HoldingView, code: str | None, state: WatchState, at: datetime
) -> Finding | None:
    """A held symbol stopped during trading hours (``cEtaval`` AS / IS after being open)."""
    if not code:
        return None
    code = code.strip().upper()
    before = state.states.get(h.ins_code)
    state.states[h.ins_code] = code
    if before in (None, code):
        return None
    if code in ("AS", "IS") and before in ("A", "AR"):
        return Finding(
            "halt",
            URGENT,
            h.instrument_id,
            f"نماد {h.symbol} متوقف شد",
            f"معاملات {h.symbol} وسط بازار متوقف شد. توقف معمولاً پیش از یک خبر یا افشای مهم است؛ "
            "کدال و پیام ناظر را ببینید. بعد از بازگشایی تصمیم می‌گیرید چه کنید؟",
            f"{h.portfolio_id}:{h.instrument_id}:halt:{_bucket(at, 60)}",
            {"from": before, "to": code},
            ask_exit=True,
        )
    if code == "A" and before in ("AS", "IS", "AR", "IR"):
        return Finding(
            "reopen",
            INFO,
            h.instrument_id,
            f"{h.symbol} بازگشایی شد",
            f"معاملات {h.symbol} دوباره باز شد.",
            f"{h.portfolio_id}:{h.instrument_id}:reopen:{_bucket(at, 60)}",
            {"from": before, "to": code},
        )
    return None


NEGATIVE_WORDS = ("توقف", "تعلیق", "زیان", "کاهش", "تعدیل منفی", "ممنوع", "محدودیت", "احتیاط")


def detect_message(
    h: HoldingView, msg: dict[str, Any], state: WatchState, at: datetime
) -> Finding | None:
    """A supervisor message (``Msg/GetMsgByFlow``) whose title or text names the holding."""
    title = str(msg.get("tseTitle") or "")
    text = str(msg.get("tseDesc") or "")
    ident = f"{msg.get('dEven')}-{msg.get('hEven')}-{title[:40]}"
    if not h.symbol or (h.symbol not in title and h.symbol not in text):
        return None
    if f"{h.portfolio_id}:{ident}" in state.seen_messages:
        return None
    state.seen_messages.add(f"{h.portfolio_id}:{ident}")
    bad = any(w in title or w in text for w in NEGATIVE_WORDS)
    return Finding(
        "supervisor",
        URGENT if bad else WARN,
        h.instrument_id,
        f"پیام ناظر: {h.symbol}",
        f"{title}\n{text[:400]}",
        f"{h.portfolio_id}:{h.instrument_id}:supervisor:{ident}",
        {"title": title},
        ask_exit=bad,
    )


def detect_index(
    portfolio_id: int,
    row: dict[str, Any] | None,
    state: WatchState,
    cfg: dict[str, Any],
    at: datetime,
) -> Finding | None:
    """The main index: a deep day change or a fast slide from the day's high."""
    if not row:
        return None
    value = _f(row.get("xDrNivJIdx004"))
    chg = _f(row.get("xVarIdxJRfV"))
    if value is None or chg is None:
        return None
    state.index_high = max(state.index_high or value, value)
    slide = (value / state.index_high - 1) * 100 if state.index_high else 0.0
    if chg <= cfg["index_drop_urgent_pct"]:
        sev = URGENT
    elif chg <= cfg["index_drop_warn_pct"] or slide <= -cfg["index_slide_pct"]:
        sev = WARN
    else:
        return None
    return Finding(
        "index_drop",
        sev,
        None,
        f"شاخص کل {_pct(chg)}",
        f"شاخص کل به {value:,.0f} رسید ({_pct(chg)} امروز، {_pct(slide)} از سقف امروز). "
        "فشار فروش کل بازار را گرفته؛ سهم‌های پرتفوی را مرور کن.",
        f"{portfolio_id}:index:{_day(at)}",
        {"value": value, "change_pct": chg, "from_high_pct": slide},
        ask_exit=sev == URGENT,
    )
