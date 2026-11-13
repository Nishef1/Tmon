export type Bar = { time: string; open: number; high: number; low: number; close: number };

/** Heikin-Ashi candles: each bar is smoothed with the previous one, so a trend shows as a run of
 *  same-coloured candles. The first bar opens at the midpoint of the real open and close. */
export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (const b of bars) {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const prev = out[out.length - 1];
    const open = prev ? (prev.open + prev.close) / 2 : (b.open + b.close) / 2;
    out.push({
      time: b.time,
      open,
      close,
      high: Math.max(b.high, open, close),
      low: Math.min(b.low, open, close),
    });
  }
  return out;
}

/** Simple moving average of the close; bars before the first full window are left out. */
export function sma(bars: Bar[], window: number): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= window) sum -= bars[i - window].close;
    if (i >= window - 1) out.push({ time: bars[i].time, value: sum / window });
  }
  return out;
}

export type Point = { time: string; price: number };
export type Measure = { pct: number; delta: number; bars: number; days: number };

/** The percent ruler: change from point ``a`` to point ``b``, with the candles and calendar days
 *  between them (``times`` = the chart's bar dates, ascending). */
export function measure(a: Point, b: Point, times: string[]): Measure | null {
  if (!(a.price > 0)) return null;
  const i = times.indexOf(a.time);
  const j = times.indexOf(b.time);
  const days = Math.round((Date.parse(b.time) - Date.parse(a.time)) / 86_400_000);
  return {
    pct: b.price / a.price - 1,
    delta: b.price - a.price,
    bars: i >= 0 && j >= 0 ? j - i : Math.abs(days),
    days,
  };
}

// ---- the chart terms of the glossary, with the same formulas as tmon.backtest.ta_signals ----

export type VBar = Bar & { volume: number | null };
export type Series = { time: string; value: number }[];
type Num = number | null;

/** Exponential mean that starts from the first value (polars ``adjust=False``) and is shown only
 *  after ``n`` values, like ``ewm_mean(min_samples=n)``. */
function ewm(xs: Num[], alpha: number, n: number): Num[] {
  const out: Num[] = [];
  let m: number | null = null;
  let seen = 0;
  for (const x of xs) {
    if (x == null || !Number.isFinite(x)) {
      out.push(m != null && seen >= n ? m : null);
      continue;
    }
    m = m == null ? x : m + alpha * (x - m);
    seen++;
    out.push(seen >= n ? m : null);
  }
  return out;
}

const emaOf = (xs: Num[], n: number) => ewm(xs, 2 / (n + 1), n);
const wilderOf = (xs: Num[], n: number) => ewm(xs, 1 / n, n);

function rolling(xs: Num[], n: number, fn: (w: number[]) => number): Num[] {
  return xs.map((_, i) => {
    if (i < n - 1) return null;
    const w = xs.slice(i - n + 1, i + 1);
    return w.every((x) => x != null) ? fn(w as number[]) : null;
  });
}

const sum = (w: number[]) => w.reduce((a, b) => a + b, 0);
const mean = (w: number[]) => sum(w) / w.length;
const sd = (w: number[]) => {
  const m = mean(w);
  return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / (w.length - 1));
};
const both = (a: Num, b: Num, f: (x: number, y: number) => number): Num =>
  a == null || b == null ? null : f(a, b);

function toSeries(bars: Bar[], xs: Num[]): Series {
  const out: Series = [];
  xs.forEach((v, i) => {
    if (v != null && Number.isFinite(v)) out.push({ time: bars[i].time, value: v });
  });
  return out;
}

export function ema(bars: Bar[], n: number): Series {
  return toSeries(
    bars,
    emaOf(
      bars.map((b) => b.close),
      n,
    ),
  );
}

/** 20-day mean with bands two (sample) standard deviations above and below. */
export function bollinger(bars: Bar[], n = 20, k = 2) {
  const c = bars.map((b) => b.close);
  const m = rolling(c, n, mean);
  const s = rolling(c, n, sd);
  return {
    mid: toSeries(bars, m),
    up: toSeries(
      bars,
      m.map((x, i) => both(x, s[i], (a, b) => a + k * b)),
    ),
    dn: toSeries(
      bars,
      m.map((x, i) => both(x, s[i], (a, b) => a - k * b)),
    ),
  };
}

