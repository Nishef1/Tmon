"""The entry-odds document (``tmon.tools.entry_odds``) turned into plain readings.

``entry_odds_out`` is the tested history for the research pages, ``entry_out`` the symbol's part
for its dashboard. Every sentence follows the stored numbers; none of it feeds the verdict.
"""

from __future__ import annotations

from typing import Any

from tmon.api.schemas import (
    DashEntry,
    DashEntryMark,
    EntryHorizon,
    EntryOddsOut,
    EntrySetup,
    EntryYear,
    OwnOdds,
    OwnWindow,
)
from tmon.api.technical import load_doc
from tmon.backtest.entry_odds import OWN_WINDOWS, YEAR_MIN, year_count
from tmon.tools.entry_odds import KEY


def entry_doc() -> dict[str, Any] | None:
    return load_doc(KEY)


def _n(x: float) -> str:
    return f"{round(100 * x)}"


def verdict(s: dict[str, Any]) -> str:
    """One plain sentence on how the candles after this setup went, from its stored numbers."""
    label = s["label"]
    if label == "too_few":
        return f"نمونه کم است ({s['n']} بار)؛ حکمی نمی‌شود داد."
    if label in ("better", "worse"):
        h = s["best_h"]
        x = s[f"h{h}"]
        word = "بیشتر" if label == "better" else "کمتر"
        return (
            f"{h} کندل بعد از خرید، {_n(x['up'])} بار از ۱۰۰ بالاتر از قیمت خرید بوده؛ "
            f"{word} از بقیهٔ سهم‌ها در همان روزها ({_n(x['up_all'])} از ۱۰۰)، "
            "و در هر دو نیمهٔ تاریخچه همین‌طور."
        )
    x = s.get("h5") or s.get("h1") or {}
    tail = f" ({x and _n(x['up'])} در برابر {x and _n(x['up_all'])} از ۱۰۰ در ۵ کندل)" if x else ""
    if label == "mixed":
        return "در بعضی بازه‌ها بهتر و در بعضی بدتر از بقیهٔ سهم‌ها بوده؛ قابل اتکا نیست" + tail + "."
    return "تفاوت قابل اعتنایی با خریدن هر سهم دیگری در همان روزها نداشته" + tail + "."


def _setup(key: str, s: dict[str, Any], horizons: list[int]) -> EntrySetup:
    hs = []
    for h in horizons:
        x = s.get(f"h{h}")
        if not x:
            continue
        hs.append(
            EntryHorizon(
                h=h,
                n=x["n"],
                up=x["up"],
                up_all=x["up_all"],
                edge=x["edge"],
                halves_edge=[(b.get(f"h{h}") or {}).get("edge") for b in s["halves"]],
                excess_mean=x.get("excess_mean"),
                median=x.get("median"),
            )
        )
    years = s.get("years") or []
    yc = year_count(years, 5)
    return EntrySetup(
        years=[EntryYear(**y) for y in years],
        years_better=yc["better"],
        years_worse=yc["worse"],
        years_counted=sum(1 for y in years if y["n"] >= YEAR_MIN and y.get("e5") is not None),
        key=key,
        group=s["group"],
        title=s["title"],
        event=s["event"],
        label=s["label"],
        best_h=s.get("best_h"),
        verdict=verdict(s),
        n=s["n"],
        symbols=s["symbols"],
        locked_share=s.get("locked_share"),
        horizons=hs,
        **{
            k: s.get(k)
            for k in (
                "dip_hit",
                "dip_hit_all",
                "dip_median",
                "win",
                "win_all",
                "loss",
                "loss_all",
            )
        },
    )


def entry_odds_out(doc: dict[str, Any] | None) -> EntryOddsOut:
    if not doc:
        return EntryOddsOut(available=False)
    hz = doc["horizons"]
    br = doc.get("base_rule") or {}
    return EntryOddsOut(
        available=True,
        as_of=doc["as_of"],
        round_trip_cost=doc["round_trip_cost"],
        dir_edge=doc["dir_edge"],
        dip=doc["dip"],
        dip_within=doc["dip_within"],
        win=doc["win"],
        loss=doc["loss"],
        path=doc["path"],
        base_dd=br.get("dd"),
        base_range=br.get("range"),
        base_days=br.get("days"),
        history_first=doc["first"],
        history_last=doc["last"],
        split_date=doc["split_date"],
        groups=doc["groups"],
        setups=[_setup(k, s, hz) for k, s in doc["setups"].items()],
    )


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}٪"


def _signed_pct(x: float) -> str:
    return f"{x * 100:+.0f}٪".replace("+-", "−").replace("-", "−")


