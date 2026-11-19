import type { Candle } from "@/lib/api";

/** One candle per trading day, Persian week (Saturday to Wednesday), Persian month, season
 *  (three months) or half year. */
export type Tf = "1d" | "1w" | "1m" | "3m" | "6m";

export const TFS: [Tf, string][] = [
  ["1d", "روزانه"],
  ["1w", "هفتگی"],
  ["1m", "ماهانه"],
  ["3m", "۳ ماهه"],
  ["6m", "۶ ماهه"],
];

/** Trading days in one candle, roughly: a span of n trading days is about n / this candles. */
export const TF_DAYS: Record<Tf, number> = { "1d": 1, "1w": 5, "1m": 22, "3m": 66, "6m": 132 };

export const TF_NAME: Record<Tf, string> = {
  "1d": "روز",
  "1w": "هفته",
  "1m": "ماه",
  "3m": "سه ماه",
  "6m": "شش ماه",
};

const persian = new Intl.DateTimeFormat("en-US-u-ca-persian-nu-latn", {
  timeZone: "UTC",
  year: "numeric",
  month: "numeric",
});

/** The period a day falls in: equal keys mean the same candle. */
export function periodKey(iso: string, tf: Tf): string {
  const d = new Date(`${iso}T12:00:00Z`);
  if (tf === "1d") return iso;
  if (tf === "1w") {
    // the Persian week starts on Saturday (getUTCDay 6)
    const back = (d.getUTCDay() + 1) % 7;
    return new Date(d.getTime() - back * 86_400_000).toISOString().slice(0, 10);
  }
  const p = persian.formatToParts(d);
  const y = p.find((x) => x.type === "year")!.value;
  const m = Number(p.find((x) => x.type === "month")!.value);
  if (tf === "1m") return `${y}-${m}`;
  if (tf === "3m") return `${y}-q${Math.ceil(m / 3)}`;
  return `${y}-h${m <= 6 ? 1 : 2}`;
}

/** Daily candles merged into longer ones. Each merged candle is dated by its first trading day,
 *  opens at that day's open, closes at its last day's close, and adds up the volume. Also the
 *  date of the merged candle for every daily date, so marks and lines land on their candle. */
export function aggregate(
  candles: Candle[],
  tf: Tf,
): { candles: Candle[]; at: Map<string, string> } {
  const at = new Map<string, string>();
  if (tf === "1d") {
    for (const c of candles) at.set(c.date, c.date);
    return { candles, at };
  }
  const out: Candle[] = [];
  let key = "";
  for (const c of candles) {
    const k = periodKey(c.date, tf);
    if (k !== key || out.length === 0) {
      key = k;
      out.push({ ...c });
    } else {
      const b = out[out.length - 1];
      b.open ??= c.open;
      if (c.high != null) b.high = b.high == null ? c.high : Math.max(b.high, c.high);
      if (c.low != null) b.low = b.low == null ? c.low : Math.min(b.low, c.low);
      if (c.close != null) b.close = c.close;
      if (c.volume != null) b.volume = (b.volume ?? 0) + c.volume;
    }
    at.set(c.date, out[out.length - 1].date);
  }
  return { candles: out, at };
}

/** Dated points moved onto their merged candle, keeping the last point of each period (a line's
 *  value at the period's end). Points of days after the last candle form their own periods,
 *  dated by their first day; points of days before the first candle are dropped. */
export function regroup<T extends { time: string }>(
  points: T[],
  tf: Tf,
  at: Map<string, string>,
): T[] {
  if (tf === "1d") return points;
  const byKey = new Map<string, string>();
  for (const [day, first] of at) byKey.set(periodKey(day, tf), first);
  const last = new Map<string, T>();
  for (const p of points) {
    const k = periodKey(p.time, tf);
    let time = at.get(p.time) ?? byKey.get(k);
    if (time == null) {
      if (at.size && p.time < at.keys().next().value!) continue;
      time = p.time;
      byKey.set(k, time);
    }
    last.set(time, { ...p, time });
  }
  return [...last.values()].sort((x, y) => (x.time < y.time ? -1 : x.time > y.time ? 1 : 0));
}
