"""Where one holding stands for its owner, in their own money (docs/17).

Pure functions. The numbers are the owner's: average price with buy fees, shares, the price a sale
would get now, the sell fee with tax, and the stop that the monitor watches. The exit result comes
from docs/reports/holder-exit-2026-11.md: no exit rule beat holding in both halves of the last three
years. The default 10% stop changed the 20-day mean very little and cut the worst losses, so the
card calls it risk control, not a way to earn more.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from tmon.engine.verdict import CODE_FA

# docs/reports/holder-exit-2026-11.md, cash earning the one-year bond yield
STOP_STUDY_FA = (
    "در آزمون سه سال اخیر، حد ضرر ۱۰٪ زیر قیمت خرید بازده میانگین ۲۰ روزه را تقریباً عوض نکرد، "
    "ولی زیان ۵ خرید بدتر از هر ۱۰۰ خرید را از حدود ۲۰٪ به حدود ۱۴٪ رساند. در بازار صعودی، در ۶۰ "
    "روز بخشی از سود را هم از دست داد. هیچ قاعدهٔ خروج دیگری (حد ضرر شناور، میانگین ۲۰ یا ۵۰ روزه) "
    "در هر دو نیمهٔ زمان از نگه داشتن بهتر نبود. "
    "پس حد ضرر برای محدود کردن زیان است، نه برای سود بیشتر."
)
OWN_STOP_FA = (
    "در آزمون سه سال اخیر هیچ حد ضرری بازده میانگین را بیشتر نکرد؛ حد ضرر فقط بدترین زیان را "
    "محدود می‌کند، و هرچه نزدیک‌تر باشد بیشتر فعال می‌شود."
)
SUNK_FA = (
    "قیمت خرید شما آیندهٔ این سهم را عوض نمی‌کند. نگه داشتن همان تصمیم «امروز این سهم را "
    "می‌خریدم؟» است."
)


def _toman(rial: float) -> str:
    return f"{abs(rial) / 10:,.0f}"


def position_plan(
    *,
    avg_price: float,
    shares: float,
    price: float | None,
    sell_rate: float,
    stop_price: float | None,
    default_stop_pct: float | None,
    bought_on: dt.date | None,
    today: dt.date,
    buyer_code: str | None,
) -> dict[str, Any] | None:
    """The card's numbers and its plain sentences, or ``None`` without a price or a cost."""
    if not price or not avg_price or shares <= 0:
        return None
    breakeven = avg_price / (1 - sell_rate)
    net = (price * (1 - sell_rate) - avg_price) * shares  # rial, after the sell fee and tax
    net_pct = price * (1 - sell_rate) / avg_price - 1
    source = "user" if stop_price else ("default" if default_stop_pct else None)
    stop = stop_price or (avg_price * (1 - default_stop_pct / 100) if default_stop_pct else None)
    lines = [
        f"اگر امروز بفروشید، پس از کارمزد و مالیات فروش {_toman(net)} تومان "
        + ("سود" if net >= 0 else "زیان")
        + f" دارید ({net_pct * 100:+.1f}٪). قیمت سربه‌سر شما {breakeven:,.0f} ریال است."
    ]
    to_stop = loss_at_stop = None
    if stop:
        to_stop = stop / price - 1
        loss_at_stop = (stop * (1 - sell_rate) - avg_price) * shares
        named = (
            f"حد ضرر شما {stop:,.0f} ریال است"
            if source == "user"
            else f"حد ضرر پیش‌فرض پایشگر {stop:,.0f} ریال است "
            f"({default_stop_pct:g}٪ زیر میانگین خرید)"
        )
        if price <= stop:
            lines.append(
                f"{named} و قیمت به آن رسیده است. فروش در این قیمت حدود {_toman(loss_at_stop)} "
                "تومان زیان را قطعی می‌کند."
            )
        else:
            lines.append(
                f"{named}؛ قیمت باید {abs(to_stop) * 100:.1f}٪ دیگر پایین بیاید تا به آن برسد. "
                f"آن‌وقت زیان قطعی حدود {_toman(loss_at_stop)} تومان می‌شود."
            )
        lines.append(STOP_STUDY_FA if source == "default" else OWN_STOP_FA)
    if buyer_code in CODE_FA:
        lines.append(
            f"{SUNK_FA} حکم امروز این سهم برای کسی که آن را ندارد «{CODE_FA[buyer_code]}» است."
        )
    return {
        "breakeven": breakeven,
        "net_if_sold": net,
        "net_if_sold_pct": net_pct,
        "stop": stop,
        "stop_source": source,
        "to_stop_pct": to_stop,
        "loss_at_stop": loss_at_stop,
        "days_held": (today - bought_on).days if bought_on else None,
        "lines": lines,
    }