const ratioIndex = (p: Num, q: Num) =>
  both(p, q, (a, b) => (b === 0 ? 100 : 100 - 100 / (1 + a / b)));

/** RSI on daily returns with Wilder smoothing (as the backend computes it). */
export function rsi(bars: Bar[], n = 14): Series {
  const r: Num[] = bars.map((b, i) => (i === 0 ? null : b.close / bars[i - 1].close - 1));
  const g = wilderOf(
    r.map((x) => (x == null ? null : Math.max(x, 0))),
    n,
  );
  const l = wilderOf(
    r.map((x) => (x == null ? null : Math.max(-x, 0))),
    n,
  );
  return toSeries(
    bars,
    g.map((x, i) => ratioIndex(x, l[i])),
  );
}

export function macd(bars: Bar[], fast = 12, slow = 26, signal = 9) {
  const c = bars.map((b) => b.close);
  const es = emaOf(c, slow);
  const line = emaOf(c, fast).map((x, i) => both(x, es[i], (a, b) => a - b));
  const sig = emaOf(line, signal);
  return {
    macd: toSeries(bars, line),
    signal: toSeries(bars, sig),
    hist: toSeries(
      bars,
      line.map((x, i) => both(x, sig[i], (a, b) => a - b)),
    ),
  };
}

const highest = (bars: Bar[], n: number) =>
  rolling(
    bars.map((b) => b.high),
    n,
    (w) => Math.max(...w),
  );
const lowest = (bars: Bar[], n: number) =>
  rolling(
    bars.map((b) => b.low),
    n,
    (w) => Math.min(...w),
  );

/** %K over 14 days and its 3-day mean %D. Williams %R is %K − 100. */
export function stochastic(bars: Bar[], n = 14, d = 3) {
  const hh = highest(bars, n);
  const ll = lowest(bars, n);
  const k = bars.map((b, i) =>
    both(hh[i], ll[i], (h, l) => (h === l ? NaN : (100 * (b.close - l)) / (h - l))),
  );
  const kk = k.map((x) => (x != null && Number.isFinite(x) ? x : null));
  return { k: toSeries(bars, kk), d: toSeries(bars, rolling(kk, d, mean)) };
}

function trueRange(bars: Bar[]): Num[] {
  return bars.map((b, i) => {
    // the first day has no previous close: its range alone (as polars max_horizontal does)
    if (i === 0) return b.high - b.low;
    const pc = bars[i - 1].close;
    return Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
  });
}

/** Average true range (Wilder, 14 days) as a share of the close. */
export function atrPct(bars: Bar[], n = 14): Series {
  const a = wilderOf(trueRange(bars), n);
  return toSeries(
    bars,
    a.map((x, i) => (x == null ? null : x / bars[i].close)),
  );
}

export function adx(bars: Bar[], n = 14) {
  const tr = wilderOf(trueRange(bars), n);
  const pdm: Num[] = [0];
  const mdm: Num[] = [0];
  for (let i = 1; i < bars.length; i++) {
    const up = bars[i].high - bars[i - 1].high;
    const dn = bars[i - 1].low - bars[i].low;
    pdm.push(up > dn && up > 0 ? up : 0);
    mdm.push(dn > up && dn > 0 ? dn : 0);
  }
  const di = (xs: Num[]) =>
    wilderOf(xs, n).map((x, i) => both(x, tr[i], (a, b) => (b === 0 ? NaN : (100 * a) / b)));
  const pdi = di(pdm);
  const mdi = di(mdm);
  const dx = pdi.map((p, i) =>
    both(p, mdi[i], (a, b) => (a + b === 0 ? NaN : (100 * Math.abs(a - b)) / (a + b))),
  );
  return {
    adx: toSeries(bars, wilderOf(dx, n)),
    pdi: toSeries(bars, pdi),
    mdi: toSeries(bars, mdi),
  };
}

/** On-balance volume: the day's volume added on an up close, taken off on a down close. */
export function obv(bars: VBar[]): Series {
  let s = 0;
  return bars.map((b, i) => {
    if (i > 0 && b.volume != null) s += Math.sign(b.close - bars[i - 1].close) * b.volume;
    return { time: b.time, value: s };
  });
}

