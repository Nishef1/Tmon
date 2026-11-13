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

import fixture from "./fixtures-ta.json";
import * as ind from "@/lib/indicators";

// The same bars and last values from tmon.backtest.ta_signals (backend), so the chart and the
// symbol card can never disagree.
describe("chart indicators match the backend", () => {
  const bars = fixture.bars as ind.VBar[];
  const want = fixture.last as Record<string, number>;
  const last = (s: ind.Series) => s[s.length - 1].value;
  const close = (got: number, key: string) => expect(got).toBeCloseTo(want[key], 6);

  it("momentum and trend", () => {
    close(last(ind.rsi(bars)), "rsi");
    const m = ind.macd(bars);
    close(last(m.macd), "macd");
    close(last(m.signal), "macd_sig");
    const s = ind.stochastic(bars);
    close(last(s.k), "stoch_k");
    close(last(s.d), "stoch_d");
    close(last(s.k) - 100, "willr");
    close(last(ind.mfi(bars)), "mfi");
    const a = ind.adx(bars);
    close(last(a.adx), "adx");
    close(last(a.pdi), "pdi");
    close(last(a.mdi), "mdi");
    close(last(ind.atrPct(bars)), "atr_pct");
    close(last(ind.obv(bars)), "obv");
  });

  it("price overlays and levels", () => {
    const b = ind.bollinger(bars);
    close(last(b.up), "bb_up");
    close(last(b.dn), "bb_dn");
    close(last(b.mid), "sma20");
    close(last(ind.ema(bars, 12)), "ema12");
    close(last(ind.ema(bars, 26)), "ema26");
    close(last(ind.vwap(bars)), "vwap20");
    const i = ind.ichimoku(bars);
    close(last(i.tenkan), "tenkan");
    close(last(i.kijun), "kijun");
    close(Math.max(last(i.spanA), last(i.spanB)), "cloud_top");
    close(Math.min(last(i.spanA), last(i.spanB)), "cloud_bot");
    const lv = Object.fromEntries(ind.levels(bars).map((l) => [l.key, l.price]));
    close(lv.res20, "hi20");
    close(lv.sup20, "lo20");
    close(lv.r1, "r1");
    close(lv.s1, "s1");
    close(lv.fib618, "fib618");
  });
});
