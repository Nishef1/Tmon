"""Naive, loop-based reference implementations used only to cross-check the vectorised
indicators. Deliberately written for clarity, not speed. Inputs are plain Python lists for a
single instrument; outputs use ``None`` for undefined warm-up values."""

from __future__ import annotations

import math


def sma(x: list[float], n: int) -> list[float | None]:
    return [None if i + 1 < n else sum(x[i + 1 - n : i + 1]) / n for i in range(len(x))]


def ema(x: list[float], n: int) -> list[float | None]:
    """Recursive EMA seeded with the first value; first ``n - 1`` outputs are warm-up."""
    a = 2 / (n + 1)
    out: list[float | None] = []
    prev = x[0]
    for i, v in enumerate(x):
        prev = v if i == 0 else a * v + (1 - a) * prev
        out.append(prev if i + 1 >= n else None)
    return out


def wilder_avg(x: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    valid = [i for i, v in enumerate(x) if v is not None]
    if len(valid) < n:
        return out
    seed_idx = valid[n - 1]
    out[seed_idx] = sum(x[i] for i in valid[:n]) / n  # type: ignore[misc]
    for i in range(seed_idx + 1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n  # type: ignore[operator]
    return out


def rsi(close: list[float], n: int = 14) -> list[float | None]:
    gains: list[float | None] = [None]
    losses: list[float | None] = [None]
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = wilder_avg(gains, n), wilder_avg(losses, n)
    out: list[float | None] = []
    for g, lo in zip(ag, al, strict=True):
        if g is None or lo is None:
            out.append(None)
        elif g + lo == 0:
            out.append(50.0)
        else:
            out.append(100 * g / (g + lo))
    return out


def true_range(h: list[float], lo: list[float], c: list[float]) -> list[float]:
    out = [h[0] - lo[0]]
    for i in range(1, len(c)):
        out.append(max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
    return out


def atr(h: list[float], lo: list[float], c: list[float], n: int = 14) -> list[float | None]:
    return wilder_avg(list(true_range(h, lo, c)), n)


def adx(
    h: list[float], lo: list[float], c: list[float], n: int = 14
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    m = len(c)
    pdm: list[float | None] = [None]
    mdm: list[float | None] = [None]
    tr: list[float | None] = [None]
    t = true_range(h, lo, c)
    for i in range(1, m):
        up, down = h[i] - h[i - 1], lo[i - 1] - lo[i]
        pdm.append(up if (up > down and up > 0) else 0.0)
        mdm.append(down if (down > up and down > 0) else 0.0)
        tr.append(t[i])
    spdm, smdm, st = wilder_avg(pdm, n), wilder_avg(mdm, n), wilder_avg(tr, n)
    pdi: list[float | None] = []
    mdi: list[float | None] = []
    dx: list[float | None] = []
    for a, b, s in zip(spdm, smdm, st, strict=True):
        if a is None or b is None or s is None or s == 0:
            pdi.append(None)
            mdi.append(None)
            dx.append(None)
            continue
        p, q = 100 * a / s, 100 * b / s
        pdi.append(p)
        mdi.append(q)
        dx.append(100 * abs(p - q) / (p + q) if p + q else None)
    return wilder_avg(dx, n), pdi, mdi


def stochastic(
    h: list[float], lo: list[float], c: list[float], n: int = 14, smooth: int = 3
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    k: list[float | None] = []
    wr: list[float | None] = []
    for i in range(len(c)):
        if i + 1 < n:
            k.append(None)
            wr.append(None)
            continue
        hh, ll = max(h[i + 1 - n : i + 1]), min(lo[i + 1 - n : i + 1])
        k.append(100 * (c[i] - ll) / (hh - ll) if hh != ll else None)
        wr.append(-100 * (hh - c[i]) / (hh - ll) if hh != ll else None)
    d: list[float | None] = []
    for i in range(len(k)):
        w = k[max(0, i + 1 - smooth) : i + 1]
        d.append(sum(w) / smooth if len(w) == smooth and None not in w else None)  # type: ignore[arg-type]
    return k, d, wr


def bollinger(
    c: list[float], n: int = 20, k: float = 2.0
) -> tuple[list[float | None], list[float | None]]:
    pct_b: list[float | None] = []
    bw: list[float | None] = []
    for i in range(len(c)):
        if i + 1 < n:
            pct_b.append(None)
            bw.append(None)
            continue
        w = c[i + 1 - n : i + 1]
        mid = sum(w) / n
        sd = math.sqrt(sum((v - mid) ** 2 for v in w) / n)
        lo_b, up_b = mid - k * sd, mid + k * sd
        pct_b.append((c[i] - lo_b) / (up_b - lo_b) if up_b != lo_b else None)
        bw.append((up_b - lo_b) / mid)
    return pct_b, bw


def obv_change(c: list[float], v: list[float], w: int = 20) -> list[float | None]:
    obv = [0.0]
    for i in range(1, len(c)):
        s = (c[i] > c[i - 1]) - (c[i] < c[i - 1])
        obv.append(obv[-1] + s * v[i])
    out: list[float | None] = []
    for i in range(len(c)):
        out.append(None if i < w else (obv[i] - obv[i - w]) / sum(v[i + 1 - w : i + 1]))
    return out


def mfi(
    h: list[float], lo: list[float], c: list[float], v: list[float], n: int = 14
) -> list[float | None]:
    tp = [(h[i] + lo[i] + c[i]) / 3 for i in range(len(c))]
    out: list[float | None] = [None] * len(c)
    for i in range(n, len(c)):
        pos = neg = 0.0
        for j in range(i + 1 - n, i + 1):
            flow = tp[j] * v[j]
            if tp[j] > tp[j - 1]:
                pos += flow
            elif tp[j] < tp[j - 1]:
                neg += flow
        out[i] = 100 * pos / (pos + neg) if pos + neg > 0 else 50.0
    return out


def ichimoku_cloud_top_dist(h: list[float], lo: list[float], c: list[float]) -> list[float | None]:
    def mid(i: int, n: int) -> float | None:
        return None if i + 1 < n else (max(h[i + 1 - n : i + 1]) + min(lo[i + 1 - n : i + 1])) / 2

    out: list[float | None] = []
    for i in range(len(c)):
        j = i - 26
        if j < 0:
            out.append(None)
            continue
        t, k, sb = mid(j, 9), mid(j, 26), mid(j, 52)
        if t is None or k is None or sb is None:
            out.append(None)
            continue
        out.append(c[i] / max((t + k) / 2, sb) - 1)
    return out
