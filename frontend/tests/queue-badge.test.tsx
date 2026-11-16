import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueueBadge } from "@/components/QueueBadge";

describe("QueueBadge", () => {
  it("names the level and puts the ratio in parentheses", () => {
    render(
      <QueueBadge
        r={{ queue_state: "buy_queue", queue_ratio: 2.44, queue_level: "heavy", queue_orders: 538 }}
      />,
    );
    const b = screen.getByTestId("queue-badge");
    expect(b.textContent).toBe("صف خرید سنگین (۲٫۴)");
    expect(b.getAttribute("title")).toContain("۵۳۸ سفارش");
  });

  it("adds the past reach share as an upper bound to the tooltip", () => {
    render(
      <QueueBadge
        r={{
          queue_state: "buy_queue",
          queue_ratio: 2.44,
          queue_level: "heavy",
          queue_reach_pct: 0.4,
          queue_reach_cases: 120,
        }}
      />,
    );
    const t = screen.getByTestId("queue-badge").getAttribute("title") ?? "";
    expect(t).toContain("۴۰٪");
    expect(t).toContain("سقف شانس پر شدن");
  });

  it("shows a line without a stored book as the plain label and nothing otherwise", () => {
    const { container, rerender } = render(<QueueBadge r={{ queue_state: "buy_queue" }} />);
    expect(container.textContent).toBe("صف خرید");
    rerender(<QueueBadge r={{ queue_state: "none" }} />);
    expect(container.textContent).toBe("");
  });

  it("marks a weak line as such even when the close was not at the limit", () => {
    render(<QueueBadge r={{ queue_state: "none", queue_ratio: 0.12, queue_level: "weak" }} />);
    expect(screen.getByTestId("queue-badge").textContent).toBe("صف خرید ضعیف (۰٫۱)");
  });
});
