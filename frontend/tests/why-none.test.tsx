import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WhyNoRecommendation } from "@/components/WhyNoRecommendation";
import type { Diagnosis } from "@/lib/api";

const diagnosis: Diagnosis = {
  universe: 685,
  stages: [
    { key: "universe", label: "نمادهای جهان امروز", count: 685, lost: 0, alone: 685 },
    { key: "ev", label: "سود خالص ≥ 0.50٪", count: 0, lost: 685, alone: 0 },
  ],
  binding: "ev",
  nearest: [
    {
      instrument: {
        id: 3,
        symbol: "فولاد",
        name: "فولاد",
        sector_code: "27",
        instrument_type: "stock",
      },
      p_win: 0.198,
      p_min: 0.502,
      shortfall: 0.304,
      ev: -0.0197,
      bucket_n: 900,
      failed: ["ev", "p_min"],
    },
  ],
  dropped_by_portfolio: {},
  stats: {
    p_win_max: 0.233,
    p_win_median: 0.233,
    p_min_median: 0.534,
    p_breakeven_median: 0.484,
    ev_max: -0.0197,
    ev_median: -0.02,
    n_ev_positive: 0,
    n_distinct_p_win: 1,
  },
  ev_min_abs: 0.005,
  min_bucket_samples: 200,
  margin: 0.05,
  p_floor: 0.35,
};

describe("WhyNoRecommendation", () => {
  it("states the binding stage with exact counts and the shortfall", () => {
    render(<WhyNoRecommendation diagnosis={diagnosis} gate={null} />);
    expect(screen.getByTestId("funnel")).toBeInTheDocument();
    expect(screen.getByTestId("why-none").textContent).toContain("۶۸۵");
    expect(screen.getByTestId("near-miss").textContent).toContain("۳۰٫۴٪");
    expect(screen.getByTestId("why-stats").textContent).toContain("نمادهای با سود مثبت: ۰");
  });

  it("flags a model that gives every symbol the same probability", () => {
    render(<WhyNoRecommendation diagnosis={diagnosis} gate={null} />);
    expect(screen.getByTestId("why-stats").textContent).toContain("یک‌جور امتیاز");
  });

  it("says plainly when no reason was stored", () => {
    render(<WhyNoRecommendation diagnosis={null} gate={null} />);
    expect(screen.getByTestId("why-missing")).toBeInTheDocument();
  });
});
