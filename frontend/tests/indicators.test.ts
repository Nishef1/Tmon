import { describe, expect, it } from "vitest";
import { heikinAshi, measure, sma, type Bar } from "@/lib/indicators";

const bars: Bar[] = [
  { time: "2026-01-01", open: 10, high: 12, low: 9, close: 11 },
  { time: "2026-01-02", open: 11, high: 15, low: 10, close: 14 },
  { time: "2026-01-03", open: 14, high: 14, low: 8, close: 9 },
];

describe("heikinAshi", () => {
  it("smooths each bar with the previous one", () => {
    const ha = heikinAshi(bars);
    expect(ha[0].open).toBe(10.5);
    expect(ha[0].close).toBe(10.5);
    expect(ha[1].open).toBe(10.5);
    expect(ha[1].close).toBe(12.5);
    expect(ha[1].high).toBe(15);
    expect(ha[2].open).toBe(11.5);
    expect(ha[2].low).toBe(8);
  });
  it("keeps the dates and the length", () => {
    expect(heikinAshi(bars).map((b) => b.time)).toEqual(bars.map((b) => b.time));
    expect(heikinAshi([])).toEqual([]);
  });
});

describe("sma", () => {
  it("averages the closes of a full window only", () => {
    expect(sma(bars, 2)).toEqual([
      { time: "2026-01-02", value: 12.5 },
      { time: "2026-01-03", value: 11.5 },
    ]);
    expect(sma(bars, 5)).toEqual([]);
  });
});

describe("percent ruler", () => {
  const times = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-08"];
  it("measures change, candles and days between two points", () => {
    const m = measure(
      { time: "2026-11-01", price: 1000 },
      { time: "2026-11-08", price: 1150 },
      times,
    );
    expect(m?.pct).toBeCloseTo(0.15, 10);
    expect(m).toMatchObject({ delta: 150, bars: 3, days: 7 });
  });
  it("goes negative backwards and refuses a zero start", () => {
    const m = measure(
      { time: "2026-11-08", price: 1150 },
      { time: "2026-11-01", price: 1000 },
      times,
    );
    expect(m?.pct).toBeCloseTo(-0.1304, 3);
    expect(m?.bars).toBe(-3);
    expect(
      measure({ time: "2026-11-01", price: 0 }, { time: "2026-11-02", price: 1 }, times),
    ).toBeNull();
  });
});
