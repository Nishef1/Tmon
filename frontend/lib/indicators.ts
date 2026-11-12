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
