import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Disclaimer, DISCLAIMER } from "@/components/Disclaimer";
import { Num } from "@/components/Num";
import { SignalCard } from "@/components/SignalCard";
import { SignalTable } from "@/components/SignalTable";
import type { Signal } from "@/lib/api";

const signal: Signal = {
  id: 1,
  date: "2025-03-01",
  timeframe: "D1",
  rank: 1,
  instrument: {
    id: 7,
    symbol: "فولاد",
    name: "فولاد مبارکه",
    sector_code: "27",
    instrument_type: "stock",
  },
  entry_price: 1000,
  entry_rule: "open_next_day",
  take_profit: 1060,
  stop_loss: 970,
  horizon_days: 3,
  p_win: 0.66,
  ev: 0.031,
  confidence_tier: "B",
  position_pct: 0.05,
  top_reasons: [
    { feature: "rsi_14", value: 55, contribution: 0.4 },
    { feature: "ret_5", value: 0.02, contribution: -0.1 },
  ],
  risks: ["نوسان بالا"],
  model_version: "m1",
  data_snapshot_id: "snap",
  outcome: "pending",
  realized_return: null,
  outcome_date: null,
};

describe("Num", () => {
  it("links the number to its glossary entry", () => {
    render(<Num term="p_win" value={0.66} kind="percent" digits={0} />);
    const a = screen.getByRole("link");
    expect(a).toHaveAttribute("href", "/glossary/p_win");
    expect(a).toHaveTextContent("۶۶٪");
  });

  it("shows a dash for missing values but still links", () => {
    render(<Num term="ev" value={null} kind="percent" />);
    expect(screen.getByRole("link")).toHaveTextContent("—");
  });
});

describe("Disclaimer", () => {
  it("carries the required wording", () => {
    render(<Disclaimer />);
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(
      "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست",
    );
    expect(DISCLAIMER).toContain("توصیه سرمایه‌گذاری نیست");
  });
});

describe("SignalCard", () => {
  it("links every metric to the glossary and the symbol to its page", () => {
    render(<SignalCard s={signal} />);
    const card = screen.getByTestId("signal-card");
    expect(within(card).getByRole("link", { name: "فولاد" })).toHaveAttribute(
      "href",
      "/instruments/7",
    );
    const hrefs = within(card)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    for (const t of [
      "p_win",
      "ev",
      "position_pct",
      "horizon",
      "entry_price",
      "take_profit",
      "stop_loss",
      "rank",
      "tier",
    ]) {
      expect(hrefs, t).toContain(`/glossary/${t}`);
    }
  });

  it("shows stop and target as signed distances from the reference price", () => {
    render(<SignalCard s={signal} />);
    expect(screen.getByText(/\+۶٫۰٪/)).toBeInTheDocument();
    expect(screen.getByText(/−۳٫۰٪/)).toBeInTheDocument();
  });

  it("explains reasons in Persian with a fallback to the raw key", () => {
    render(
      <SignalCard
        s={{ ...signal, top_reasons: [{ feature: "weird_x", value: 1, contribution: 0.2 }] }}
      />,
    );
    expect(screen.getByText("weird_x")).toBeInTheDocument();
  });

  it("never promises a return", () => {
    render(<SignalCard s={signal} />);
    const text = screen.getByTestId("signal-card").textContent ?? "";
    for (const banned of ["تضمین", "قطعی", "سود تضمینی", "بدون ریسک"]) {
      expect(text).not.toContain(banned);
    }
  });
});

describe("SignalTable", () => {
  it("shows open signals without a return and closed ones with a gross return", () => {
    render(
      <SignalTable
        items={[
          signal,
          { ...signal, id: 2, date: "2025-02-20", outcome: "tp", realized_return: 0.06 },
        ]}
      />,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("باز")).toBeInTheDocument();
    expect(within(rows[2]).getByText("رسید به حد سود")).toBeInTheDocument();
    expect(within(rows[2]).getByText("+۶٫۰٪")).toBeInTheDocument();
  });
});
