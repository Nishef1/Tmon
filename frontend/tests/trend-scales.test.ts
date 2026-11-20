import { describe, expect, it } from "vitest";
import { legText, zigzag } from "@/components/stock/PriceChartTrends";
import type { components } from "@/lib/api-schema";

type Scale = components["schemas"]["TrendScale"];

const up: Scale = {
  size: 0.15,
  label: "میانی",
  swings: [
    { date: "2026-01-01", kind: "low", close: 100 },
    { date: "2026-02-01", kind: "high", close: 150 },
    { date: "2026-03-01", kind: "low", close: 120 },
  ],
  direction: "up",
  since: { date: "2026-03-01", kind: "low", close: 120 },
  extreme: { date: "2026-04-01", kind: "high", close: 200 },
  from_since: 0.5,
  from_extreme: -0.1,
};

describe("trend scales", () => {
  it("draws the swings, then the running extreme and the last close", () => {
    const p = zigzag(up, { date: "2026-04-10", open: 1, high: 1, low: 1, close: 180, volume: 1 });
    expect(p.straight).toBe(true);
    expect(p.points.map((x) => x.value)).toEqual([100, 150, 120, 200, 180]);
  });

  it("does not repeat the last day when the extreme is already on it", () => {
    const p = zigzag(up, { date: "2026-04-01", open: 1, high: 1, low: 1, close: 200, volume: 1 });
    expect(p.points).toHaveLength(4);
  });

  it("names the confirming close of an up leg", () => {
    const t = legText(up) ?? "";
    expect(t).toContain("صعودی");
    expect(t).toContain("۱۷۰"); // 200 * (1 - 0.15)
  });

  it("has no sentence before the first confirmed swing", () => {
    expect(legText({ ...up, direction: null, since: null, extreme: null, swings: [] })).toBeNull();
  });
});
