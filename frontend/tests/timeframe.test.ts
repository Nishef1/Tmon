import { describe, expect, it } from "vitest";
import type { Candle } from "@/lib/api";
import { aggregate, periodKey, regroup } from "@/lib/timeframe";

const c = (date: string, o: number, h: number, l: number, cl: number, v: number): Candle =>
  ({ date, open: o, high: h, low: l, close: cl, volume: v }) as Candle;

describe("periodKey", () => {
  it("starts the week on Saturday", () => {
    // 2026-11-14 is a Saturday, 2026-11-18 a Wednesday, 2026-11-21 the next Saturday
    expect(periodKey("2026-11-14", "1w")).toBe("2026-11-14");
    expect(periodKey("2026-11-18", "1w")).toBe("2026-11-14");
    expect(periodKey("2026-11-21", "1w")).toBe("2026-11-21");
  });
  it("uses Persian months, seasons and halves", () => {
    // 1 Azar 1405 is 2026-11-22; 30 Aban 1405 is 2026-11-21
    expect(periodKey("2026-11-21", "1m")).not.toBe(periodKey("2026-11-22", "1m"));
    expect(periodKey("2026-11-21", "3m")).toBe(periodKey("2026-11-22", "3m"));
    // 1 Mehr 1405 (2026-09-23) starts the second half and the third season
    expect(periodKey("2026-09-22", "6m")).not.toBe(periodKey("2026-09-23", "6m"));
    expect(periodKey("2026-09-22", "3m")).not.toBe(periodKey("2026-09-23", "3m"));
  });
});

describe("aggregate", () => {
  const days = [
    c("2026-11-14", 10, 12, 9, 11, 100),
    c("2026-11-15", 11, 15, 10, 14, 50),
    c("2026-11-18", 14, 14, 8, 9, 25),
    c("2026-11-21", 9, 10, 9, 10, 5),
  ];
  it("merges a week into one candle dated by its first day", () => {
    const { candles, at } = aggregate(days, "1w");
    expect(candles).toHaveLength(2);
    expect(candles[0]).toMatchObject({
      date: "2026-11-14",
      open: 10,
      high: 15,
      low: 8,
      close: 9,
      volume: 175,
    });
    expect(at.get("2026-11-18")).toBe("2026-11-14");
    expect(at.get("2026-11-21")).toBe("2026-11-21");
  });
  it("keeps the last point of each period and dates later days by their own period", () => {
    const { at } = aggregate(days, "1w");
    const pts = [
      { time: "2026-11-01", value: 1 },
      { time: "2026-11-14", value: 2 },
      { time: "2026-11-18", value: 3 },
      { time: "2026-11-22", value: 4 },
      { time: "2026-11-29", value: 5 },
    ];
    expect(regroup(pts, "1w", at)).toEqual([
      { time: "2026-11-14", value: 3 },
      { time: "2026-11-21", value: 4 },
      { time: "2026-11-29", value: 5 },
    ]);
  });
  it("leaves daily candles as they are", () => {
    expect(aggregate(days, "1d").candles).toBe(days);
  });
});
