"""What moves a Tehran stock besides its own chart? One-off research behind
docs/reports/stock-drivers-2026-11.md.

Run from backend/ with the live env (see ../weekly_outlook/README.md) after
technical_signals/study.py; argv[1] = the same scratch dir (reads ts_panel.parquet, writes
sd_*.json). Uses the free-market dollar (tgju), world copper/Brent/gold/DXY (Yahoo), TEDPIX,
Codal letters and the dated shocks in config/market_events.csv. Weeks run Saturday to Wednesday, the
Tehran trading week; a series' weekly value is its last value in that week.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from tmon.core.db import session_scope

SP = sys.argv[1]
C = pl.col
G = "instrument_id"
TEDPIX = "32097828799138957"
MACRO = ["usd_free", "copper_usd", "brent_usd", "gold_usd", "dxy"]
FOCUS = {"فملی": 2448, "وبملت": 1037, "شکام": 2672}
OTHERS = {"فولاد": 857, "شپنا": 3364, "خودرو": 853, "فارس": 763, "شستا": 3157,
          "اخابر": 3461, "کگل": 1952, "پارسان": 1781, "شبندر": 913, "وغدیر": 1723}  # fmt: skip
ERAS = [("2012", date(2012, 1, 1), date(2015, 12, 31)), ("2016", date(2016, 1, 1),
        date(2019, 12, 31)), ("2020", date(2020, 1, 1), date(2022, 12, 31)),
        ("2023", date(2023, 1, 1), date(2026, 12, 31))]  # fmt: skip
HERE = Path(__file__).parent


def read_events() -> list[dict[str, str]]:
    with open(HERE.parents[1] / "config" / "market_events.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def sql(q: str) -> pl.DataFrame:
    with session_scope() as s:
        return pl.read_database(q, s.connection())


def week(e: pl.Expr) -> pl.Expr:
    # Saturday..Friday share a key: +2 days moves Saturday onto the ISO Monday
    return (e + pl.duration(days=2)).dt.truncate("1w")


def load() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    panel = pl.read_parquet(SP + "/ts_panel.parquet").select(
        G, "date", "close", "liquid", "x20", "x60"
    )
    idx = sql(
        f"select date, close as tedpix from market_index_daily where index_code='{TEDPIX}'"
    ).with_columns(C("date").cast(pl.String).str.slice(0, 10).str.to_date())
    mac = (
        sql(
            "select series, ref_period, release_date, value from macro_series where series in ("
            + ",".join(f"'{m}'" for m in MACRO)
            + ")"
        )
        .with_columns(
            C("ref_period").cast(pl.String).str.slice(0, 10).str.to_date(),
            C("release_date").cast(pl.String).str.slice(0, 10).str.to_date(),
        )
        .sort("series", "ref_period")
    )
    meta = sql("select id as instrument_id, symbol_fa, sector_code, tags from instruments")
    meta = meta.with_columns(
        sector=C("tags").str.json_path_match("$.sector_title"),
    ).drop("tags")
    return panel, idx, mac, meta


def weekly_grid(idx: pl.DataFrame, mac: pl.DataFrame) -> pl.DataFrame:
    w = idx.group_by(wk=week(C("date"))).agg(C("tedpix").sort_by("date").last()).sort("wk")
    for m in MACRO:
        s = mac.filter(C("series") == m).group_by(wk=week(C("ref_period")))
        s = s.agg(C("value").sort_by("ref_period").last().alias(m))
        w = w.join(s, on="wk", how="left")
    w = w.sort("wk").with_columns(pl.all().exclude("wk").forward_fill())
    w = w.with_columns(copper_rial=C("copper_usd") * C("usd_free"))
    cols = ["tedpix", *MACRO, "copper_rial"]
    return w.with_columns(*[(C(c).log().diff()).alias("r_" + c) for c in cols])


def stock_weekly(panel: pl.DataFrame, ids: list[int], grid: pl.DataFrame) -> pl.DataFrame:
    s = panel.filter(C(G).is_in(ids)).group_by(G, wk=week(C("date")))
    s = s.agg(C("close").sort_by("date").last())
    frames = []
    for i in ids:
        one = grid.select("wk").join(s.filter(C(G) == i), on="wk", how="left").sort("wk")
        one = one.with_columns(C("close").forward_fill(), pl.lit(i).alias(G))
        frames.append(one.with_columns(r=C("close").log().diff()))
    return pl.concat(frames).join(grid, on="wk")


def ols(y: np.ndarray, xs: np.ndarray) -> tuple[np.ndarray, float]:
    x = np.column_stack([np.ones(len(y)), xs])
    b, *_ = np.linalg.lstsq(x, y, rcond=None)
    res = y - x @ b
    r2 = 1 - res.var() / y.var() if y.var() > 0 else float("nan")
    return b[1:], float(r2)


def sensitivities(sw: pl.DataFrame, name: str, iid: int) -> dict:
    """Weekly betas on index and dollar, 4-week correlations with each outside price, lead/lag."""
    d = sw.filter(C(G) == iid).drop_nulls(["r", "r_tedpix", "r_usd_free"]).filter(C("r") != 0)
    out: dict = {"symbol": name, "eras": {}}
    for era, a, b in [("all", date(2012, 1, 1), date(2026, 12, 31)), *ERAS]:
        e = d.filter(C("wk").is_between(a, b))
        if e.height < 40:
            continue
        beta, r2 = ols(e["r"].to_numpy(), e.select("r_tedpix", "r_usd_free").to_numpy())
        m4 = (
            e.with_columns(blk=pl.int_range(pl.len()) // 4)
            .group_by("blk")
            .agg(pl.all().exclude("wk", G, "close", "blk").sum())
        )
        corr = {
            k: float(np.corrcoef(m4["r"], m4["r_" + k])[0, 1])
            for k in ["tedpix", *MACRO, "copper_rial"]
            if m4["r_" + k].drop_nulls().len() == m4.height and m4["r_" + k].std() > 0
        }
        lead = e.with_columns(pu=C("r_usd_free").shift(1), pi=C("r_tedpix").shift(1)).drop_nulls()
        out["eras"][era] = {
            "weeks": e.height,
            "beta_index": float(beta[0]),
            "beta_usd": float(beta[1]),
            "r2": r2,
            "corr4w": corr,
            "lead_usd": float(np.corrcoef(lead["r"], lead["pu"])[0, 1]),
            "lead_index": float(np.corrcoef(lead["r"], lead["pi"])[0, 1]),
        }
    return out


def zigzag(px: np.ndarray, th: float) -> list[int]:
    piv, ext, dirn = [0], 0, 0
    for i in range(1, len(px)):
        p = px[i]
        if dirn == 0:
            ext = i if abs(p / px[0] - 1) > abs(px[ext] / px[0] - 1) else ext
            if abs(px[ext] / px[0] - 1) >= th:
                dirn = 1 if px[ext] > px[0] else -1
        elif dirn == 1:
            if p > px[ext]:
                ext = i
            elif p / px[ext] - 1 <= -th:
                piv.append(ext)
                dirn, ext = -1, i
        else:
            if p < px[ext]:
                ext = i
            elif p / px[ext] - 1 >= th:
                piv.append(ext)
                dirn, ext = 1, i
    piv.append(ext)
    return piv


def daily_levels(idx: pl.DataFrame, mac: pl.DataFrame) -> pl.DataFrame:
    days = pl.DataFrame({"date": pl.date_range(date(2008, 1, 1), date(2026, 12, 31), eager=True)})
    d = days.join(idx, on="date", how="left")
    for m in MACRO:
        s = mac.filter(C("series") == m).select(C("ref_period").alias("date"), C("value").alias(m))
        d = d.join(s, on="date", how="left")
    return d.sort("date").with_columns(pl.all().exclude("date").forward_fill())


def legs(panel: pl.DataFrame, lv: pl.DataFrame, iid: int, sens: dict) -> list[dict]:
    p = panel.filter((C(G) == iid) & (C("date") >= date(2012, 1, 1))).sort("date")
    px = p["close"].to_numpy()
    dates = p["date"].to_list()
    piv = zigzag(px, 0.25)
    letters = sql(
        "select letter_code, title, published_at from codal_letters where instrument_id=" + str(iid)
    ).with_columns(day=C("published_at").cast(pl.String).str.slice(0, 10).str.to_date())
    corp = sql(
        "select type, coalesce(event_date, announced_at) as day, dps, increase_pct "
        f"from corporate_events where instrument_id={iid}"
    ).with_columns(C("day").cast(pl.String).str.slice(0, 10).str.to_date())
    events = read_events()
    era_beta = sens["eras"]
    out = []
    for a, b in itertools.pairwise(piv):
        da, db = dates[a], dates[b]
        la = lv.filter(C("date") == da).row(0, named=True)
        lb = lv.filter(C("date") == db).row(0, named=True)

        def chg(k: str, la: dict = la, lb: dict = lb) -> float | None:
            if la[k] is None or lb[k] is None:
                return None
            return float(lb[k] / la[k] - 1)

        r_s = float(px[b] / px[a] - 1)
        era = next((e for e, s, t in ERAS if s <= da <= t), "all")
        eb = era_beta.get(era) or era_beta["all"]
        r_i, r_u = chg("tedpix"), chg("usd_free")
        fit = None
        if r_i is not None and r_u is not None:
            fit = math.exp(eb["beta_index"] * math.log1p(r_i) + eb["beta_usd"] * math.log1p(r_u))
            fit -= 1
        win = letters.filter(C("day").is_between(da, db))
        cw = corp.filter(C("day").is_between(da, db))
        out.append(
            {
                "start": str(da),
                "end": str(db),
                "days": (db - da).days,
                "stock": r_s,
                "tedpix": r_i,
                "usd": r_u,
                "copper": chg("copper_usd"),
                "copper_rial": (
                    None
                    if chg("copper_usd") is None or r_u is None
                    else (1 + chg("copper_usd")) * (1 + r_u) - 1  # type: ignore[operator]
                ),
                "fit_index_usd": fit,
                "n30": win.filter(C("letter_code") == "ن-۳۰").height,
                "n10": win.filter(C("letter_code") == "ن-۱۰").height,
                "cap_incr": cw.filter(C("type") == "egm_capital_increase").height,
                "dps": cw.filter(C("type") == "agm_dividend")["dps"].drop_nulls().to_list(),
                "events": [
                    e["date"] + " " + e["title_fa"]
                    for e in events
                    if da <= date.fromisoformat(e["date"]) <= db
                ],
            }
        )
    return out


def codal_reaction(panel: pl.DataFrame, idx: pl.DataFrame) -> dict:
    """Is the day a monthly report or financial statement lands a bigger-than-usual move?"""
    let = sql(
        "select instrument_id, letter_code, published_at from codal_letters "
        "where instrument_id is not null and letter_code in ('ن-۳۰','ن-۱۰')"
    )
    let = let.with_columns(
        ts=C("published_at").cast(pl.String).str.slice(0, 19).str.to_datetime("%Y-%m-%d %H:%M:%S")
    )
    # Codal times are Tehran local; after 12:30 the market has closed, so day 0 is the next one
    let = let.with_columns(
        d0=pl.when(C("ts").dt.hour() * 60 + C("ts").dt.minute() >= 12 * 60 + 30)
        .then(C("ts").dt.date() + pl.duration(days=1))
        .otherwise(C("ts").dt.date())
    )
    ids = let[G].unique().to_list()
    p = panel.filter(C(G).is_in(ids)).sort(G, "date").join(idx, on="date", how="left")
    p = p.with_columns(
        ar=(C("close") / C("close").shift(1).over(G)) - (C("tedpix") / C("tedpix").shift(1).over(G))
    ).drop_nulls("ar")
    p = p.with_columns(aar=C("ar").abs())
    res: dict = {}
    for code in ("ن-۳۰", "ن-۱۰"):
        ev = let.filter(C("letter_code") == code).sort("d0").select(G, "d0")
        hit = ev.join_asof(
            p.select(G, "date").sort("date"), left_on="d0", right_on="date", by=G,
            strategy="forward", tolerance=timedelta(days=7),
        ).drop_nulls("date")  # fmt: skip
        tagged = p.join(hit.select(G, "date").unique().with_columns(ev=pl.lit(True)),
                        on=[G, "date"], how="left")  # fmt: skip
        tagged = tagged.with_columns(C("ev").fill_null(False))
        base = tagged.filter(~C("ev"))
        on = tagged.filter(C("ev"))
        nxt = tagged.with_columns(prev_ev=C("ev").shift(1).over(G)).filter(C("prev_ev"))
        res[code] = {
            "events": on.height,
            "abs_ar_event_day": float(on["aar"].mean()),
            "abs_ar_next_day": float(nxt["aar"].mean()),
            "abs_ar_other_days": float(base["aar"].mean()),
            "ar_event_day_mean": float(on["ar"].mean()),
            "ar_event_day_median": float(on["ar"].median()),
        }
    return res


def shocks(panel: pl.DataFrame, idx: pl.DataFrame, lv: pl.DataFrame, meta: pl.DataFrame) -> list:
    """Index, dollar and sector moves around each dated shock (entry: last close before it)."""
    tdays = idx.filter(C("tedpix").diff() != 0)["date"].sort().to_list()
    events = read_events()
    sec = (
        panel.filter(C("liquid"))
        .join(meta.select(G, "sector"), on=G)
        .select(G, "date", "close", "sector")
    )
    out = []
    for e in events:
        ed = date.fromisoformat(e["date"])
        before = [d for d in tdays if d < ed]
        after = [d for d in tdays if d >= ed]
        if not before or len(after) < 5:
            continue
        d0 = before[-1]
        if out and out[-1]["d0"] == str(d0):
            # several shocks inside one market closure share a single measured window
            out[-1]["title"] += " / " + e["title_fa"]
            continue
        row = {"date": e["date"], "kind": e["kind"], "title": e["title_fa"], "d0": str(d0),
               "first_trade": str(after[0]), "closed_days": (after[0] - d0).days}  # fmt: skip
        lv0 = lv.filter(C("date") == d0).row(0, named=True)
        for h in (5, 20, 60):
            if len(after) < h:
                continue
            dh = after[h - 1]
            lvh = lv.filter(C("date") == dh).row(0, named=True)
            row[f"tedpix_{h}"] = lvh["tedpix"] / lv0["tedpix"] - 1
            row[f"usd_{h}"] = lvh["usd_free"] / lv0["usd_free"] - 1 if lv0["usd_free"] else None
            if h == 20:
                a = sec.filter(C("date") == d0).select(G, "sector", c0=C("close"))
                b = sec.filter(C("date") == dh).select(G, c1=C("close"))
                m = a.join(b, on=G).with_columns(r=C("c1") / C("c0") - 1)
                g = m.group_by("sector").agg(C("r").median(), n=pl.len()).filter(C("n") >= 3)
                g = g.sort("r")
                row["worst"] = g.head(3).rows()
                row["best"] = g.tail(3).reverse().rows()
                row["breadth_up"] = float((m["r"] > 0).mean()) if m.height else None
        out.append(row)
    return out


def timing(grid: pl.DataFrame) -> dict:
    """Does the dollar lead the index, and is the index cheap in dollars before it rises?"""
    g = grid.filter(C("wk") >= date(2012, 1, 1)).drop_nulls(["r_tedpix", "r_usd_free"])
    m = g.with_columns(blk=pl.int_range(pl.len()) // 4).group_by("blk").agg(
        C("r_tedpix").sum(), C("r_usd_free").sum(), C("wk").first()
    ).sort("blk")  # fmt: skip
    m = m.with_columns(prev_usd=C("r_usd_free").shift(1)).drop_nulls()
    g = g.with_columns(
        idx_usd=(C("tedpix") / C("usd_free")).log(),
        fwd26=C("tedpix").log().shift(-26) - C("tedpix").log(),
    )
    g = g.with_columns(
        pctl=C("idx_usd").rolling_map(
            lambda s: float((s < s[-1]).mean()), window_size=156, min_samples=104
        )
    ).drop_nulls(["pctl", "fwd26"])
    q = g.with_columns(qt=(C("pctl") * 5).floor().clip(0, 4)).group_by("qt").agg(
        n=pl.len(), fwd26=C("fwd26").mean(), up=(C("fwd26") > 0).mean()
    ).sort("qt")  # fmt: skip
    return {
        "same_4w_corr": float(np.corrcoef(m["r_tedpix"], m["r_usd_free"])[0, 1]),
        "usd_leads_4w_corr": float(np.corrcoef(m["r_tedpix"], m["prev_usd"])[0, 1]),
        "months": m.height,
        "idx_in_usd_quintiles": q.to_dicts(),
    }


def fundamentals(panel: pl.DataFrame, lv: pl.DataFrame, names: dict[str, int], sens: dict) -> list:
    """Today's P/E, dividends read off the price gaps, and price in dollars against its history."""
    out = []
    for n, iid in names.items():
        raw = sql(
            "select date, close from prices_daily where close > 0 and not market_halt "
            f"and instrument_id={iid} order by date desc limit 1"
        )
        tags = sql(f"select tags from instruments where id={iid}")["tags"][0]
        t = json.loads(tags) if isinstance(tags, str) else tags
        adj = sql(
            "select date, close_before, price_after, adj_factor from price_adjustments "
            f"where instrument_id={iid} order by date desc"
        )
        # a gap under 20% is almost always a cash dividend; bigger ones are capital increases
        div = adj.filter(C("adj_factor") >= 0.8).with_columns(
            dps=C("close_before").cast(pl.Float64) - C("price_after").cast(pl.Float64),
            yld=1 - C("adj_factor"),
        )
        price = float(raw["close"][0])
        p = panel.filter(C(G) == iid).select("date", "close").join(lv, on="date", how="left")
        p = p.filter(C("date") >= date(2016, 1, 1)).with_columns(pu=C("close") / C("usd_free"))
        pu = p["pu"].drop_nulls()
        eps = t.get("eps")
        a = sens[n]["eras"].get("all", {})
        out.append(
            {
                "symbol": n,
                "sector": t.get("sector_title"),
                "price": price,
                "price_date": str(raw["date"][0]),
                "eps": eps,
                "pe": price / eps if eps and eps > 0 else None,
                "sector_pe": t.get("sector_pe"),
                "last_div": div.head(1).select("date", "dps", "yld").to_dicts(),
                "div_years": div.height,
                "usd_pctl_10y": float((pu < pu[-1]).mean()) if pu.len() else None,
                "usd_from_peak": float(pu[-1] / pu.max() - 1) if pu.len() else None,
                "beta_index": a.get("beta_index"),
                "beta_usd": a.get("beta_usd"),
                "corr_usd": a.get("corr4w", {}).get("usd_free"),
                "corr_copper_rial": a.get("corr4w", {}).get("copper_rial"),
                "corr_brent": a.get("corr4w", {}).get("brent_usd"),
            }
        )
    return out


