import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AdaptSection, methodLabel } from "@/components/model/AdaptSection";
import type { Adapt } from "@/lib/api";

const W = { ind_buy_power: 0.25, rv_20: 0.25, dist_high_52w: 0.25, mom_12_1: 0.25 };
const stat = { n: 10, mean: 0, t: null, pos: 0 };

function horizon(h: number, champion = "equal"): Adapt["horizons"][number] {
  return {
    horizon_days: h,
    window_from: "2024-07-09",
    window_to: "2026-11-04",
    window_dates: 500,
    champion,
    why: "هیچ نامزدی از دروازه نگذشت؛ وزن مساوی می‌ماند",
    production_expressible: true,
    weights: W,
    reference_weights: { ...W, ind_buy_power: 0.6 },
    candidates: {
      ridge4_x120: {
        passed: false,
        reasons: ["برتری‌اش در هر دو نیمهٔ پنجره دیده نمی‌شود"],
        n: 499,
        ic: 0.15,
        d_ic: 0.0166,
        t: 2.2,
        early: -0.017,
        late: 0.05,
        top_excess: 0.019,
        d_top_excess: 0.002,
      },
    },
  };
}

const doc: Adapt = {
  available: true,
  as_of: "2026-11-11",
  round_trip_cost: 0.017512,
  config: {
    window_dates: 500,
    min_half_dates: 150,
    min_t: 2,
    switch_margin_t: 1,
    history_keep: 240,
    replay_every_dates: 21,
    candidates: ["ridge4_x120"],
  },
  horizons: [horizon(5), horizon(20)],
  drift: { "5": { dates: ["2026-10-13", "2026-11-11"], series: { ind_buy_power: [0.5, 0.6] } } },
  history: [{ as_of: "2026-11-11", champions: { "5": "equal", "20": "equal" } }],
  replay: {
    every: 21,
    as_of: "2026-11-11",
    horizons: {
      "5": {
        horizon_days: 5,
        first_cycle: "2024-12-18",
        n_cycles: 19,
        share_equal: 1,
        meta_ic: stat,
        equal_ic: stat,
        d_ic: stat,
        d_ic_early: stat,
        d_ic_late: stat,
        d_top_excess: stat,
        split_date: "2025-10-27",
        timeline: [
          { date: "2024-12-18", champion: "equal" },
          { date: "2025-01-19", champion: "equal" },
        ],
        candidate_counts: { equal: 19 },
      },
    },
  },
  disclaimer: "x",
};

describe("AdaptSection", () => {
  it("names methods in plain Persian", () => {
    expect(methodLabel("equal")).toBe("وزن مساوی");
    expect(methodLabel("ridge4_x120")).toContain("ریج روی ۴ سیگنال");
    expect(methodLabel("hedge_k30")).toContain("Hedge");
    expect(methodLabel("unknown_key")).toBe("unknown_key");
  });

  it("says equal weights stay when nobody passed the gate, with the one-regime caveat", () => {
    render(<AdaptSection d={doc} />);
    expect(screen.getByTestId("adapt-caveat").textContent).toContain("یک رژیم صعودی");
    expect(screen.getByTestId("adapt-caveat").textContent).toContain("وزن مساوی همه‌جا قهرمان");
    expect(screen.getByTestId("adapt-champions").querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("shows the replay and the candidate reasons, and the shadow-only mark", () => {
    const shadow = { ...doc, horizons: [{ ...horizon(5, "gbm"), production_expressible: false }] };
    render(<AdaptSection d={shadow} />);
    expect(screen.getByTestId("adapt-replay").textContent).toContain("۱۹");
    expect(screen.getByTestId("adapt-champions").textContent).toContain("فقط سایه");
    expect(screen.getByTestId("adapt-candidates-5").textContent).toContain("هر دو نیمهٔ پنجره");
    expect(screen.getByTestId("adapt-caveat").textContent).not.toContain("همه‌جا قهرمان");
  });
});
