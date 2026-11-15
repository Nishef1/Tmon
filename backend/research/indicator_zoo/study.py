"""Indicator zoo: every widely used TradingView indicator (built-ins and the popular community
"machine learning / AI" scripts), computed on adjusted TSETMC prices and judged one by one as a
predictor of the next 5, 20 and 60 trading days. Behind docs/reports/indicator-zoo-2026-11.md.

Run from backend/ with the live DB env; argv[1] = scratch dir (the panel parquet is cached
there and rebuilt whenever the newest price date changes).

Protocol (same as the earlier signal reports, so the numbers are comparable):
* universe: each day's 60% most traded symbols by 20-day median value; every 5th trading day;
* entry at the close of t+1; outcome = adjusted return t+1 -> t+1+h minus the universe mean;
* each indicator is a number per symbol-day; it is judged by the daily cross-sectional rank IC,
  the excess of its best decile and whether that holds in both halves of the history and most
  calendar years, and by its partial IC after removing what the four live ranking signals
  already know (does it *add* anything?).
Every indicator uses only data up to day t. The ML scripts (Lorentzian kNN and the like) only
learn from labels that were already known at t.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from scipy.signal import lfilter

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

SP = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
G = "instrument_id"
COST = 0.0175
H = (5, 20, 60)
STEP = 5
LIQUID = 0.6
A = np.ndarray

# ---------------------------------------------------------------- numpy helpers (one symbol)


def ema(x: A, n: int) -> A:
    a = 2 / (n + 1)
    out = np.full_like(x, np.nan)
    ok = ~np.isnan(x)
    if ok.sum() < n:
        return out
    i0 = np.argmax(ok)
    y = lfilter([a], [1, a - 1], np.nan_to_num(x[i0:]), zi=[x[i0] * (1 - a)])[0]
    out[i0:] = y
    out[: i0 + n - 1] = np.nan
    return out


def rma(x: A, n: int) -> A:  # Wilder's smoothing, as TradingView's ta.rma
    a = 1 / n
    out = np.full_like(x, np.nan)
    x0 = np.nan_to_num(x)
    if len(x) < n:
        return out
    seed = x0[:n].mean()
    y = lfilter([a], [1, a - 1], x0[n:], zi=[seed * (1 - a)])[0]
    out[n - 1] = seed
    out[n:] = y
    return out


def sma(x: A, n: int) -> A:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def rstd(x: A, n: int) -> A:
    return pd.Series(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def rmax(x: A, n: int) -> A:
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def rmin(x: A, n: int) -> A:
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


def rsum(x: A, n: int) -> A:
    return pd.Series(x).rolling(n, min_periods=n).sum().to_numpy()


def wma(x: A, n: int) -> A:
    w = np.arange(1, n + 1, dtype=float)
    return (
        pd.Series(x).rolling(n, min_periods=n).apply(lambda v: v @ w / w.sum(), raw=True).to_numpy()
    )


def wma_fast(x: A, n: int) -> A:
    # linear weights via two cumulative sums (same result as wma, O(N))
    s1 = pd.Series(x).rolling(n, min_periods=n).sum().to_numpy()
    idx = np.arange(len(x), dtype=float)
    s2 = pd.Series(x * idx).rolling(n, min_periods=n).sum().to_numpy()
    return (s2 - (idx - n) * s1) / (n * (n + 1) / 2)


def shift(x: A, k: int) -> A:
    out = np.full_like(x, np.nan)
    if k > 0:
        out[k:] = x[:-k]
    elif k < 0:
        out[:k] = x[-k:]
    else:
        out[:] = x
    return out


def linreg(x: A, n: int) -> tuple[A, A]:
    """Rolling least-squares slope (per bar, relative to price) and R² over n bars."""
    s = pd.Series(x)
    t = pd.Series(np.arange(len(x), dtype=float))
    cov = s.rolling(n, min_periods=n).cov(t)
    var_t = (n * n - 1) / 12
    slope = cov / var_t
    r = s.rolling(n, min_periods=n).corr(t)
    return (slope / s).to_numpy(), (r * r).to_numpy()


def rsi(c: A, n: int) -> A:
    d = np.diff(c, prepend=np.nan)
    up, dn = rma(np.where(d > 0, d, 0.0), n), rma(np.where(d < 0, -d, 0.0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def atr(h: A, l: A, c: A, n: int) -> A:
    pc = shift(c, 1)
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return rma(tr, n)


def supertrend(h: A, l: A, c: A, n: int = 10, f: float = 3.0) -> tuple[A, A]:
    """TradingView ta.supertrend: direction (+1 up) and distance of close from the line."""
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2
    ub, lb = hl2 + f * a, hl2 - f * a
    N = len(c)
    fu, fl, d = np.full(N, np.nan), np.full(N, np.nan), np.zeros(N)
    line = np.full(N, np.nan)
    for i in range(N):
        if np.isnan(a[i]):
            continue
        if i == 0 or np.isnan(fu[i - 1]):
            fu[i], fl[i], d[i] = ub[i], lb[i], 1
        else:
            fu[i] = ub[i] if ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1] else fu[i - 1]
            fl[i] = lb[i] if lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1] else fl[i - 1]
            d[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else d[i - 1]
        line[i] = fl[i] if d[i] > 0 else fu[i]
    d[np.isnan(line)] = np.nan
    return d, c / line - 1


def psar(h: A, l: A, start: float = 0.02, inc: float = 0.02, mx: float = 0.2) -> A:
    N = len(h)
    out = np.full(N, np.nan)
    if N < 3:
        return out
    up, af, ep, sar = True, start, h[0], l[0]
    for i in range(1, N):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], start
            elif h[i] > ep:
                ep, af = h[i], min(af + inc, mx)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], start
            elif l[i] < ep:
                ep, af = l[i], min(af + inc, mx)
        out[i] = sar
    return out


def kama(c: A, n: int = 10, fast: int = 2, slow: int = 30) -> A:
    ch = np.abs(c - shift(c, n))
    vol = rsum(np.abs(np.diff(c, prepend=np.nan)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        er = ch / vol
    sc = (er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2
    out = np.full_like(c, np.nan)
    k = np.nan
    for i in range(len(c)):
        if np.isnan(sc[i]):
            continue
        k = c[i] if np.isnan(k) else k + sc[i] * (c[i] - k)
        out[i] = k
    return out


def kalman(c: A, q: float = 1e-4, r: float = 1e-2) -> tuple[A, A]:
    """Local linear trend Kalman filter on log price: filtered level vs close, and the slope."""
    y = np.log(c)
    N = len(y)
    lev, slo = np.full(N, np.nan), np.full(N, np.nan)
    x = np.array([y[0], 0.0])
    P = np.eye(2)
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    Q = np.diag([q, q / 10])
    for i in range(N):
        x = F @ x
        P = F @ P @ F.T + Q
        s = P[0, 0] + r
        k = P[:, 0] / s
        x = x + k * (y[i] - x[0])
        P = P - np.outer(k, P[0, :])
        lev[i], slo[i] = x[0], x[1]
    lev[:20], slo[:20] = np.nan, np.nan
    return y - lev, slo


def nadaraya_watson(c: A, bw: float = 8.0, n: int = 25) -> tuple[A, A]:
    """LuxAlgo / jdehorty's non-repainting Nadaraya-Watson (rational-quadratic-like Gaussian
    kernel over the last n bars): close vs the estimate, and the estimate's 1-bar slope."""
    w = np.exp(-(np.arange(n) ** 2) / (2 * bw * bw))
    w = w / w.sum()
    est = np.convolve(c, w, mode="full")[: len(c)]
    est[: n - 1] = np.nan
    return c / est - 1, est / shift(est, 1) - 1