def forecast(own: list[OwnOdds], now: list[EntrySetup], window: str = "year") -> list[str]:
    """The plain answer to "what will the next candles do": the symbol's own record with its 95%
    interval and the band 8 in 10 outcomes fell in, then any setup it is in that changed the
    odds in both halves of the exchange history. Past counts, not a promise."""
    out: list[str] = []
    for x in own:
        if x.h not in (1, 5, 20):
            continue
        when = "کندل بعد" if x.h == 1 else f"{x.h} کندل بعد"
        line = f"{when}: شانس بالاتر بودن از قیمت خرید {_n(x.up)}٪ (همهٔ سهم‌ها {_n(x.up_all or 0)}٪)"
        if x.q10 is not None and x.q90 is not None:
            line += f"؛ ۸ بار از ۱۰ تغییر قیمت بین {_signed_pct(x.q10)} و {_signed_pct(x.q90)} بوده"
        out.append(line + ".")
    if own:
        x = next((o for o in own if o.h == 5), own[0])
        if x.lo > 0.5:
            out.append("در این سابقه ۵ کندل بعد بیشتر بالا رفته تا پایین، ولی نه همیشه.")
        elif x.hi < 0.5:
            out.append(
                "در این سابقه بیشتر پایین آمده تا بالا؛ کندل‌های سبز بعدی را نمی‌شود انتظار داشت."
            )
        else:
            out.append("یعنی جهت ۵ کندل بعد در سابقهٔ خود این سهم تقریباً شیر یا خط بوده است.")
    if own:
        out.append(
            (
                "این سابقهٔ خود این سهم از ابتدای امسال است"
                if window == "year"
                else "این سابقهٔ خود این سهم در همین بازه است"
            )
            + ": اگر سهم در این مدت روند تندی داشته، عدد همان روند را نشان می‌دهد و تضمین "
            "نمی‌کند ادامه پیدا کند. بازه‌های ۱۰ و ۲۰ کندل از روزهای هم‌پوشان ساخته شده‌اند و "
            "با سابقهٔ کوتاه کم‌اعتمادترند."
        )
    for st in now:
        if st.label in ("better", "worse"):
            word = "بیشتر" if st.label == "better" else "کمتر"
            out.append(
                f"این سهم الان در حالت «{st.title}» است که در کل بورس، در هر دو نیمهٔ تاریخچه، "
                f"کندل‌های بعدی را {word} از بقیهٔ سهم‌ها بالا برده است."
            )
    return out


def entry_out(doc: dict[str, Any] | None, instrument_id: int) -> DashEntry | None:
    """The symbol's part: its streak and base/uptrend, the setups it is in now with their
    tested odds, and its entry candles of the last year."""
    if not doc:
        return None
    me = (doc.get("now") or {}).get(str(instrument_id))
    if not me:
        return None
    hz = doc["horizons"]
    setups = doc["setups"]
    now = [_setup(k, setups[k], hz) for k in me["active"] if k in setups]
    marks = [
        DashEntryMark(
            key=m["key"],
            title=setups[m["key"]]["title"],
            date=m["date"],
            ago=m["ago"],
            label=setups[m["key"]]["label"],
        )
        for m in me["marks"]
        if m["key"] in setups
    ]
    lines: list[str] = []
    for k, word in (("green", "سبز"), ("red", "قرمز")):
        if me[k] == 1:
            lines.append(f"آخرین شمع {word} بوده و شمع پیش از آن {word} نبوده است.")
        elif me[k]:
            lines.append(f"آخرین {me[k]} شمع پشت سر هم {word} بوده است.")
    if me["in_base"]:
        lines.append(
            f"سهم در کف چندماهه است: {_pct(me['dd'] or 0)} زیر سقف ۵۲ هفته و ۶۰ روز اخیر در "
            f"دامنهٔ {_pct(me['rng60'] or 0)}."
        )
    mine = me.get("own") or {}
    windows = []
    for key, label, _ in OWN_WINDOWS:
        w = (mine.get("windows") or {}).get(key)
        if not w:
            continue
        odds = [OwnOdds(**x) for x in w["h"]]
        windows.append(
            OwnWindow(
                key=key,
                label=label,
                since=w["since"],
                odds=odds,
                forecast=forecast(odds, now, key),
            )
        )
    first = windows[0] if windows else None
    own = first.odds if first else []
    if me["in_up"]:
        lines.append("سهم در روند صعودی است: میانگین ۲۰ روزه بالای ۵۰ و ۵۰ بالای ۲۰۰.")
    return DashEntry(
        as_of=doc["as_of"],
        green=me["green"],
        red=me["red"],
        in_base=me["in_base"],
        in_up=me["in_up"],
        dd=me.get("dd"),
        rng60=me.get("rng60"),
        now=now,
        marks=marks,
        lines=lines,
        own_since=first.since if first else None,
        own_close=mine.get("close"),
        own=own,
        forecast=first.forecast if first else [],
        windows=windows,
    )
