import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Verdict } from "@/components/stock/Verdict";
import type { InstrumentDashboard } from "@/lib/api";

type D = InstrumentDashboard["decision"];

const quarter = (over: Record<string, unknown>) =>
  ({
    key: "Q1",
    label: "سه ماه",
    days: 60,
    verdict: "hold",
    verdict_label: "صبر",
    weak: false,
    vetoed: false,
    headline: "برای این سهم: فعلاً نخرید؛ حالت سهم در گذشته از بازار جلو نزده است.",
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
    code: "wait",
    holder_code: "hold",
    holder_verdict: "hold",
    holder_label: "نگه‌دار",
    holder_headline: "اگر دارید، نگه دارید.",
    band: "candidate",
    grade: "unproven",
    grade_label: "ثابت‌نشده",
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
  it("says the gauge is a rank, not advice, when it sits in the buy zone but the word is not buy", () => {
    render(<Verdict d={decision()} h={quarter({ vetoed: true })} id={1} />);
    expect(screen.getByTestId("gauge-not-advice")).toHaveTextContent("فقط رتبه");
  });

  it("keeps the gauge caption plain when the verdict is a buy", () => {
    render(
      <Verdict
        d={decision({ verdict: "buy", label: "خرید", code: "buy", grade: "proven" })}
        h={quarter({ verdict: "buy", verdict_label: "خرید" })}
        id={1}
      />,
    );
    expect(screen.queryByTestId("gauge-not-advice")).toBeNull();
  });

  it("uses «صبر» for someone who does not own the stock, and shows the grade of the zone", () => {
    render(<Verdict d={decision()} h={quarter({ vetoed: true })} id={1} />);
    expect(screen.getByTestId("verdict-word")).toHaveTextContent("صبر");
    expect(screen.getByTestId("verdict-word")).not.toHaveTextContent("نگه");
    expect(screen.getByTestId("verdict-grade")).toHaveTextContent("ثابت‌نشده");
  });

  it("shows no grade for a stock in the middle of the list", () => {
    render(
      <Verdict
        d={decision({ band: "middle", grade: null, grade_label: null, code: "with_market" })}
        h={quarter({ verdict_label: "همراه بازار" })}
        id={1}
      />,
    );
    expect(screen.queryByTestId("verdict-grade")).toBeNull();
    expect(screen.getByTestId("verdict-word")).toHaveTextContent("همراه بازار");
  });
});
