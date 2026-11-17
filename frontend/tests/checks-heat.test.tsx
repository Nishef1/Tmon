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

const text = (n: unknown): string => {
  if (n == null || typeof n === "boolean") return "";
  if (typeof n === "string" || typeof n === "number") return String(n);
  if (Array.isArray(n)) return n.map(text).join("");
  const props = (n as { props?: { children?: unknown } }).props;
  return text(props?.children);
};

describe("rank and history wording", () => {
  const dash = (gauge: number) =>
    ({
      decision: {
        gauge,
        rank: 1,
        verdict: "hold",
        band: "candidate",
        grade: "unproven",
        grade_label: "ثابت‌نشده",
        horizons: [],
        queue_state: "none",
      },
    }) as unknown as InstrumentDashboard;
  it("never says a stock beats 100% of the market", () => {
    const row = buildChecks(dash(99.6), undefined).find((c) => c.key === "rank");
    expect(text(row?.answer)).toContain("۹۹٪");
    expect(text(row?.answer)).not.toContain("۱۰۰");
  });
  it("does not pair high confidence with a negative net edge", () => {
    const h = {
      label: "یک ماه (۲۰ روز)",
      top_excess: 0.015,
      net_excess: -0.003,
      cost: 0.0175,
      ic_t: 3.6,
    };
    const row = buildChecks(dash(95), h as never).find((c) => c.key === "history");
    const t = text(row?.answer);
    expect(t).toContain("کارمزد را پوشش نمی‌دهد");
    expect(t).not.toContain("(اطمینان زیاد)");
    expect(t).toContain("ثابت‌نشده");
  });
  it("is silent for a stock in the middle of the list", () => {
    const d = dash(60);
    (d.decision as { band: string }).band = "middle";
    const h = { label: "سه ماه", top_excess: 0.01, net_excess: 0.01, cost: 0.0175, ic_t: 1 };
    expect(buildChecks(d, h as never).some((c) => c.key === "history")).toBe(false);
  });
});