def hurst(c: A, n: int = 100) -> A:
    """Rolling Hurst exponent from the variance of 1-, 2-, 4- and 8-bar log returns."""
    y = np.log(c)
    lags = [1, 2, 4, 8]
    v = np.vstack([np.log(rstd(y - shift(y, k), n)) for k in lags])
    lx = np.log(lags)
    lx = lx - lx.mean()
    return (lx @ (v - v.mean(axis=0))) / (lx @ lx)


def kmeans1(x: A, k: int = 3, it: int = 10) -> A:
    c = np.quantile(x, [0.25, 0.5, 0.75])
    for _ in range(it):
        lab = np.argmin(np.abs(x[:, None] - c[None, :]), axis=1)
        c = np.array([x[lab == j].mean() if (lab == j).any() else c[j] for j in range(k)])
    return np.sort(c)


def ml_adaptive_supertrend(h: A, l: A, c: A, train: int = 100) -> A:
    """AlgoAlpha's 'Machine Learning Adaptive SuperTrend': k-means on the last `train` ATRs puts
    today's volatility in a low/mid/high cluster, the SuperTrend uses that cluster's ATR."""
    a = atr(h, l, c, 10)
    N = len(c)
    av = np.full(N, np.nan)
    for i in range(train + 10, N, 1):
        w = a[i - train + 1 : i + 1]
        if np.isnan(w).any():
            continue
        cen = kmeans1(w) if i % 20 == 0 or np.isnan(av[i - 1]) else cen  # noqa: F821
        av[i] = cen[np.argmin(np.abs(cen - a[i]))]
    hl2 = (h + l) / 2
    ub, lb = hl2 + 3 * av, hl2 - 3 * av
    d = np.zeros(N)
    fu, fl = np.full(N, np.nan), np.full(N, np.nan)
    for i in range(1, N):
        if np.isnan(av[i]):
            continue
        if np.isnan(fu[i - 1]):
            fu[i], fl[i], d[i] = ub[i], lb[i], 1
            continue
        fu[i] = ub[i] if ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1] else fu[i - 1]
        fl[i] = lb[i] if lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1] else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else d[i - 1]
    line = np.where(d > 0, fl, fu)
    return c / line - 1


def supertrend_ai(h: A, l: A, c: A) -> A:
    """LuxAlgo 'SuperTrend AI (Clustering)', simplified: SuperTrends with factors 1..5; each bar
    uses the factor whose past 1-bar signal performance (EMA, known at t) is best."""
    best_perf = None
    lines = []
    perfs = []
    dc = np.diff(c, prepend=np.nan)
    for f in (1.0, 2.0, 3.0, 4.0, 5.0):
        d, dist = supertrend(h, l, c, 10, f)
        p = ema(np.nan_to_num(shift(d, 1) * dc / c), 50)
        lines.append(dist)
        perfs.append(p)
    P = np.vstack(perfs)
    L = np.vstack(lines)
    ok = ~np.isnan(P).all(axis=0)
    best_perf = np.full(len(c), np.nan)
    pick = np.argmax(np.nan_to_num(P, nan=-9), axis=0)
    best_perf[ok] = L[pick, np.arange(len(c))][ok]
    return best_perf


