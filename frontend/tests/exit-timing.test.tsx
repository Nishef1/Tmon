import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntryGuard } from "@/components/stock/EntryGuard";

const pick = (label: string, confirmed: boolean, vs: number) => ({
  window: 2,
  label,
  confirmed,
  vs_day: vs,
  t: confirmed ? 3.1 : 0.4,
});

const slice = (k: number) => ({
  window: k,
  label: `۰۹:${String(k * 15).padStart(2, "0")}`,
  mid_vs_day: 0.0004 * k - 0.002,
  low_share: 0.2,
  high_share: 0.15,
  chance_low: 0.07,
  chance_high: 0.07,
});

const base = {
  available: true,
  live: true,
  verdict: "sell",
  bar: { last: 1000, close: 990, yesterday: 980 },
  guard: { state: "wait", headline: "الان صبر", reasons: [] },
  review: null,
};

const exitPlan = {
  available: true,
  mode: "today",
  reference: 980,
  now: 1000,
  headline: "سفارش حدی فروش را روی ۱٬۰۲۰ بگذارید.",
  ladder: [
    {
      fill_prob: 0.5,
      day_fill_prob: 0.6,
      price: 1020,
      vs_now: 0.02,
      vs_ref: 0.04,
      touched_today: false,
      fallback_price: 990,
      gain_vs_now: 0.004,
    },
  ],
  recommended: {
    fill_prob: 0.5,
    day_fill_prob: 0.6,
    price: 1020,
    vs_now: 0.02,
    vs_ref: 0.04,
    touched_today: false,
    fallback_price: 990,
    gain_vs_now: 0.004,
  },
  basis: { market_days: 480, own_days: 60, gap_bucket: null, minutes_left: 120 },
  notes: ["احتمال‌ها از روزهای گذشته‌اند."],
};

function serve(extra: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ ...base, ...extra }) })),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("exit ladder and time of day on the stock page", () => {
  it("shows the sell ladder with the days it rests on and the recommended price", async () => {
    serve({ exit_plan: exitPlan });
    render(<EntryGuard instrumentId={1} />);
    const block = await screen.findByTestId("exit-plan");
    expect(block).toHaveTextContent("بهترین فروش");
    expect(block).toHaveTextContent("← پیشنهاد");
    expect(block).toHaveTextContent("۴۸۰ روز مشابه بازار");
    expect(block).toHaveTextContent("۶۰ روز خودِ این نماد");
  });

  it("names a slice only when it was confirmed, with its basis and the table behind it", async () => {
    serve({
      timing: {
        available: true,
        basis: "own",
        basis_days: 64,
        last_day: "2026-11-15",
        headline: "خرید: 10:00–10:15 (در روزهای آزمون‌شده 0.5٪ پایین‌تر از میانگین روز).",
        spread: 0.004,
        table: [slice(0), slice(1)],
        buy: pick("10:00–10:15", true, -0.005),
        sell: pick("12:15–12:30", false, 0.0004),
        notes: ["اثر ساعت هنوز آزموده نشده است (برآورد اولیه)."],
      },
    });
    render(<EntryGuard instrumentId={1} />);
    const block = await screen.findByTestId("timing");
    expect(block).toHaveTextContent("خرید: ۱۰:۰۰–۱۰:۱۵");
    expect(block).toHaveTextContent("۶۴ روز خودِ این نماد");
    expect(block).toHaveTextContent("برآورد اولیه");
    expect(block).toHaveTextContent("تصادفی");
  });

  it("shows the no-reliable-hour sentence as plain muted text, not as advice", async () => {
    serve({
      timing: {
        available: true,
        basis: "market",
        basis_days: 900,
        last_day: "2026-11-15",
        headline: "ساعت مشخصی برای خرید یا فروش این نماد به‌طور معتبر بهتر نبوده.",
        spread: 0.003,
        table: [slice(0)],
        buy: pick("09:15–09:30", false, 0.0001),
        sell: pick("09:15–09:30", false, 0.0001),
        notes: [],
      },
    });
    render(<EntryGuard instrumentId={1} />);
    const block = await screen.findByTestId("timing");
    expect(block).toHaveTextContent("معتبر بهتر نبوده");
    expect(block).toHaveTextContent("همهٔ نمادهای دارای داده");
  });

  it("says the data is not enough instead of inventing an hour", async () => {
    serve({ timing: { available: false, message: "دادهٔ کافی برای ساعت بهتر نیست." } });
    render(<EntryGuard instrumentId={1} />);
    const note = await screen.findByTestId("timing-missing");
    expect(note).toHaveTextContent("دادهٔ کافی");
    expect(screen.queryByTestId("timing")).toBeNull();
  });
});