/** Money flow index over 14 days (typical price × volume). */
export function mfi(bars: VBar[], n = 14): Series {
  const tp = bars.map((b) => (b.high + b.low + b.close) / 3);
  const flow = (sign: number): Num[] =>
    bars.map((b, i) => (i > 0 && sign * (tp[i] - tp[i - 1]) > 0 ? tp[i] * (b.volume ?? 0) : 0));
  const p = rolling(flow(1), n, sum);
  const q = rolling(flow(-1), n, sum);
  return toSeries(
    bars,
    p.map((x, i) => ratioIndex(x, q[i])),
  );
}

/** Volume-weighted typical price over the last ``n`` days. */
export function vwap(bars: VBar[], n = 20): Series {
  const tpv = rolling(
    bars.map((b) => ((b.high + b.low + b.close) / 3) * (b.volume ?? 0)),
    n,
    sum,
  );
  const v = rolling(
    bars.map((b) => b.volume ?? 0),
    n,
    sum,
  );
  return toSeries(
    bars,
    tpv.map((x, i) => both(x, v[i], (a, b) => (b === 0 ? NaN : a / b))),
  );
}

/** Ichimoku lines; the cloud spans are drawn 26 days after the day they were computed. */
export function ichimoku(bars: Bar[]) {
  const mid = (n: number) => {
    const ll = lowest(bars, n);
    return highest(bars, n).map((h, i) => both(h, ll[i], (a, b) => (a + b) / 2));
  };
  const tenkan = mid(9);
  const kijun = mid(26);
  const spanA = tenkan.map((x, i) => both(x, kijun[i], (a, b) => (a + b) / 2));
  const shift = (xs: Num[]) => bars.map((_, i) => (i >= 26 ? xs[i - 26] : null));
  return {
    tenkan: toSeries(bars, tenkan),
    kijun: toSeries(bars, kijun),
    spanA: toSeries(bars, shift(spanA)),
    spanB: toSeries(bars, shift(mid(52))),
  };
}

export type PriceLevel = { key: string; title: string; price: number };

/** Support and resistance the glossary names: the 20-day range before the last day, the
 *  previous day's pivot R1 and S1, and the 61.8% Fibonacci pullback of the last 120 days. */
export function levels(bars: Bar[]): PriceLevel[] {
  const n = bars.length;
  if (n < 21) return [];
  const prev = bars.slice(n - 21, n - 1);
  const y = bars[n - 2];
  const p = (y.high + y.low + y.close) / 3;
  const out: PriceLevel[] = [
    { key: "res20", title: "مقاومت ۲۰ روزه", price: Math.max(...prev.map((b) => b.high)) },
    { key: "sup20", title: "حمایت ۲۰ روزه", price: Math.min(...prev.map((b) => b.low)) },
    { key: "r1", title: "R1 پیوت", price: 2 * p - y.low },
    { key: "s1", title: "S1 پیوت", price: 2 * p - y.high },
  ];
  if (n >= 120) {
    const w = bars.slice(n - 120);
    const hi = Math.max(...w.map((b) => b.high));
    const lo = Math.min(...w.map((b) => b.low));
    out.push({ key: "fib618", title: "فیبو ۶۱٫۸٪", price: hi - 0.618 * (hi - lo) });
  }
  return out;
}

/** Trend regime of each day: up when the close is above a rising n-day average (higher than k
 *  days earlier), down when below a falling one, range otherwise. */
export function regime(bars: Bar[], n = 50, k = 10): { time: string; value: -1 | 0 | 1 }[] {
  const m = sma(bars, n);
  const off = bars.length - m.length;
  return m.map((p, i) => {
    const c = bars[i + off].close;
    const slope = i >= k ? p.value - m[i - k].value : 0;
    const value = c > p.value && slope > 0 ? 1 : c < p.value && slope < 0 ? -1 : 0;
    return { time: p.time, value };
  });
}

/** OBV with each day's volume capped at ``cap`` times its median of the last 60 days, so one
 *  block trade (معامله بلوکی) does not throw the line off for good. */
export function obvCapped(bars: VBar[], cap = 5, n = 60): Series {
  let s = 0;
  const vs: number[] = [];
  return bars.map((b, i) => {
    if (i > 0 && b.volume != null) {
      const w = vs.slice(-n).sort((x, y) => x - y);
      const med = w.length >= 10 ? w[w.length >> 1] : Infinity;
      s += Math.sign(b.close - bars[i - 1].close) * Math.min(b.volume, cap * med);
    }
    if (b.volume != null) vs.push(b.volume);
    return { time: b.time, value: s };
  });
}

