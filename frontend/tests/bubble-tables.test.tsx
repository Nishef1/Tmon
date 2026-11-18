import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundsTable } from "@/components/compare/BubbleTables";
import type { Fund } from "@/lib/api";

const fund = (reg_no: string, symbol: string, bubble: number | null, note?: string): Fund => ({
  reg_no,
  symbol,
  name: `صندوق ${symbol}`,
  instrument_id: Number(reg_no),
  kind: reg_no === "3" ? "صندوق طلا" : "صندوق سهامی",
  listed: true,
  nav_date: "2026-11-17",
  fund_type: null,
  industry: null,
  cancel_nav: null,
  issue_nav: null,
  net_asset: null,
  price: null,
  bubble,
  bubble_note: note ?? null,
});

const symbols = () =>
  within(screen.getByTestId("funds-table"))
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("link")[0].textContent);

describe("FundsTable", () => {
  const funds = [
    fund("1", "الف", 0.02),
    fund("2", "ب", -0.4, "حباب غیرعادی"),
    fund("3", "پ", -0.03),
    fund("4", "ت", null, "قیمت ثبت نشده"),
  ];

  it("puts clean rows first, most negative bubble first", () => {
    render(<FundsTable funds={funds} />);
    expect(symbols()).toEqual(["پ", "الف", "ب", "ت"]);
  });

  it("flips the order on a second click and filters by kind", () => {
    render(<FundsTable funds={funds} />);
    fireEvent.click(screen.getByRole("button", { name: /حباب/ }));
    expect(symbols()).toEqual(["الف", "پ", "ب", "ت"]);
    fireEvent.change(screen.getByLabelText("نوع صندوق:"), { target: { value: "صندوق طلا" } });
    expect(symbols()).toEqual(["پ"]);
  });
});
