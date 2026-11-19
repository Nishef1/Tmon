import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ValueTable } from "@/components/compare/BubbleTables";
import type { SymbolValue } from "@/lib/api";

const row = (
  id: number,
  symbol: string,
  kind: string,
  bubble: number | null,
  real: number | null,
  note: string | null = null,
): SymbolValue => ({
  instrument_id: id,
  symbol,
  name: null,
  kind,
  industry: null,
  close: null,
  traded_value: null,
  fair_value: null,
  bubble,
  bubble_note: note,
  nominal_return: null,
  real_return: real,
});

const symbols = () =>
  within(screen.getByTestId("value-table"))
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("link")[0].textContent);

describe("ValueTable", () => {
  const rows = [
    row(1, "الف", "صندوق سهامی", 0.02, 0.1),
    row(2, "ب", "صندوق سهامی", -0.4, null, "حباب غیرعادی"),
    row(3, "پ", "صندوق طلا", -0.03, 0.2),
    row(4, "شکام", "سهم", null, 2.9),
    row(5, "فجهان", "سهم", null, 0.3),
  ];

  it("puts clean bubbles first, then the rest by real return", () => {
    render(<ValueTable rows={rows} months={12} />);
    expect(symbols()).toEqual(["پ", "الف", "ب", "شکام", "فجهان"]);
    expect(screen.getByTestId("value-summary").textContent).toContain("۴ نماد از ۴");
  });

  it("sorts by real return and filters stocks or all funds", () => {
    render(<ValueTable rows={rows} months={12} />);
    fireEvent.click(screen.getByRole("button", { name: /جلوتر از تورم/ }));
    expect(symbols()).toEqual(["الف", "پ", "فجهان", "شکام", "ب"]);
    const pick = screen.getByLabelText("نوع نماد:");
    fireEvent.change(pick, { target: { value: "سهم" } });
    expect(symbols()).toEqual(["فجهان", "شکام"]);
    fireEvent.change(pick, { target: { value: "همهٔ صندوق‌ها" } });
    expect(symbols()).toHaveLength(3);
  });
});
