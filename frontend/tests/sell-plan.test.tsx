import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SellPlan } from "@/components/portfolio/BuyPlan";

function serve(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => body })),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("sell line on a held stock", () => {
  it("gives the limit price and names the hour only when it was confirmed out of sample", async () => {
    serve({
      available: true,
      exit_plan: { available: true, recommended: { price: 1020, day_fill_prob: 0.6 } },
      timing: { available: true, sell: { label: "۱۲:۱۵–۱۲:۳۰", confirmed: true } },
    });
    render(<SellPlan instrumentId={1} />);
    const line = await screen.findByTestId("sell-plan");
    expect(line).toHaveTextContent("سفارش حدی");
    expect(line).toHaveTextContent("۱۲:۱۵–۱۲:۳۰");
  });

  it("does not name an hour that was not confirmed", async () => {
    serve({
      available: true,
      exit_plan: { available: true, recommended: { price: 1020, day_fill_prob: 0.6 } },
      timing: { available: true, sell: { label: "۱۲:۱۵–۱۲:۳۰", confirmed: false } },
    });
    render(<SellPlan instrumentId={1} />);
    const line = await screen.findByTestId("sell-plan");
    expect(line).not.toHaveTextContent("۱۲:۱۵");
  });

  it("stays hidden when there is nothing to say", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => ({ available: true, exit_plan: { available: false } }),
    }));
    vi.stubGlobal("fetch", f);
    render(<SellPlan instrumentId={1} />);
    await vi.waitFor(() => expect(f).toHaveBeenCalled());
    expect(screen.queryByTestId("sell-plan")).toBeNull();
  });
});
