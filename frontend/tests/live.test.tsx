import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveQuote, ageText } from "@/components/LiveQuote";
import type { LiveQuote as Live } from "@/lib/api";

const base: Live = {
  instrument_id: 1,
  available: true,
  as_of: "2026-07-01T06:00:00Z",
  age_seconds: 20,
  stale: false,
  last_price: 1012,
  cum_volume: 456000,
  reference_price: 1000,
  change_pct: 0.012,
  book_as_of: "2026-07-01T06:00:00Z",
  book: [1, 2].map((i) => ({
    row: i,
    bid_price: 1000 - i,
    bid_volume: 100 * i,
    bid_count: i,
    ask_price: 1000 + i,
    ask_volume: 90 * i,
    ask_count: i,
  })),
  message: null,
  disclaimer: "x",
};

function mockFetch(body: Live | null, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok, json: async () => body, status: ok ? 200 : 500 }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveQuote", () => {
  it("shows price, signed change, volume and the book, each number linking to the glossary", async () => {
    mockFetch(base);
    render(<LiveQuote instrumentId={1} pollMs={60_000} />);
    await waitFor(() => expect(screen.getByTestId("order-book")).toBeInTheDocument());
    expect(screen.getByText("+۱٫۲٪")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);
    const link = screen.getByText("+۱٫۲٪").closest("a");
    expect(link).toHaveAttribute("href", "/glossary/change_pct");
    expect(screen.getByTestId("live-age")).not.toHaveTextContent("قدیمی");
  });

  it("flags stale data", async () => {
    mockFetch({ ...base, stale: true, age_seconds: 7200 });
    render(<LiveQuote instrumentId={1} pollMs={60_000} />);
    await waitFor(() => expect(screen.getByTestId("live-age")).toHaveTextContent("قدیمی"));
  });

  it("says so when nothing is stored, and when the API is down", async () => {
    mockFetch({ ...base, available: false, message: "هنوز داده‌ای نیست" });
    const { unmount } = render(<LiveQuote instrumentId={1} pollMs={60_000} />);
    await waitFor(() => expect(screen.getByTestId("live-unavailable")).toHaveTextContent("هنوز"));
    unmount();
    mockFetch(null, false);
    render(<LiveQuote instrumentId={1} pollMs={60_000} />);
    await waitFor(() => expect(screen.getByTestId("live-error")).toBeInTheDocument());
  });

  it("describes data age in Persian", () => {
    expect(ageText(5)).toBe("چند ثانیه پیش");
    expect(ageText(300)).toContain("دقیقه");
    expect(ageText(7200)).toContain("ساعت");
    expect(ageText(null)).toBe("");
  });
});
