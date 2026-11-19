import type { Cone } from "@/components/CandleChart";
import type { SymbolForecast } from "@/lib/api";

export type Period = SymbolForecast["horizons"][number];

/** The periods the outlook offers, in order; ``quarter`` is the verdict's own 60 days. */
export const PERIOD_KEYS = ["day", "days3", "week", "month", "quarter", "half"] as const;
export const DEFAULT_PERIOD = "quarter";

export const PERIOD_SHORT: Record<string, string> = {
  day: "۱ روز",
  days3: "۳ روز",
  week: "۱ هفته",
  month: "۱ ماه",
  quarter: "۳ ماه",
  half: "۶ ماه",
};

export function pickPeriod(f: SymbolForecast, key: string | undefined): Period | undefined {
  return f.horizons.find((x) => x.key === key) ?? f.horizons.find((x) => x.key === DEFAULT_PERIOD);
}

/** The next ``n`` trading days after ``iso``: Thursday and Friday are skipped, holidays are not
 *  known ahead, so a period that spans one ends a day or two later on the real calendar. */
export function tradingDaysAfter(iso: string, n: number): string[] {
  const out: string[] = [];
  const d = new Date(`${iso}T00:00:00Z`);
  while (out.length < n) {
    d.setUTCDate(d.getUTCDate() + 1);
    const wd = d.getUTCDay();
    if (wd !== 4 && wd !== 5) out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

/** The forecast drawn on the chart up to the chosen period: the 80% range and the median at every
 *  measured period on the way (1, 3, 5 ... days), joined by straight lines from today's price. */
export function conePoints(f: SymbolForecast, period: Period, lastDate: string): Cone | null {
  if (!f.price) return null;
  const p = f.price;
  const knots = f.horizons.filter((x) => x.days <= period.days);
  const days = tradingDaysAfter(lastDate, period.days);
  const points: Cone["points"] = [{ time: lastDate, low: p, mid: p, high: p }];
  let prev = { days: 0, low: 0, mid: 0, high: 0 };
  for (const k of knots) {
    for (let t = prev.days + 1; t <= k.days; t++) {
      const w = (t - prev.days) / (k.days - prev.days);
      const at = (a: number, b: number) => p * (1 + a + (b - a) * w);
      points.push({
        time: days[t - 1],
        low: at(prev.low, k.low),
        mid: at(prev.mid, k.mid),
        high: at(prev.high, k.high),
      });
    }
    prev = k;
  }
  return { points, label: PERIOD_SHORT[period.key] ?? period.label };
}
