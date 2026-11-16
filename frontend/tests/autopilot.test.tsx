import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AutopilotStatus } from "@/components/model/AutopilotStatus";
import type { Autopilot } from "@/lib/api";

function doc(over: Partial<Autopilot> = {}): Autopilot {
  return {
    available: true,
    checked_at: "2026-11-14T10:00:00",
    as_of: "2026-11-14",
    regime: {
      as_of: "2026-11-14",
      drawdown: 0.0126,
      return_recent: 1.2494,
      recent_days: 120,
      windows: [1.6, 0.57, -0.01, 0.48],
      bear_windows: 0,
      bullish_only: true,
      stress: false,
      stress_drawdown: 0.2,
    },
    events: [],
    disclaimer: "x",
    ...over,
  };
}

describe("AutopilotStatus", () => {
  it("says the regime is still one and that nothing changed", () => {
    render(<AutopilotStatus a={doc()} />);
    expect(screen.getByTestId("autopilot-regime").textContent).toContain("یک رژیم صعودی");
    expect(screen.getByTestId("autopilot-no-events")).toBeTruthy();
  });

  it("lists events newest first in plain words, and a stress reading", () => {
    const a = doc({
      events: [
        {
          at: "2026-11-14",
          kind: "champion",
          horizon: 5,
          before: "equal",
          after: "gbm",
        },
        {
          at: "2026-11-13",
          kind: "regime",
          after: "stress",
          before: null,
          horizon: null,
        },
      ],
    });
    a.regime = { ...a.regime!, stress: true, bullish_only: false, bear_windows: 1 };
    render(<AutopilotStatus a={a} />);
    const items = screen.getByTestId("autopilot-events").querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("وزن مساوی");
    expect(items[0].textContent).toContain("درخت تقویتی (GBM)");
    expect(items[1].textContent).toContain("هشدار رژیم");
    expect(screen.getByTestId("autopilot-regime").textContent).toContain("اکنون در حالت افت است");
    expect(screen.getByTestId("autopilot-regime").textContent).not.toContain("فقط در یک رژیم");
  });
});
