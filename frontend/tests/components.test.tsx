import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Disclaimer, DISCLAIMER } from "@/components/Disclaimer";
import { Num } from "@/components/Num";

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
