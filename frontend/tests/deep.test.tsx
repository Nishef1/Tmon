import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DeepStudy } from "@/components/model/DeepStudy";
import { methodLabel } from "@/components/model/methods";
import type { Deep, DeepMethod } from "@/lib/api";

const stat = (mean: number, t: number | null = null) => ({ n: 800, mean, t, pos: 0.5 });

function method(over: Partial<DeepMethod> = {}): DeepMethod {
  return {
    ic: stat(0.12, 9),
    ex: stat(0.02, 9),
    d_ic: stat(0.02, 3.5),
    d_ex: stat(0.002, 1),
    d_ic_early: stat(0.015),
    d_ic_late: stat(0.025),
    seed_ic: [0.11, 0.12, 0.13],
    gate: { passed: false, reasons: ["مازاد دهک بالایش از وزن مساوی بیشتر نیست"] },
    ...over,
  };
}

function doc(passGbm: boolean): Deep {
  const equal = method({ d_ic: null, d_ex: null, d_ic_early: null, d_ic_late: null, gate: null });
  const gbm = method({ gate: { passed: passGbm, reasons: passGbm ? [] : ["x"] } });
  return {
    available: true,
    first: "2019-12-24",
    oos_from: "2022-11-07",
    mid: "2024-10-02",
    last: "2026-11-11",
    device: "cuda",
    torch: "2.14.1",
    seeds: [11, 12, 13],
    settings: { seq: 16 },
    round_trip_cost: 0.017512,
    min_t: 2,
    horizons: [
      { horizon_days: 5, methods: { equal, gbm, gru: method(), diff: method({ seed_ic: null }) } },
      { horizon_days: 20, methods: { equal, gbm: method() } },
    ],
    disclaimer: "x",
  };
}

describe("DeepStudy", () => {
  it("names the deep methods in plain Persian", () => {
    expect(methodLabel("gru")).toContain("GRU");
    expect(methodLabel("diff")).toContain("دیفیوژن");
    expect(methodLabel("resid")).toContain("باقیمانده");
    expect(methodLabel("hedge_all")).toContain("Hedge");
  });

  it("says nobody passed the gate and states the one-regime caveat", () => {
    render(<DeepStudy d={doc(false)} />);
    const c = screen.getByTestId("deep-caveat").textContent ?? "";
    expect(c).toContain("یک رژیم صعودی");
    expect(c).toContain("هیچ روشی در هیچ افقی از دروازه نگذشت");
  });

  it("names who passed, and marks that cell", () => {
    render(<DeepStudy d={doc(true)} />);
    expect(screen.getByTestId("deep-caveat").textContent).toContain("درخت تقویتی (GBM) در افق");
    const rows = screen.getByTestId("deep-matrix").querySelectorAll("tbody tr");
    expect(rows.length).toBe(3); // gbm, gru, diff: the methods present in some horizon
    expect(
      screen.getByTestId("deep-matrix").querySelectorAll('td[data-passed="true"]'),
    ).toHaveLength(1);
  });

  it("lists every method per horizon with the seed spread when there are seeds", () => {
    render(<DeepStudy d={doc(false)} />);
    const t = screen.getByTestId("deep-h5").textContent ?? "";
    expect(t).toContain("وزن مساوی");
    expect(t).toContain("۰٫۱۱");
  });
});