def main() -> None:
    panel, idx, mac, meta = load()
    grid = weekly_grid(idx, mac)
    lv = daily_levels(idx, mac)
    names = {**FOCUS, **OTHERS}
    sw = stock_weekly(panel, list(names.values()), grid)
    sens = {n: sensitivities(sw, n, i) for n, i in names.items()}
    for n, s in sens.items():
        a = s["eras"].get("all", {})
        print(
            f"{n}: b_idx={a.get('beta_index', 0):+.2f} b_usd={a.get('beta_usd', 0):+.2f} "
            f"r2={a.get('r2', 0):.2f} "
            f"corr4w={ {k: round(v, 2) for k, v in a.get('corr4w', {}).items()} }"
        )
    zz = {n: legs(panel, lv, FOCUS[n], sens[n]) for n in FOCUS}
    for n, ls in zz.items():
        print(n, "legs", len(ls))
    cr = codal_reaction(panel, idx)
    print("codal", cr)
    sh = shocks(panel, idx, lv, meta)
    tm = timing(grid)
    fu = fundamentals(panel, lv, names, sens)
    for r in fu:
        print(r)
    print("timing", {k: v for k, v in tm.items() if k != "idx_in_usd_quintiles"})
    for r in tm["idx_in_usd_quintiles"]:
        print(r)
    with open(SP + "/sd.json", "w", encoding="utf-8") as fh:
        json.dump(
            {"sens": sens, "legs": zz, "codal": cr, "shocks": sh, "timing": tm, "fund": fu},
            fh, ensure_ascii=False, indent=1, default=str,
        )  # fmt: skip


if __name__ == "__main__":
    main()
