import { describe, expect, it } from "vitest";
import { conePoints, pickPeriod, tradingDaysAfter } from "@/components/stock/outlook";
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
  it("skips Thursday and Friday", () => {
    // 2026-11-18 is a Wednesday: next are Saturday, Sunday, Monday
    expect(tradingDaysAfter("2026-11-18", 3)).toEqual(["2026-11-21", "2026-11-22", "2026-11-23"]);
  });

  it("falls back to three months, then to nothing it does not have", () => {
    expect(pickPeriod(f, "days3")?.days).toBe(3);
    expect(pickPeriod(f, "nope")).toBeUndefined();
  });

  it("draws the range from today's price through every measured period", () => {
    const cone = conePoints(f, f.horizons[1], "2026-11-18")!;
    expect(cone.points.map((p) => p.time)).toEqual([
      "2026-11-18",
      "2026-11-21",
      "2026-11-22",
      "2026-11-23",
    ]);
    expect(cone.points[0]).toEqual({ time: "2026-11-18", low: 1000, mid: 1000, high: 1000 });
    expect(cone.points[1].low).toBeCloseTo(970);
    // halfway between the 1-day and the 3-day knots
    expect(cone.points[2].high).toBeCloseTo(1045);
    expect(cone.points[3].mid).toBeCloseTo(1003);
  });
});