def lorentzian(feats: A, c: A, eval_idx: A, k: int = 8, window: int = 2000, horizon: int = 4) -> A:
    """jdehorty's 'Machine Learning: Lorentzian Classification': approximate nearest neighbours
    in Lorentzian distance (sum log(1+|dx|)) over 5 oscillators, sampled every 4 bars from the
    symbol's last `window` bars; the label of a past bar is the sign of its next-`horizon`
    move, used only once that move had finished (bar index <= t - horizon). Output = sum of the
    k nearest labels (-k..k)."""
    N = len(c)
    out = np.full(N, np.nan)
    lab = np.sign(shift(c, -horizon) - c)
    good = ~np.isnan(feats).any(axis=1)
    for t in eval_idx:
        if not good[t]:
            continue
        lo = max(0, t - window)
        idx = np.arange(lo, t - horizon + 1)[::4]
        idx = idx[good[idx] & ~np.isnan(lab[idx])]
        if len(idx) < 50:
            continue
        dist = np.log1p(np.abs(feats[idx] - feats[t])).sum(axis=1)
        nn = np.argpartition(dist, k)[:k]
        out[t] = lab[idx[nn]].sum()
    return out


def knn_momentum(c: A, eval_idx: A, k: int = 20, window: int = 1000) -> A:
    """capissimo-style 'kNN-based strategy': neighbours of today's (ret5, ret20, rsi14) among
    past bars, prediction = mean of their realised next-20-bar return (only finished ones)."""
    r5 = c / shift(c, 5) - 1
    r20 = c / shift(c, 20) - 1
    rs = rsi(c, 14) / 100
    X = np.vstack([r5, r20, rs]).T
    fut = shift(c, -20) / c - 1
    out = np.full(len(c), np.nan)
    ok = ~np.isnan(X).any(axis=1)
    for t in eval_idx:
        if not ok[t]:
            continue
        idx = np.arange(max(0, t - window), t - 20)
        idx = idx[ok[idx] & ~np.isnan(fut[idx])]
        if len(idx) < 100:
            continue
        sd = X[idx].std(axis=0) + 1e-9
        dist = (((X[idx] - X[t]) / sd) ** 2).sum(axis=1)
        nn = np.argpartition(dist, k)[:k]
        out[t] = fut[idx[nn]].mean()
    return out


# ---------------------------------------------------------------- the indicators of one symbol

INFO: dict[str, tuple[str, str]] = {}  # key -> (family, Persian title)


def reg(key: str, fam: str, fa: str) -> str:
    INFO[key] = (fam, fa)
    return key


