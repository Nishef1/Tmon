import { describe, expect, it } from "vitest";
import { pickPeriod } from "@/components/stock/outlook";
import type { SymbolForecast } from "@/lib/api";

const h = (key: string, days: number, low: number, mid: number, high: number) => ({
  key,
  label: key,
  days,
  low,
  mid,
  high,
  p_gain_net: 0.5,
  calibrated: true,
  coverage80: 0.8,
  windows: 30,
  reliable: true,
  drift_weight: 0.25,
});

const f: SymbolForecast = {
  available: true,
  as_of: "2026-11-18",
  reason: null,
  price: 1000,
  history_days: 900,
  horizons: [
    h("day", 1, -0.03, 0, 0.03),
    h("days3", 3, -0.06, 0.003, 0.06),
    h("week", 5, -0.1, 0.01, 0.1),
  ],
};

describe("outlook", () => {
  it("falls back to three months, then to nothing it does not have", () => {
    expect(pickPeriod(f, "days3")?.days).toBe(3);
    expect(pickPeriod(f, "nope")).toBeUndefined();
  });
});
