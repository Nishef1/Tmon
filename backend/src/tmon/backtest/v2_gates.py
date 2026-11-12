"""R3 (ADR 0003 sections 6-7): simulate the v2 baseline portfolio and judge it against gates G1-G6.

Two candidates are judged against the official equal-weight index, after costs:

* ``selection``: the 20-name low-turnover book alone (fully invested), on the longest window the
  signals allow (12-1 month momentum needs 252 days of history);
* ``v2``: the book scaled by the R2 exposure layer, the rest in the treasury bill, on the window
  where every exposure input exists. This is the candidate the ADR wants published.

Nothing here is tuned. The configurations that were run are listed in the report; the number of
signal/horizon combinations looked at in R1 is stated next to the PBO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import polars as pl

from tmon.backtest.costs import rule_value_expr
from tmon.backtest.exposure_eval import _p, sell_queue_share, simulate
from tmon.backtest.metrics import portfolio_metrics
from tmon.backtest.portfolio_sim import BookParams, BookResult, simulate_book
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.engine.exposure import compute_exposure

R1_COMBINATIONS = 20  # signal x horizon pairs examined in R1 before this design was fixed


@dataclass
class Matrices:
    dates: list[Any]
    ret: np.ndarray
    rank: np.ndarray
    queue: np.ndarray
    median_value: np.ndarray
    sector: np.ndarray
    buy_cost: np.ndarray
    sell_cost: np.ndarray
    start: int


def _matrix(df: pl.DataFrame, col: str, days: pl.DataFrame, ids: pl.DataFrame) -> np.ndarray:
    j = df.join(days, on="date").join(ids, on="instrument_id")
    m = np.full((days.height, ids.height), np.nan)
    m[j["di"].to_numpy(), j["ii"].to_numpy()] = j[col].cast(pl.Float64).to_numpy()
    return m


def build_matrices(
    feats: pl.DataFrame,
    adj: pl.DataFrame,
    panel: pl.DataFrame,
    sectors: pl.DataFrame,
    rules: RuleBook,
    cfg: EngineConfig,
) -> Matrices:
    dates = adj["date"].unique().sort()
    days = pl.DataFrame({"date": dates, "di": np.arange(dates.len())})
    id_list = adj["instrument_id"].unique().sort()
    ids = pl.DataFrame({"instrument_id": id_list, "ii": np.arange(id_list.len())})
    a = _matrix(adj, "adj_close", days, ids)
    # carry the last price over days without a bar: such a day has a zero return, not a gap
    idx = np.where(~np.isnan(a), np.arange(a.shape[0])[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    seen = np.maximum.accumulate(~np.isnan(a), axis=0)
    ff = np.where(seen, np.take_along_axis(a, idx, axis=0), np.nan)
    ret = np.zeros_like(ff)
    ret[1:] = np.where(np.isfinite(ff[1:]) & np.isfinite(ff[:-1]), ff[1:] / ff[:-1] - 1.0, 0.0)
    q = feats.select(
        "instrument_id",
        "date",
        pl.when(pl.col("queue_state") == "buy_queue")
        .then(1.0)
        .when(pl.col("queue_state") == "sell_queue")
        .then(2.0)
        .otherwise(0.0)
        .alias("q"),
        "median_value_20",
    )
    queue = np.nan_to_num(_matrix(q, "q", days, ids))
    med = _matrix(q, "median_value_20", days, ids)
    rank = _matrix(panel, "r_composite", days, ids)
    sec_map = dict(
        zip(sectors["instrument_id"].to_list(), sectors["sector_code"].to_list(), strict=True)
    )
    sector = np.array([sec_map.get(i) or "?" for i in id_list.to_list()], dtype=object)
    slip = cfg.costs.slippage_fraction
    cost = days.select(
        (rule_value_expr(rules, "commission_buy", "rate", "date") + slip / 2).alias("b"),
        (
            rule_value_expr(rules, "commission_sell", "rate", "date")
            + rule_value_expr(rules, "sell_tax", "rate", "date")
            + slip / 2
        ).alias("s"),
    )
    if cost["b"].null_count() or cost["s"].null_count():
        raise ValueError("a trading day has no commission/tax rule in market_rules")
    ranked = np.isfinite(rank).sum(axis=1)
    ok = np.where(ranked >= cfg.v2.portfolio.min_cross_section)[0]
    if ok.size == 0:
        raise ValueError("no day has enough ranked symbols to start the book")
    return Matrices(
        dates=dates.to_list(),
        ret=ret,
        rank=rank,
        queue=queue,
        median_value=med,
        sector=sector,
        buy_cost=cost["b"].to_numpy(),
        sell_cost=cost["s"].to_numpy(),
        start=int(ok[0]),
    )


def restrict_top_liquid(m: Matrices, n: int, min_cross_section: int) -> Matrices:
    """Keep, on every day, only the ``n`` ranked names with the highest 20-day median traded
    value known at that day's close (point in time: no name is kept because of what happened
    later). Names outside the basket lose their rank, so the book cannot hold them."""
    from dataclasses import replace

    rank = m.rank.copy()
    for d in range(rank.shape[0]):
        cand = np.where(np.isfinite(rank[d]) & np.isfinite(m.median_value[d]))[0]
        if cand.size > n:
            drop = cand[np.argsort(m.median_value[d][cand])[: cand.size - n]]
            rank[d, drop] = np.nan
        rank[d, ~np.isfinite(m.median_value[d])] = np.nan
    ok = np.where(np.isfinite(rank).sum(axis=1) >= min_cross_section)[0]
    if ok.size == 0:
        raise ValueError("no day keeps enough names in the liquid basket")
    return replace(m, rank=rank, start=int(ok[0]))


def basket_index(m: Matrices, review_every: int) -> pl.DataFrame:
    """Costed equal-weight index of the basket itself: the benchmark a buyer limited to the same
    liquid names could have held without any selection.

    Weights are reset to equal over the names ranked at the previous close every
    ``review_every`` days (the book's own review rhythm and one-day order lag) and drift in
    between. Each reset pays the buy and sell cost of ``market_rules`` plus slippage on the amount
    traded. It does not model queues or the liquidity cap, so it is an idealisation in the
    benchmark's favour."""
    n_days, n = m.ret.shape
    member = np.isfinite(m.rank)
    w = np.zeros(n)
    rets = np.zeros(n_days)
    for t in range(max(m.start, 1), n_days):
        if w.any():
            grown = w * (1.0 + m.ret[t])
            f = float(grown.sum())
            rets[t] = f - 1.0
            w = grown / f
        if (t - m.start) % review_every == 0:
            cnt = int(member[t - 1].sum())
            if cnt:
                target = member[t - 1] / cnt
                delta = target - w
                cost = float(
                    np.clip(delta, 0, None).sum() * m.buy_cost[t]
                    + np.clip(-delta, 0, None).sum() * m.sell_cost[t]
                )
                rets[t] = (1.0 + rets[t]) * (1.0 - cost) - 1.0
                w = target
    lo = max(m.start, 1)
    return pl.DataFrame({"date": m.dates[lo:], "ret": rets[lo:]})


def run_book(
    m: Matrices,
    cfg: EngineConfig,
    *,
    n_names: int | None = None,
    entry_delay: int | None = None,
    cost_multiplier: float = 1.0,
) -> BookResult:
    pc, sz = cfg.v2.portfolio, cfg.sizing
    p = BookParams(
        n_names=n_names or pc.n_names,
        n_tranches=pc.n_tranches,
        review_every=pc.review_every_days,
        buy_top_frac=pc.buy_top_frac,
        hold_top_frac=pc.hold_top_frac,
        sector_cap_pct=sz.sector_cap_pct,
        name_cap_pct=sz.max_position_pct,
        liquidity_cap=sz.liquidity_cap_of_median_value,
        capital=cfg.backtest.initial_capital,
        entry_delay=entry_delay or pc.entry_delay_days,
        cost_multiplier=cost_multiplier,
    )
    return simulate_book(
        m.ret, m.rank, m.queue, m.median_value, m.sector, m.buy_cost, m.sell_cost, p, m.start
    )


# ---------------------------------------------------------------- candidates and statistics


@dataclass
class Candidate:
    daily: pl.DataFrame  # date, ret, buy (one-way turnover as a fraction of total capital)
    ew: pl.DataFrame  # date, ret of the equal-weight index on the same days


def _selection(m: Matrices, book: BookResult, ew_ret: pl.DataFrame, warm: int) -> Candidate:
    lo = m.start + warm
    d = pl.DataFrame(
        {"date": m.dates[lo:], "ret": book.ret[lo:], "buy": book.buy_frac[lo:]}
    ).filter(pl.col("date").is_in(ew_ret["date"].implode()))
    return Candidate(d, ew_ret.filter(pl.col("date").is_in(d["date"].implode())))


def _v2(
    m: Matrices,
    book: BookResult,
    exposure: pl.DataFrame,
    ew_ret: pl.DataFrame,
    rf_daily: pl.DataFrame,
    cost_per_side: float,
    warm: int,
) -> Candidate:
    lo = m.start + warm
    sleeve = pl.DataFrame({"date": m.dates[lo:], "ret": book.ret[lo:], "buy": book.buy_frac[lo:]})
    s = simulate(exposure, sleeve.select("date", "ret"), rf_daily, cost_per_side=cost_per_side)
    s = s.join(sleeve.select("date", "buy"), on="date").with_columns(
        (pl.col("buy") * pl.col("e")).alias("buy")
    )
    d = s.select("date", "ret", "buy")
    return Candidate(d, ew_ret.filter(pl.col("date").is_in(d["date"].implode())))


def monthly(daily: pl.DataFrame, min_days: int = 15) -> pl.DataFrame:
    return (
        daily.with_columns(
            pl.col("date").dt.year().alias("y"), pl.col("date").dt.month().alias("m")
        )
        .group_by("y", "m")
        .agg(
            ((1 + pl.col("ret")).product() - 1).alias("ret"),
            pl.len().alias("n"),
            pl.col("buy").sum().alias("buy")
            if "buy" in daily.columns
            else pl.lit(0.0).alias("buy"),
        )
        .filter(pl.col("n") >= min_days)
        .sort("y", "m")
    )


def yearly(daily: pl.DataFrame) -> dict[int, tuple[float, int]]:
    g = (
        daily.with_columns(pl.col("date").dt.year().alias("y"))
        .group_by("y")
        .agg(((1 + pl.col("ret")).product() - 1).alias("r"), pl.len().alias("n"))
        .sort("y")
    )
    return {int(y): (float(r), int(n)) for y, r, n in g.iter_rows()}


def pbo_cscv(perf: np.ndarray, splits: int) -> float | None:
    """Probability of backtest overfitting (Bailey et al.): ``perf`` is (periods, configs).
    ``None`` when there are fewer than two configs or fewer periods than splits."""
    t, n = perf.shape
    if n < 2 or t < splits or splits < 2 or splits % 2:
        return None
    blk = t // splits
    blocks = [np.arange(b * blk, (b + 1) * blk) for b in range(splits)]
    logits = []
    for comb in combinations(range(splits), splits // 2):
        is_i = np.concatenate([blocks[b] for b in comb])
        oos_i = np.concatenate([blocks[b] for b in range(splits) if b not in comb])
        best = int(np.argmax(perf[is_i].mean(0)))
        oos = perf[oos_i].mean(0)
        w = (np.sum(oos <= oos[best])) / (n + 1)
        logits.append(math.log(w / (1 - w)))
    return float(np.mean(np.array(logits) <= 0))


def _ann(daily: pl.DataFrame, rf: float | None) -> dict[str, Any]:
    return portfolio_metrics(daily.select("date", "ret"), risk_free_annual=rf)


@dataclass
class Judged:
    name: str
    first: Any
    last: Any
    days: int
    cand: dict[str, Any]
    ew: dict[str, Any]
    years: dict[int, tuple[float, float, int]]
    monthly_t: float | None
    monthly_n: int
    mean_turnover: float | None
    max_turnover: float | None
    robust: dict[str, dict[str, Any]]
    pbo: float | None
    n_configs: int
    gates: dict[str, dict[str, Any]]
    turnover_total_buys: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


def judge(
    name: str,
    base: Candidate,
    variants: dict[str, Candidate],
    cfg: EngineConfig,
    rf_annual: float | None,
) -> Judged:
    g = cfg.v2.gates
    cand, ew = _ann(base.daily, rf_annual), _ann(base.ew, rf_annual)
    cy, ey = yearly(base.daily), yearly(base.ew)
    years = {y: (cy[y][0], ey[y][0], cy[y][1]) for y in cy if y in ey}
    counted = [y for y, (_, _, n) in years.items() if n >= g.min_days_per_year]
    wins = sum(1 for y in counted if years[y][0] > years[y][1])
    share = wins / len(counted) if counted else None

    cm, em = monthly(base.daily), monthly(base.ew.with_columns(pl.lit(0.0).alias("buy")))
    mm = cm.join(em, on=["y", "m"], suffix="_ew")
    ex = (mm["ret"] - mm["ret_ew"]).to_numpy()
    t = (
        float(ex.mean() / (ex.std(ddof=1) / math.sqrt(ex.size)))
        if ex.size > 2 and ex.std(ddof=1) > 0
        else None
    )
    to = cm["buy"].to_numpy()
    mean_to, max_to = (float(to.mean()), float(to.max())) if to.size else (None, None)

    robust: dict[str, dict[str, Any]] = {}
    cols = {"base": ex}
    for vname, v in variants.items():
        vm = monthly(v.daily).join(em, on=["y", "m"], suffix="_ew")
        cols[vname] = (vm["ret"] - vm["ret_ew"]).to_numpy()
        vs = _ann(v.daily, rf_annual)
        robust[vname] = {
            "ann": vs.get("annualized_return"),
            "ann_ew": _ann(v.ew, rf_annual).get("annualized_return"),
            "mdd": vs.get("max_drawdown"),
            "mdd_ew": _ann(v.ew, rf_annual).get("max_drawdown"),
        }
    k = min(c.size for c in cols.values())
    pbo = pbo_cscv(np.column_stack([c[:k] for c in cols.values()]), g.pbo_splits)

    c_ann, e_ann = cand.get("annualized_return"), ew.get("annualized_return")
    gates: dict[str, dict[str, Any]] = {}

    def gate(key: str, ok: bool | None, text: str) -> None:
        gates[key] = {"passed": ok, "text": text}

    gate(
        "G1",
        None
        if c_ann is None or e_ann is None or share is None
        else bool(c_ann > e_ann and share >= g.min_year_win_share),
        f"بازده سالانه {_p(c_ann)} در برابر شاخص {_p(e_ann)}؛ سال‌های برنده "
        + (f"{wins} از {len(counted)}" if counted else "هیچ سال کاملی نیست")
        + f" (نیاز: ≥ {g.min_year_win_share * 100:.0f}٪ و سال با دست‌کم {g.min_days_per_year} روز)",
    )
    gate(
        "G2",
        None
        if cand.get("max_drawdown") is None
        else bool(cand["max_drawdown"] >= ew["max_drawdown"]),
        f"حداکثر افت {_p(cand.get('max_drawdown'))} در برابر شاخص {_p(ew.get('max_drawdown'))}",
    )
    gate(
        "G3",
        None if mean_to is None else bool(mean_to <= g.max_monthly_one_way_turnover),
        f"گردش یک‌طرفهٔ ماهانه: میانگین {_p(mean_to, 0)}، بیشینه {_p(max_to, 0)} (سقف {g.max_monthly_one_way_turnover * 100:.0f}٪)",
    )
    gate(
        "G4",
        None if t is None else bool(t >= g.min_monthly_excess_t),
        f"t مازاد ماهانه = {'—' if t is None else f'{t:.2f}'} روی {ex.size} ماه (نیاز ≥ {g.min_monthly_excess_t}). "
        f"پیکربندی‌های اجراشده: {len(cols)} (+ {R1_COMBINATIONS} ترکیب سیگنال-افق در R1)؛ PBO = "
        + ("محاسبه‌پذیر نیست" if pbo is None else f"{pbo * 100:.0f}٪"),
    )
    beats = [
        r["ann"] is not None and r["ann_ew"] is not None and r["ann"] > r["ann_ew"]
        for r in robust.values()
    ]
    gate(
        "G5",
        None if not robust else bool(all(beats)),
        "؛ ".join(f"{k_}: {_p(r['ann'])} (شاخص {_p(r['ann_ew'])})" for k_, r in robust.items()),
    )
    gate(
        "G6",
        bool(g.survivorship_resolved),
        "فهرست کامل نمادهای TSETMC (حذف‌شده‌ها هم) و تاریخچهٔ آن‌ها از ۱۳۸۰ بارگیری شده است؛ دروازه باز می‌ماند چون زیان روزهای پس از آخرین معامله (تعلیق و حذف) در سری نیست و کران بدبینانه‌ای ثبت نشده (OQ 65، گزارش داده-و-روش‌ها)"
        if not g.survivorship_resolved
        else "رفع‌شده",
    )
    return Judged(
        name=name,
        first=base.daily["date"].min(),
        last=base.daily["date"].max(),
        days=base.daily.height,
        cand=cand,
        ew=ew,
        years=years,
        monthly_t=t,
        monthly_n=int(ex.size),
        mean_turnover=mean_to,
        max_turnover=max_to,
        robust=robust,
        pbo=pbo,
        n_configs=len(cols),
        gates=gates,
    )


def evaluate(
    m: Matrices,
    ew_index: pl.DataFrame,
    rf_daily: pl.DataFrame,
    sell_share: pl.DataFrame,
    rf_annual: float | None,
    cfg: EngineConfig,
    benchmark: pl.DataFrame | None = None,
) -> tuple[list[Judged], dict[str, Any]]:
    """``benchmark`` (date, ret) replaces the official equal-weight index as the comparator of
    every gate; the exposure layer still reads the official index."""
    pc, g = cfg.v2.portfolio, cfg.v2.gates
    official = (
        ew_index.sort("date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"))
        .filter(pl.col("ret").is_not_null())
        .select("date", "ret")
    )
    ew_ret = official if benchmark is None else benchmark.select("date", "ret")
    warm = pc.warmup_days
    cost_side = cfg.costs.slippage_fraction / 2
    exposure = compute_exposure(ew_index, rf_daily, sell_share, cfg.v2.exposure)

    specs: dict[str, dict[str, Any]] = {
        "base": {},
        f"names {pc.n_names + g.robust_names_delta}": {
            "n_names": pc.n_names + g.robust_names_delta
        },
        f"names {pc.n_names - g.robust_names_delta}": {
            "n_names": pc.n_names - g.robust_names_delta
        },
        f"entry +{g.robust_entry_delay_days - 1} day": {"entry_delay": g.robust_entry_delay_days},
        f"cost x{g.robust_cost_multiplier}": {"cost_multiplier": g.robust_cost_multiplier},
    }
    books = {k: run_book(m, cfg, **v) for k, v in specs.items()}
    out: list[Judged] = []
    info = {
        "start": m.dates[m.start],
        "n_buys": books["base"].n_buys,
        "cancelled_buys": books["base"].n_cancelled_buys,
        "postponed_sells": books["base"].n_postponed_sells,
        "avg_held": float(books["base"].n_held[m.start + warm :].mean()),
    }
    member = np.isfinite(m.rank[:-1])  # in the universe at the close before the return day
    n_mem = np.maximum(member.sum(1), 1)
    uni = np.zeros(len(m.dates))
    uni[1:] = np.where(member, m.ret[1:], 0.0).sum(1) / n_mem
    uni_ret = pl.DataFrame({"date": m.dates, "ret": uni})
    sel = {k: _selection(m, b, ew_ret, warm) for k, b in books.items()}
    out.append(
        judge(
            "selection", sel["base"], {k: v for k, v in sel.items() if k != "base"}, cfg, rf_annual
        )
    )
    v2c = {k: _v2(m, b, exposure, ew_ret, rf_daily, cost_side, warm) for k, b in books.items()}
    out.append(
        judge("v2", v2c["base"], {k: v for k, v in v2c.items() if k != "base"}, cfg, rf_annual)
    )
    for j in out:
        u = uni_ret.filter((pl.col("date") >= j.first) & (pl.col("date") <= j.last))
        j.extra["ew_universe"] = _ann(u, rf_annual)
        if benchmark is not None:
            o = official.filter((pl.col("date") >= j.first) & (pl.col("date") <= j.last))
            j.extra["official"] = _ann(o, rf_annual)
    info["benchmark_label"] = "شاخص سبد" if benchmark is not None else "شاخص هم‌وزن"
    return out, info


def verdict(j: Judged) -> str:
    vals = [g["passed"] for g in j.gates.values()]
    if all(v is True for v in vals):
        return "همهٔ دروازه‌ها گذشت"
    failed = [k for k, g in j.gates.items() if g["passed"] is False]
    unknown = [k for k, g in j.gates.items() if g["passed"] is None]
    return (
        "رد شد: "
        + "، ".join(failed)
        + (f"؛ قابل ارزیابی نیست: {'، '.join(unknown)}" if unknown else "")
    )


def render_markdown(js: list[Judged], info: dict[str, Any], cfg: EngineConfig) -> str:
    pc = cfg.v2.portfolio
    names = {
        "selection": "انتخاب سهام تنها (کاملاً سرمایه‌گذاری‌شده)",
        "v2": "v2 کامل (انتخاب + لایهٔ مواجهه + اخزا)",
    }
    out = [
        "# R3 — سبد مبنای v2 و دروازهٔ G1 تا G6 (دادهٔ واقعی)",
        "",
        f"- سبد: {pc.n_names} نماد هم‌وزن در {pc.n_tranches} قسط، بازبینی هر {pc.review_every_days} روز، خرید از "
        f"{pc.buy_top_frac * 100:.0f}٪ بالا، نگهداری تا خروج از {pc.hold_top_frac * 100:.0f}٪ بالا، سقف صنعت "
        f"{cfg.sizing.sector_cap_pct * 100:.0f}٪، سقف نقدشوندگی {cfg.sizing.liquidity_cap_of_median_value * 100:.0f}٪ "
        "میانهٔ ارزش ۲۰ روزه. سفارش پایانی `t` در پایانی `t+1` اجرا می‌شود؛ خرید در صف خرید لغو و فروش در صف فروش "
        "به روز بعد موکول می‌شود.",
        f"- شروع سبد: {info['start']}؛ {pc.warmup_days} روز اول (ساخت سبد) از هر آماری بیرون است. "
        f"خریدهای اجراشده {info['n_buys']}، خریدهای لغوشده به‌دلیل صف خرید {info['cancelled_buys']}، "
        f"فروش‌های موکول‌شده به‌دلیل صف فروش {info['postponed_sells']}؛ متوسط نمادهای نگه‌داشته {info['avg_held']:.1f}.",
        "- هزینه: کارمزد و مالیات از `market_rules` + لغزش پیکربندی، هر طرف. هیچ پارامتری روی این داده تنظیم نشد.",
        "- معیار مقایسه: شاخص هم‌وزن رسمی (ممکن است سود نقدی را شامل نشود، OQ 89)."
        if info.get("benchmark_label", "شاخص هم‌وزن") == "شاخص هم‌وزن"
        else f"- معیار مقایسه: شاخص همین سبد پرنقدشونده، هم‌وزن با بازتوازن هر {pc.review_every_days} روز و هزینهٔ "
        "کارمزد، مالیات و لغزش؛ صف و سقف نقدشوندگی را مدل نمی‌کند (به نفع معیار). شاخص رسمی فقط مرجع است.",
        "",
    ]
    for j in js:
        c, e = j.cand, j.ew
        out += [
            f"## {names[j.name]}",
            "",
            f"بازه {j.first} تا {j.last}؛ {j.days} روز. **حکم: {verdict(j)}**",
            "",
            "| | بازده کل | سالانه | نوسان | حداکثر افت | شارپ |",
            "|---|---|---|---|---|---|",
            f"| سبد | {_p(c.get('total_return'))} | {_p(c.get('annualized_return'))} | {_p(c.get('annualized_volatility'))} | {_p(c.get('max_drawdown'))} | {c.get('sharpe') or float('nan'):.2f} |",
            f"| {info.get('benchmark_label', 'شاخص هم‌وزن')} | {_p(e.get('total_return'))} | {_p(e.get('annualized_return'))} | {_p(e.get('annualized_volatility'))} | {_p(e.get('max_drawdown'))} | {e.get('sharpe') or float('nan'):.2f} |",
            *(
                [
                    f"| شاخص هم‌وزن رسمی (مرجع) | {_p(j.extra['official'].get('total_return'))} | {_p(j.extra['official'].get('annualized_return'))} | {_p(j.extra['official'].get('annualized_volatility'))} | {_p(j.extra['official'].get('max_drawdown'))} | {j.extra['official'].get('sharpe') or float('nan'):.2f} |"
                ]
                if "official" in j.extra
                else []
            ),
            f"| هم‌وزن جهان خودمان (تعدیل‌شده، همان نمادها) | {_p(j.extra['ew_universe'].get('total_return'))} | {_p(j.extra['ew_universe'].get('annualized_return'))} | {_p(j.extra['ew_universe'].get('annualized_volatility'))} | {_p(j.extra['ew_universe'].get('max_drawdown'))} | {j.extra['ew_universe'].get('sharpe') or float('nan'):.2f} |",
            "",
            "| دروازه | نتیجه | عدد |",
            "|---|---|---|",
        ]
        for k, g in j.gates.items():
            mark = {True: "✔ گذشت", False: "✘ رد", None: "؟ قابل ارزیابی نیست"}[g["passed"]]
            out.append(f"| {k} | {mark} | {g['text']} |")
        out += ["", "| سال | سبد | شاخص | روز |", "|---|---|---|---|"]
        for y, (a, b, n) in j.years.items():
            out.append(f"| {y} | {_p(a)} | {_p(b)} | {n} |")
        out.append("")
    out += [
        "## محدودیت‌ها",
        "",
        "- بازهٔ v2 کامل کوتاه است (اخزا فقط از آذر ۱۴۰۲)؛ بخش سالانهٔ G1 و t ماهانهٔ G4 روی چند ده ماه است و قدرت آماری کمی دارد.",
        "- سوگیری بقا (G6): نمادهای حذف‌شده اکنون در جهان هستند، اما زیان پس از آخرین معامله در سری نیست؛ اعداد بالا در همین حد خوش‌بینانه‌اند.",
        "- PBO روی پیکربندی‌های استحکام (نه یک جست‌وجوی واقعی) ساخته شده و فقط نشانه است.",
        "- «رد شد» به معنای اشتباه بودن طراحی نیست؛ یعنی شاهد کافی برای انتشار نداریم و سایت «پیشنهادی نیست» می‌ماند.",
        "",
        "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="tmon-v2-gates")
    ap.add_argument("--md", type=Path)
    ap.add_argument(
        "--survivors-only",
        action="store_true",
        help="drop instruments found by the R0 search crawl (reproduces the pre-R0 universe)",
    )
    ap.add_argument(
        "--vs-official",
        action="store_true",
        help="with --top-liquid: judge against the official index instead of the basket's own",
    )
    ap.add_argument(
        "--top-liquid",
        type=int,
        default=None,
        help="trade only the N names with the highest 20-day median value on each day",
    )
    args = ap.parse_args(argv)

    from tmon.backtest.runner import mean_risk_free, risk_free_daily
    from tmon.backtest.signal_decay import adjusted_close, build_panel
    from tmon.core.db import session_scope
    from tmon.features.builder import build_features
    from tmon.features.store import load_benchmark_inputs, load_inputs

    cfg = get_engine_config()
    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        if args.survivors_only:
            from sqlalchemy import select

            from tmon.storage.models import Instrument

            found = {
                i
                for i, t in session.execute(select(Instrument.id, Instrument.tags))
                if (t or {}).get("discovered_by") == "search"
            }
            prices = prices.filter(~pl.col("instrument_id").is_in(found))
            clients = clients.filter(~pl.col("instrument_id").is_in(found))
            sectors = sectors.filter(~pl.col("instrument_id").is_in(found))
        rules = RuleBook.from_session(session)
        index_daily, rf = load_benchmark_inputs(session)
    code = cfg.benchmarks.indices["equal_weight"]
    ew = index_daily.filter(pl.col("index_code") == code).select("date", "close").sort("date")
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    panel = build_panel(feats, adj, cfg, horizons=(20,))
    m = build_matrices(feats, adj, panel, sectors, rules, cfg)
    if args.top_liquid:
        m = restrict_top_liquid(m, args.top_liquid, cfg.v2.portfolio.min_cross_section)
    rf_daily = risk_free_daily(rf, ew.filter(pl.col("date") >= rf["date"].min())["date"])
    rf_annual = mean_risk_free(rf, rf["date"].min(), rf["date"].max(), cfg)
    bench = (
        basket_index(m, cfg.v2.portfolio.review_every_days)
        if args.top_liquid and not args.vs_official
        else None
    )
    js, info = evaluate(m, ew, rf_daily, sell_queue_share(feats), rf_annual, cfg, bench)
    md = render_markdown(js, info, cfg)
    if args.top_liquid:
        note = (
            f"> **جهان محدود به {args.top_liquid} نماد پرنقدشونده:** هر روز فقط نمادهای با بیشترین "
            "میانهٔ ارزش معاملهٔ ۲۰ روزه (که همان روز شناخته است) اجازهٔ ورود به سبد دارند."
        )
        head, _, rest = md.partition("\n\n")
        md = f"{head}\n\n{note}\n\n{rest}"
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