def symbol_features(g: pd.DataFrame, eval_idx: A) -> dict[str, A]:
    o, h, l, c = (g[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = g["volume"].to_numpy(float)
    val = g["value"].to_numpy(float)
    bvi, svi = g["buy_value_i"].to_numpy(float), g["sell_value_i"].to_numpy(float)
    bci, sci = g["buy_count_i"].to_numpy(float), g["sell_count_i"].to_numpy(float)
    pc = shift(c, 1)
    r1 = c / pc - 1
    f: dict[str, A] = {}
    E = np.errstate(divide="ignore", invalid="ignore")
    E.__enter__()

    # the four signals of the live ranking, as tmon.features computes them: one day's buy power,
    # std of 20 log returns, close over the 250-day high of highs (half the window required),
    # and the 12-1 momentum. (The live ranking also carries a stale value forward a few days.)
    pw = (bvi / bci) / (svi / sci)
    f["b_power"] = np.log(pw)
    f["b_rv20"] = -pd.Series(np.log(c / pc)).rolling(20, min_periods=20).std(ddof=1).to_numpy()
    f["b_dist52"] = c / pd.Series(h).rolling(250, min_periods=125).max().to_numpy() - 1
    f["b_mom121"] = shift(c, 21) / shift(c, 252) - 1

    # ---- moving averages (distance of close from the average)
    for n in (20, 50, 200):
        f[reg(f"sma{n}", "trend", f"فاصله از میانگین ساده {n}")] = c / sma(c, n) - 1
    f[reg("ema21", "trend", "فاصله از EMA ۲۱")] = c / ema(c, 21) - 1
    f[reg("wma20", "trend", "فاصله از WMA ۲۰")] = c / wma_fast(c, 20) - 1
    hma = wma_fast(2 * wma_fast(c, 10) - wma_fast(c, 20), int(np.sqrt(20)))
    f[reg("hma20_slope", "trend", "شیب میانگین هال (HMA) ۲۰")] = hma / shift(hma, 1) - 1
    e1 = ema(c, 20)
    e2 = ema(e1, 20)
    e3 = ema(e2, 20)
    f[reg("dema20", "trend", "فاصله از DEMA ۲۰")] = c / (2 * e1 - e2) - 1
    f[reg("tema20", "trend", "فاصله از TEMA ۲۰")] = c / (3 * e1 - 3 * e2 + e3) - 1
    k = kama(c)
    f[reg("kama", "trend", "فاصله از میانگین تطبیقی کافمن (KAMA)")] = c / k - 1
    f[reg("vwma20", "trend", "فاصله از میانگین وزنی حجم (VWMA)")] = (
        c / (rsum(c * v, 20) / rsum(v, 20)) - 1
    )
    m = 0.85 * 8
    s = 9 / 6
    wa = np.exp(-((np.arange(9) - m) ** 2) / (2 * s * s))
    alma = np.convolve(c, (wa / wa.sum())[::-1], mode="full")[: len(c)]
    alma[:8] = np.nan
    f[reg("alma9", "trend", "فاصله از ALMA ۹")] = c / alma - 1
    f[reg("ma_ribbon", "trend", "نظم نوار میانگین‌ها (۱۰>۲۰>۵۰>۱۰۰)")] = (
        (sma(c, 10) > sma(c, 20)).astype(float)
        + (sma(c, 20) > sma(c, 50))
        + (sma(c, 50) > sma(c, 100))
    ) * np.where(np.isnan(sma(c, 100)), np.nan, 1)

    # ---- trend strength / direction
    e12, e26 = ema(c, 12), ema(c, 26)
    macd = e12 - e26
    sig = ema(macd, 9)
    f[reg("macd", "trend", "MACD (نسبت به قیمت)")] = macd / c
    f[reg("macd_hist", "trend", "هیستوگرام MACD")] = (macd - sig) / c
    f[reg("ppo", "trend", "PPO")] = macd / e26
    t3 = ema(ema(ema(np.log(c), 15), 15), 15)
    f[reg("trix", "trend", "TRIX")] = t3 - shift(t3, 1)
    f[reg("dpo", "trend", "DPO (نوسان‌نمای بی‌روند)")] = c / shift(sma(c, 20), 11) - 1
    up_m = h - shift(h, 1)
    dn_m = shift(l, 1) - l
    pdm = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    ndm = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    a14 = atr(h, l, c, 14)
    pdi, ndi = 100 * rma(pdm, 14) / a14, 100 * rma(ndm, 14) / a14
    dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
    adx = rma(np.nan_to_num(dx), 14)
    adx[np.isnan(a14)] = np.nan
    f[reg("dmi", "trend", "DMI (+DI منهای −DI)")] = pdi - ndi
    f[reg("adx", "trend", "ADX (قدرت روند)")] = adx
    f[reg("adx_dir", "trend", "ADX × جهت")] = adx * np.sign(pdi - ndi)
    hh25 = pd.Series(h).rolling(26, min_periods=26).apply(np.argmax, raw=True).to_numpy()
    ll25 = pd.Series(l).rolling(26, min_periods=26).apply(np.argmin, raw=True).to_numpy()
    f[reg("aroon", "trend", "نوسان‌نمای آرون")] = (hh25 - ll25) / 25 * 100
    d, dist = supertrend(h, l, c, 10, 3)
    f[reg("supertrend_dir", "trend", "جهت سوپرترند (۱۰، ۳)")] = d
    f[reg("supertrend_dist", "trend", "فاصله از خط سوپرترند")] = dist
    f[reg("psar", "trend", "فاصله از Parabolic SAR")] = c / psar(h, l) - 1
    tk = (rmax(h, 9) + rmin(l, 9)) / 2
    kj = (rmax(h, 26) + rmin(l, 26)) / 2
    sa = shift((tk + kj) / 2, 26)
    sb = shift((rmax(h, 52) + rmin(l, 52)) / 2, 26)
    f[reg("ichi_tk", "trend", "ایچیموکو: تنکان نسبت به کیجون")] = tk / kj - 1
    f[reg("ichi_cloud", "trend", "ایچیموکو: فاصله از ابر")] = c / np.fmax(sa, sb) - 1
    f[reg("ichi_chikou", "trend", "ایچیموکو: چیکو (قیمت نسبت به ۲۶ روز پیش)")] = (
        c / shift(c, 26) - 1
    )
    trs = rsum(np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0), 14)
    vip = rsum(np.abs(h - shift(l, 1)), 14) / trs
    vim = rsum(np.abs(l - shift(h, 1)), 14) / trs
    f[reg("vortex", "trend", "شاخص گردابی (Vortex)")] = vip - vim
    tr1 = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    f[reg("chop", "trend", "شاخص بی‌جهتی (Choppiness)")] = (
        100 * np.log10(rsum(tr1, 14) / (rmax(h, 14) - rmin(l, 14))) / np.log10(14)
    )
    roc = lambda n: (c / shift(c, n) - 1) * 100  # noqa: E731
    f[reg("coppock", "trend", "منحنی کاپاک")] = wma_fast(roc(14) + roc(11), 10)
    kst = sma(roc(10), 10) + 2 * sma(roc(15), 10) + 3 * sma(roc(20), 10) + 4 * sma(roc(30), 15)
    f[reg("kst", "trend", "KST (دانستن قطعی)")] = kst - sma(kst, 9)
    rng = h - l
    e9 = ema(rng, 9)
    f[reg("mass", "volatility", "شاخص جرم (Mass Index)")] = rsum(e9 / ema(e9, 9), 25)
    sl, r2 = linreg(c, 20)
    f[reg("lr_slope", "trend", "شیب رگرسیون خطی ۲۰")] = sl
    f[reg("lr_r2", "trend", "R² رگرسیون خطی ۲۰ (تمیزی روند)")] = r2
    f[reg("lr_trend", "trend", "شیب × R² (روند تمیز)")] = sl * r2
    e13 = ema(c, 13)
    f[reg("elder_bull", "trend", "قدرت گاوها (Elder)")] = (h - e13) / c
    f[reg("elder_bear", "trend", "قدرت خرس‌ها (Elder)")] = (l - e13) / c
    mac = ema(c, 23) - ema(c, 50)
    st1 = (mac - rmin(mac, 10)) / (rmax(mac, 10) - rmin(mac, 10))
    st1 = ema(np.nan_to_num(st1, nan=0.5), 3)
    st2 = (st1 - rmin(st1, 10)) / (rmax(st1, 10) - rmin(st1, 10))
    f[reg("stc", "trend", "چرخهٔ روند شاف (STC)")] = ema(np.nan_to_num(st2, nan=0.5), 3) * np.where(
        np.isnan(mac), np.nan, 1
    )

    # ---- momentum / oscillators
    f[reg("rsi14", "momentum", "RSI ۱۴")] = rsi(c, 14)
    f[reg("rsi2", "momentum", "RSI ۲ (کانرز)")] = rsi(c, 2)
    hh, ll = rmax(h, 14), rmin(l, 14)
    stk = 100 * (c - ll) / (hh - ll)
    f[reg("stoch", "momentum", "استوکاستیک %K")] = sma(stk, 3)
    rs = rsi(c, 14)
    f[reg("stochrsi", "momentum", "استوکاستیک RSI")] = sma(
        100 * (rs - rmin(rs, 14)) / (rmax(rs, 14) - rmin(rs, 14)), 3
    )
    f[reg("willr", "momentum", "ویلیامز %R")] = -100 * (hh - c) / (hh - ll)
    tp = (h + l + c) / 3
    md = (
        pd.Series(tp)
        .rolling(20, min_periods=20)
        .apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        .to_numpy()
    )
    f[reg("cci", "momentum", "CCI ۲۰")] = (tp - sma(tp, 20)) / (0.015 * md)
    dc_ = np.diff(c, prepend=np.nan)
    su, sd_ = rsum(np.where(dc_ > 0, dc_, 0), 14), rsum(np.where(dc_ < 0, -dc_, 0), 14)
    f[reg("cmo", "momentum", "نوسان‌نمای چاند (CMO)")] = 100 * (su - sd_) / (su + sd_)
    for n in (10, 20, 60, 120):
        f[reg(f"roc{n}", "momentum", f"نرخ تغییر {n} روزه (ROC)")] = c / shift(c, n) - 1
    bp = c - np.fmin(l, pc)
    trr = np.fmax(h, pc) - np.fmin(l, pc)
    uo = (
        100
        * (
            4 * rsum(bp, 7) / rsum(trr, 7)
            + 2 * rsum(bp, 14) / rsum(trr, 14)
            + rsum(bp, 28) / rsum(trr, 28)
        )
        / 7
    )
    f[reg("uo", "momentum", "نوسان‌نمای نهایی (Ultimate)")] = uo
    mid = (h + l) / 2
    f[reg("ao", "momentum", "نوسان‌نمای شگفت‌انگیز (AO)")] = (sma(mid, 5) - sma(mid, 34)) / c
    x = 2 * ((mid - rmin(mid, 10)) / (rmax(mid, 10) - rmin(mid, 10)) - 0.5)
    x = np.clip(ema(np.nan_to_num(x), 5), -0.999, 0.999) * np.where(
        np.isnan(rmin(mid, 10)), np.nan, 1
    )
    f[reg("fisher", "momentum", "تبدیل فیشر")] = 0.5 * np.log((1 + x) / (1 - x))
    m1 = dc_
    tsi = 100 * ema(ema(m1, 25), 13) / ema(ema(np.abs(m1), 25), 13)
    f[reg("tsi", "momentum", "شاخص قدرت واقعی (TSI)")] = tsi
    streak = np.zeros(len(c))
    for i in range(1, len(c)):
        streak[i] = (
            (streak[i - 1] + 1 if streak[i - 1] > 0 else 1)
            if c[i] > c[i - 1]
            else ((streak[i - 1] - 1 if streak[i - 1] < 0 else -1) if c[i] < c[i - 1] else 0)
        )
    pr = (
        pd.Series(r1)
        .rolling(100, min_periods=100)
        .apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
        .to_numpy()
    )
    f[reg("crsi", "momentum", "RSI کانرز (ترکیبی)")] = (rsi(c, 3) + rsi(streak + 1000, 2) + pr) / 3
    rvi_n = sma((c - o), 10)
    rvi_d = sma((h - l), 10)
    f[reg("rvgi", "momentum", "شاخص نیروی نسبی (RVGI)")] = rvi_n / rvi_d
    hl = rmax(h, 10) - rmin(l, 10)
    rel = c - (rmax(h, 10) + rmin(l, 10)) / 2
    f[reg("smi", "momentum", "SMI (استوکاستیک ممنتوم)")] = (
        100 * ema(ema(rel, 3), 3) / (0.5 * ema(ema(hl, 3), 3))
    )
    f[reg("bop", "momentum", "توازن قدرت (BOP)")] = sma((c - o) / (h - l), 14)
    ap = tp
    esa = ema(ap, 10)
    dd = ema(np.abs(ap - esa), 10)
    ci = (ap - esa) / (0.015 * dd)
    wt1 = ema(ci, 21)
    f[reg("wavetrend", "momentum", "موج‌روند (WaveTrend)")] = wt1
    f[reg("wavetrend_x", "momentum", "موج‌روند: خط ۱ منهای ۲")] = wt1 - sma(wt1, 4)

    # ---- volatility
    f[reg("atrp", "volatility", "ATR درصدی")] = a14 / c
    m20, s20 = sma(c, 20), rstd(c, 20)
    f[reg("bb_pctb", "volatility", "بولینگر %B")] = (c - (m20 - 2 * s20)) / (4 * s20)
    f[reg("bb_width", "volatility", "پهنای بولینگر")] = 4 * s20 / m20
    kc_m, kc_a = ema(c, 20), atr(h, l, c, 10)
    f[reg("keltner", "volatility", "جای قیمت در کانال کلتنر")] = (c - kc_m) / (2 * kc_a)
    f[reg("squeeze", "volatility", "فشردگی (بولینگر داخل کلتنر)")] = (2 * s20 < 1.5 * kc_a).astype(
        float
    ) * np.where(np.isnan(s20 + kc_a), np.nan, 1)
    f[reg("squeeze_mom", "volatility", "ممنتوم فشردگی (LazyBear)")] = (
        c - ((rmax(h, 20) + rmin(l, 20)) / 2 + sma(c, 20)) / 2
    ) / c
    f[reg("donchian", "volatility", "جای قیمت در کانال دانچیان ۲۰")] = (c - rmin(l, 20)) / (
        rmax(h, 20) - rmin(l, 20)
    )
    f[reg("hv20", "volatility", "نوسان تاریخی ۲۰ روزه")] = rstd(np.log(c / pc), 20)
    erng = ema(h - l, 10)
    f[reg("chaikin_vol", "volatility", "نوسان چایکین")] = erng / shift(erng, 10) - 1
    ddp = 100 * (c / rmax(c, 14) - 1)
    f[reg("ulcer", "volatility", "شاخص زخم (Ulcer)")] = np.sqrt(sma(ddp * ddp, 14))

    # ---- volume / money flow
    obv = np.nancumsum(np.sign(np.nan_to_num(dc_)) * v)
    f[reg("obv_slope", "volume", "شیب OBV نسبت به حجم")] = (obv - shift(obv, 20)) / rsum(v, 20)
    clv = ((c - l) - (h - c)) / (h - l)
    clv = np.nan_to_num(clv)
    ad = np.cumsum(clv * v)
    f[reg("ad_slope", "volume", "شیب خط انباشت/توزیع (A/D)")] = (ad - shift(ad, 20)) / rsum(v, 20)
    f[reg("cmf", "volume", "جریان پول چایکین (CMF)")] = rsum(clv * v, 20) / rsum(v, 20)
    f[reg("chaikin_osc", "volume", "نوسان‌نمای چایکین")] = (ema(ad, 3) - ema(ad, 10)) / sma(v, 20)
    raw = tp * v
    pos = rsum(np.where(tp > shift(tp, 1), raw, 0), 14)
    neg = rsum(np.where(tp < shift(tp, 1), raw, 0), 14)
    f[reg("mfi", "volume", "شاخص جریان پول (MFI)")] = 100 - 100 / (1 + pos / neg)
    f[reg("force", "volume", "شاخص نیرو (Elder Force)")] = ema(r1 * v, 13) / sma(v, 20)
    emv = ((h + l) / 2 - (shift(h, 1) + shift(l, 1)) / 2) / (v / (h - l))
    f[reg("eom", "volume", "سهولت حرکت (EOM)")] = sma(emv, 14) / c * sma(v, 20)
    f[reg("vwap20", "volume", "فاصله از VWAP ۲۰ روزه")] = c / (rsum(tp * v, 20) / rsum(v, 20)) - 1
    pvt = np.nancumsum(np.nan_to_num(r1) * v)
    f[reg("pvt_slope", "volume", "شیب روند حجم-قیمت (PVT)")] = (pvt - shift(pvt, 20)) / rsum(v, 20)
    trend = np.sign(np.nan_to_num(tp - shift(tp, 1)))
    vf = v * trend
    f[reg("klinger", "volume", "نوسان‌نمای کلینگر")] = (ema(vf, 34) - ema(vf, 55)) / sma(v, 55)
    nvi = np.exp(np.nancumsum(np.where(v < shift(v, 1), np.log1p(np.nan_to_num(r1)), 0)))
    f[reg("nvi", "volume", "شاخص حجم منفی (NVI) نسبت به میانگین ۲۵۵")] = nvi / ema(nvi, 255) - 1
    pvi = np.exp(np.nancumsum(np.where(v > shift(v, 1), np.log1p(np.nan_to_num(r1)), 0)))
    f[reg("pvi", "volume", "شاخص حجم مثبت (PVI) نسبت به میانگین ۲۵۵")] = pvi / ema(pvi, 255) - 1
    f[reg("rvol", "volume", "حجم نسبی (امروز ÷ میانگین ۲۰)")] = v / shift(sma(v, 20), 1)
    f[reg("vol_osc", "volume", "نوسان‌نمای حجم (۵ و ۲۰)")] = sma(v, 5) / sma(v, 20) - 1

    # ---- Iran-specific money flow (the "smart money" filters of Persian channels)
    f[reg("net_real5", "flow", "خالص خرید حقیقی ۵ روزه")] = rsum(bvi - svi, 5) / rsum(val, 5)
    f[reg("power5", "flow", "قدرت خریدار حقیقی ۵ روزه")] = np.log(
        rsum(bvi, 5) / rsum(bci, 5)
    ) - np.log(rsum(svi, 5) / rsum(sci, 5))
    f[reg("pcbuy_rel", "flow", "سرانهٔ خرید نسبت به ۶۰ روز")] = np.log(
        (bvi / bci) / sma(bvi / bci, 60)
    )

    # ---- price structure
    f[reg("dist_52w_low", "structure", "فاصله از کف ۵۲ هفته")] = c / rmin(c, 250) - 1
    piv = shift(tp, 1)
    f[reg("pivot", "structure", "فاصله از پیوت کلاسیک دیروز")] = c / piv - 1
    f[reg("gap", "structure", "شکاف بازگشایی")] = o / pc - 1
    f[reg("candle_body", "structure", "بدنهٔ کندل (پایانی−باز ÷ دامنه)")] = (c - o) / (h - l)
    f[reg("upper_wick", "structure", "سایهٔ بالایی")] = (h - np.fmax(o, c)) / (h - l)
    f[reg("lower_wick", "structure", "سایهٔ پایینی")] = (np.fmin(o, c) - l) / (h - l)

    # ---- "machine learning / AI" scripts from the TradingView community
    nw_d, nw_s = nadaraya_watson(c)
    f[reg("nw_dist", "ml", "نادارایا-واتسون: فاصله از تخمین کرنل")] = nw_d
    f[reg("nw_slope", "ml", "نادارایا-واتسون: شیب تخمین کرنل")] = nw_s
    kd, ks = kalman(c)
    f[reg("kalman_dist", "ml", "فیلتر کالمن: فاصله از سطح")] = kd
    f[reg("kalman_slope", "ml", "فیلتر کالمن: شیب روند")] = ks
    f[reg("hurst", "ml", "نمای هرست (روندی بودن)")] = hurst(c)
    f[reg("ml_supertrend", "ml", "سوپرترند تطبیقی یادگیری ماشینی (k-means نوسان)")] = (
        ml_adaptive_supertrend(h, l, c)
    )
    f[reg("supertrend_ai", "ml", "سوپرترند AI (انتخاب بهترین ضریب)")] = supertrend_ai(h, l, c)
    lr = np.log(c / pc)
    ent = (
        pd.Series(np.sign(np.nan_to_num(lr)))
        .rolling(20, min_periods=20)
        .apply(
            lambda w: (
                -sum(
                    p * np.log(p)
                    for p in [(w > 0).mean(), (w < 0).mean(), (w == 0).mean()]
                    if p > 0
                )
            ),
            raw=True,
        )
        .to_numpy()
    )
    f[reg("entropy", "ml", "آنتروپی جهت ۲۰ روزه")] = ent
    wt_n = (wt1 - rmin(wt1, 50)) / (rmax(wt1, 50) - rmin(wt1, 50))
    cci_s = f["cci"]
    cci_n = (cci_s - rmin(cci_s, 50)) / (rmax(cci_s, 50) - rmin(cci_s, 50))
    adx_n = adx / 100
    X = np.vstack([rsi(c, 14) / 100, wt_n, cci_n, adx_n, rsi(c, 9) / 100]).T
    f[reg("lorentzian", "ml", "طبقه‌بندی لورنتزی (kNN، jdehorty)")] = lorentzian(X, c, eval_idx)
    f[reg("knn_mom", "ml", "kNN ممنتوم (همسایه‌های گذشتهٔ خود سهم)")] = knn_momentum(c, eval_idx)
    E.__exit__(None, None, None)
    return f


# ---------------------------------------------------------------- panel


def build_panel() -> pl.DataFrame:
    cache = SP / "zoo_panel.parquet"
    with session_scope() as s:
        prices, clients, _ = load_inputs(s)
    newest = str(prices["date"].max())
    meta = SP / "zoo_panel.json"
    if cache.exists() and meta.exists() and json.loads(meta.read_text())["newest"] == newest:
        return pl.read_parquet(cache)
    p = apply_adjustments(prices).filter(~pl.col("market_halt") & (pl.col("close") > 0))
    p = p.with_columns(
        open=pl.col("adj_open"),
        high=pl.col("adj_high"),
        low=pl.col("adj_low"),
        close=pl.col("adj_close"),
    ).sort(G, "date")
    cols = ["buy_value_i", "sell_value_i", "buy_count_i", "sell_count_i"]
    p = p.join(clients.select(G, "date", *cols), on=[G, "date"], how="left")
    p = p.select(G, "date", "open", "high", "low", "close", "volume", "value", *cols)
    days = p["date"].unique().sort()
    # ZOO_DAILY_FROM=YYYY-MM-DD: every trading day from then on (the adapt gate needs daily dates)
    daily_from = os.environ.get("ZOO_DAILY_FROM")
    picked = set(days.gather_every(STEP).to_list())
    if daily_from:
        picked |= {d for d in days.to_list() if d >= dt.date.fromisoformat(daily_from)}
    evald = pd.to_datetime(pd.Series(sorted(picked)))
    out = []
    t0 = time.time()
    groups = p.partition_by(G, as_dict=True)
    lim = int(os.environ.get("ZOO_LIMIT", "0"))
    if lim:
        groups = dict(list(groups.items())[:lim])
    for i, (key, g) in enumerate(groups.items()):
        gd = g.to_pandas()
        if len(gd) < 300:
            continue
        ev = np.flatnonzero(pd.to_datetime(gd["date"]).isin(evald).to_numpy())
        feats = symbol_features(gd, ev)
        c = gd["close"].to_numpy(float)
        res = {
            G: gd[G].to_numpy(),
            "date": gd["date"].to_numpy(),
            "close": c,
            "value": gd["value"].to_numpy(float),
        }
        for hh in H:
            res[f"fwd{hh}"] = shift(c, -(1 + hh)) / shift(c, -1) - 1
        res.update(feats)
        df = pd.DataFrame(res).iloc[ev]
        out.append(pl.from_pandas(df))
        if i % 100 == 0:
            print(f"  {i}/{len(groups)} symbols, {time.time() - t0:.0f}s", flush=True)
    panel = pl.concat(out, how="diagonal_relaxed").with_columns(pl.col("date").cast(pl.Date))
    # liquidity: 20-day median value is approximated on the sampled days by the value itself's
    # rank smoothing below; use the symbol's trailing median from the full series instead
    vm = (
        p.sort(G, "date")
        .with_columns(vmed20=pl.col("value").rolling_median(20, min_samples=10).over(G))
        .select(G, "date", "vmed20")
    )
    panel = panel.join(vm, on=[G, "date"], how="left")
    panel = panel.with_columns(
        liquid=(pl.col("vmed20").rank() / pl.len()).over("date") >= 1 - LIQUID,
        year=pl.col("date").dt.year(),
    )
    for hh in H:
        panel = panel.with_columns(
            (
                pl.col(f"fwd{hh}") - pl.col(f"fwd{hh}").filter(pl.col("liquid")).mean().over("date")
            ).alias(f"x{hh}")
        )
    panel = panel.filter(pl.col("liquid"))
    panel.write_parquet(cache)
    meta.write_text(json.dumps({"newest": newest, "info": INFO}, ensure_ascii=False))
    return panel


# ---------------------------------------------------------------- scoring


def _ranks(d: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    return d.with_columns(
        *[((pl.col(c).rank() - 0.5) / pl.col(c).count()).over("date").alias(f"r_{c}") for c in cols]
    )


BASE = ["b_power", "b_rv20", "b_dist52", "b_mom121"]


def score(panel: pl.DataFrame, info: dict[str, list[str]]) -> dict[str, dict]:
    keys = list(info)
    d = _ranks(panel, keys + BASE)
    for hh in H:
        d = d.with_columns(
            ((pl.col(f"x{hh}").rank() - 0.5) / pl.col(f"x{hh}").count())
            .over("date")
            .alias(f"ry{hh}")
        )
    d = d.with_columns(r_base=pl.mean_horizontal([f"r_{b}" for b in BASE]))
    split = d["date"].sort()[d.height // 2]
    out: dict[str, dict] = {}
    # partial IC needs per-day residuals: done in numpy per day
    dd = d.select(
        "date",
        *[f"r_{k}" for k in keys],
        *[f"r_{b}" for b in BASE],
        *[f"ry{hh}" for hh in H],
        *[f"x{hh}" for hh in H],
    )
    by_day = dd.partition_by("date", as_dict=True)
    partial: dict[tuple[str, int], list[tuple]] = {}
    for (day,), g in by_day.items():
        B = g.select([f"r_{b}" for b in BASE]).fill_null(0.5).to_numpy()
        B = np.column_stack([np.ones(len(B)), B])
        for hh in H:
            y = g[f"ry{hh}"].to_numpy()
            oky = ~np.isnan(y)
            if oky.sum() < 30:
                continue
            by, *_ = np.linalg.lstsq(B[oky], y[oky], rcond=None)
            ey = y - B @ by
            for k in keys:
                x = g[f"r_{k}"].to_numpy()
                ok = oky & ~np.isnan(x)
                if ok.sum() < 30:
                    continue
                bx, *_ = np.linalg.lstsq(B[ok], x[ok], rcond=None)
                ex = x[ok] - B[ok] @ bx
                cc = np.corrcoef(ex, ey[ok])[0, 1]
                partial.setdefault((k, hh), []).append((day, cc))
    for k in keys:
        rk = f"r_{k}"
        res: dict = {"family": info[k][0], "title": info[k][1], "h": {}}
        for hh in H:
            x, y = f"x{hh}", f"ry{hh}"
            g = (
                d.filter(pl.col(rk).is_not_null() & pl.col(x).is_not_null())
                .group_by("date")
                .agg(
                    ic=pl.corr(rk, y),
                    top=pl.col(x).filter(pl.col(rk) >= 0.9).mean(),
                    bot=pl.col(x).filter(pl.col(rk) <= 0.1).mean(),
                    n=pl.len(),
                    year=pl.col("year").first(),
                )
                .filter(pl.col("n") >= 30)
                .sort("date")
            )
            if g.height < 100:
                continue
            ov = max(1.0, hh / STEP)  # overlapping outcomes: fewer independent days
            ic = g["ic"]
            t = float(ic.mean() / ic.std() * np.sqrt(g.height / ov))
            a, b = g.filter(pl.col("date") < split), g.filter(pl.col("date") >= split)
            yrs = g.group_by("year").agg(pl.col("ic").mean())
            sign = np.sign(ic.mean())
            pr = partial.get((k, hh), [])
            pv = np.array([c for _, c in pr if not np.isnan(c)])
            pa = np.array([c for dte, c in pr if dte < split and not np.isnan(c)])
            pb = np.array([c for dte, c in pr if dte >= split and not np.isnan(c)])
            res["h"][hh] = {
                "ic": float(ic.mean()),
                "t": t,
                "ic_a": fl(a["ic"].mean()),
                "ic_b": fl(b["ic"].mean()),
                "years_same": float((np.sign(yrs["ic"].to_numpy()) == sign).mean()),
                "top": fl(g["top"].mean()),
                "bot": fl(g["bot"].mean()),
                "top_a": fl(a["top"].mean()),
                "top_b": fl(b["top"].mean()),
                "bot_a": fl(a["bot"].mean()),
                "bot_b": fl(b["bot"].mean()),
                "pic": float(pv.mean()) if len(pv) else None,
                "pic_t": float(pv.mean() / pv.std() * np.sqrt(len(pv) / ov))
                if len(pv) > 10
                else None,
                "pic_a": float(pa.mean()) if len(pa) else None,
                "pic_b": float(pb.mean()) if len(pb) else None,
                "days": g.height,
            }
        out[k] = res
    return {"split": str(split), "signals": out}


def fl(x: object) -> float:
    return float("nan") if x is None else float(x)  # type: ignore[arg-type]


def verdict(r: dict) -> dict:
    """A reading 'works' at horizon h when its IC has one sign in both halves and in >= 60% of
    years with |t| >= 3, and its better tail (top decile for a positive IC, bottom for a negative
    one, i.e. 'avoid') beats the round-trip cost in both halves. It 'adds' when the partial IC
    after the four live signals keeps the sign in both halves with |t| >= 2."""
    out = {}
    for hh, s in r["h"].items():
        sg = np.sign(s["ic"])
        stable = (
            np.sign(s["ic_a"]) == sg == np.sign(s["ic_b"])
            and s["years_same"] >= 0.6
            and abs(s["t"]) >= 3
        )
        tail_a, tail_b = (s["top_a"], s["top_b"]) if sg > 0 else (-s["bot_a"], -s["bot_b"])
        pays = tail_a > COST and tail_b > COST
        adds = (
            s["pic_t"] is not None
            and abs(s["pic_t"]) >= 2
            and np.sign(s["pic_a"]) == np.sign(s["pic_b"]) == np.sign(s["pic"])
        )
        out[hh] = {
            "stable": bool(stable),
            "pays": bool(pays),
            "adds": bool(adds),
            "dir": 0 if np.isnan(sg) else int(sg),
        }
    return out


def main() -> None:
    SP.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    panel = build_panel()
    info = json.loads((SP / "zoo_panel.json").read_text())["info"]
    print(f"panel {panel.shape} in {time.time() - t0:.0f}s; {len(info)} indicators", flush=True)
    res = score(panel, info)
    for k, r in res["signals"].items():
        r["verdict"] = verdict(r)
    (SP / "zoo_scores.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"scored in {time.time() - t0:.0f}s -> {SP / 'zoo_scores.json'}")


if __name__ == "__main__":
    main()
