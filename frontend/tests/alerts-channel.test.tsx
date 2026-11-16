import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/portfolio", async (orig) => ({
  ...(await orig<typeof import("@/lib/portfolio")>()),
  call: vi.fn(async () => []),
}));

import { AlertsFeed } from "@/components/portfolio/PortfolioView";

describe("alerts without a notification channel", () => {
  it("says the alerts stay inside the page, so a silent portfolio is not mistaken for a quiet one", () => {
    render(<AlertsFeed id={1} pkey="k" hasChannel={false} />);
    const note = screen.getByTestId("no-channel");
    expect(note).toHaveTextContent("کانال اطلاع‌رسانی نداری");
    expect(note).toHaveTextContent("فقط داخل همین صفحه");
  });

  it("shows no notice once a channel is set", () => {
    render(<AlertsFeed id={1} pkey="k" hasChannel />);
    expect(screen.queryByTestId("no-channel")).toBeNull();
  });
});