export type Zone = {
  time: string;
  top: number;
  bot: number;
  side: "bull" | "bear";
  inverted: boolean;
};

/** Fair value gaps (three-candle imbalance of at least ``min`` of the price), the same rule as
 *  the tested signals: a bullish gap is a low above the high of two candles before. A close
 *  through the whole zone inverts it (iFVG: old support becomes resistance and the reverse).
 *  Returns the latest ``keep`` live zones of each side and the latest inverted one of each. */
export function fvgZones(bars: Bar[], min = 0.01, keep = 2): Zone[] {
  const all: Zone[] = [];
  for (let i = 2; i < bars.length; i++) {
    const b = bars[i];
    const a = bars[i - 2];
    if ((b.low - a.high) / b.close >= min)
      all.push({ time: b.time, top: b.low, bot: a.high, side: "bull", inverted: false });
    if ((a.low - b.high) / b.close >= min)
      all.push({ time: b.time, top: a.low, bot: b.high, side: "bear", inverted: false });
    for (const z of all) {
      if (z.inverted || z.time === b.time) continue;
      if (z.side === "bull" && b.close < z.bot) z.inverted = true;
      if (z.side === "bear" && b.close > z.top) z.inverted = true;
    }
  }
  const pick = (side: Zone["side"], inv: boolean, n: number) =>
    all.filter((z) => z.side === side && z.inverted === inv).slice(-n);
  return [
    ...pick("bull", false, keep),
    ...pick("bear", false, keep),
    ...pick("bull", true, 1),
    ...pick("bear", true, 1),
  ];
}

export type Pivot = { i: number; conf: number; price: number; kind: 1 | -1 };

/** Swing pivots of the closes, known only once the close has turned ``th`` from them (the
 *  same zigzag as the tested Elliott signals). */
export function zigzag(bars: Bar[], th = 0.1): Pivot[] {
  const out: Pivot[] = [];
  if (bars.length === 0) return out;
  let d = 0;
  let hiI = 0;
  let loI = 0;
  let hi = bars[0].close;
  let lo = hi;
  for (let i = 1; i < bars.length; i++) {
    const c = bars[i].close;
    if (d >= 0 && c > hi) [hiI, hi] = [i, c];
    if (d <= 0 && c < lo) [loI, lo] = [i, c];
    if (d >= 0 && c <= hi * (1 - th)) {
      out.push({ i: hiI, conf: i, price: hi, kind: 1 });
      [d, loI, lo] = [-1, i, c];
    } else if (d <= 0 && c >= lo * (1 + th)) {
      out.push({ i: loI, conf: i, price: lo, kind: -1 });
      [d, hiI, hi] = [1, i, c];
    }
  }
  return out;
}

const impulse = (q: Pivot[]) => {
  if (q.map((x) => x.kind).join() !== "-1,1,-1,1,-1,1") return false;
  const [a, b, c, d, e, f] = q.map((x) => x.price);
  return c > a && d > b && e > b && f > d && d - c >= Math.min(b - a, f - e);
};

/** Labels of the latest textbook up-impulse (waves 1 to 5 at its pivots, 0 at its start) and
 *  the A-B-C after it when one followed, on confirmed zigzag pivots only. */
export function elliottLabels(
  bars: Bar[],
  th = 0.1,
): { time: string; text: string; top: boolean }[] {
  const pv = zigzag(bars, th);
  for (let k = pv.length - 6; k >= 0; k--) {
    const q = pv.slice(k, k + 6);
    if (!impulse(q)) continue;
    const names = ["۰", "۱", "۲", "۳", "۴", "۵"];
    const out = q.map((p, j) => ({ time: bars[p.i].time, text: names[j], top: p.kind === 1 }));
    const r = pv.slice(k + 6, k + 9);
    if (r.length === 3 && r[1].price < q[5].price && r[2].price < r[0].price)
      r.forEach((p, j) => out.push({ time: bars[p.i].time, text: "ABC"[j], top: p.kind === 1 }));
    return out;
  }
  return [];
}
