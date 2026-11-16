import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Verdict } from "@/components/SymbolDashboard";
import type { InstrumentDashboard } from "@/lib/api";

type D = InstrumentDashboard["decision"];

const month = (over: Record<string, unknown>) =>
  ({
    key: "M1",
    label: "یک ماه",
    days: 20,
    verdict: "hold",
    verdict_label: "صبر",
    weak: false,
    vetoed: false,
    headline: "برای یک ماه: فعلاً نخرید؛ سود اضافهٔ گذشته کم بوده است.",
    reasons: [],
    top_excess: 0.04,
    cost: 0.0175,
    net_excess: 0.0225,
    ic: null,
    ic_t: null,
    ...over,
  }) as unknown as NonNullable<D["horizons"][number]>;

const decision = (over: Record<string, unknown> = {}) =>
  ({
    verdict: "hold",
    label: "صبر",
    weak: false,
    gauge: 95,
    rank: 5,
    zone_hold_from: 70,
    zone_buy_from: 90,
    summary: "",
    headline: "",
    reasons: [],
    horizons: [],
    ...over,
  }) as unknown as D;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("verdict head next to the gauge", () => {
  it("does not blame a thin edge when the state veto lowered the buy", () => {
    render(<Verdict d={decision()} h={month({ vetoed: true })} id={1} />);
    expect(screen.queryByTestId("wait-why")).toBeNull();
  });

  it("explains a high score with a wait when the edge itself was too thin", () => {
    render(<Verdict d={decision()} h={month({ net_excess: 0.004 })} id={1} />);
    expect(screen.getByTestId("wait-why")).toHaveTextContent("کافی نبوده");
  });

  it("says the gauge is a rank, not advice, when it sits in the buy zone but the word is not buy", () => {
    render(<Verdict d={decision()} h={month({ vetoed: true })} id={1} />);
    expect(screen.getByTestId("gauge-not-advice")).toHaveTextContent("فقط رتبه");
  });

  it("keeps the gauge caption plain when the verdict is a buy", () => {
    render(
      <Verdict
        d={decision({ verdict: "buy", label: "بخرید" })}
        h={month({ verdict: "buy", verdict_label: "بخرید" })}
        id={1}
      />,
    );
    expect(screen.queryByTestId("gauge-not-advice")).toBeNull();
    expect(screen.queryByTestId("wait-why")).toBeNull();
  });
});
