import { describe, expect, it } from "vitest";
import { buildChecks } from "@/components/stock/Checks";
import type { InstrumentDashboard } from "@/lib/api";

const base = (rsi: number, green: number) =>
  ({
    decision: { gauge: null, verdict: "buy", horizons: [], queue_state: "none" },
    technical: { values: [{ key: "rsi", value: rsi }] },
    entry: { green },
  }) as unknown as InstrumentDashboard;

describe("short-term heat check", () => {
  it("warns when RSI is above 80 or six green candles ran", () => {
    expect(buildChecks(base(86.7, 8), undefined).find((c) => c.key === "heat")?.status).toBe(
      "warn",
    );
    expect(buildChecks(base(60, 6), undefined).some((c) => c.key === "heat")).toBe(true);
    expect(buildChecks(base(85, 0), undefined).some((c) => c.key === "heat")).toBe(true);
  });
  it("stays silent for a calm stock", () => {
    expect(buildChecks(base(60, 3), undefined).some((c) => c.key === "heat")).toBe(false);
  });
});
