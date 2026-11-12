import { describe, expect, it } from "vitest";
import { heikinAshi, sma, type Bar } from "@/lib/indicators";

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
