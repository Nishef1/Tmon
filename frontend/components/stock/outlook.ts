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
