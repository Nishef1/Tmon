import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GlossarySearch, type GlossaryItem } from "@/components/GlossarySearch";
import { execFileSync } from "node:child_process";
import { allPlaces, placesFor } from "@/lib/glossary-places";

const ITEMS: GlossaryItem[] = [
  {
    key: "brier",
    fa: "نمرهٔ بریر",
    en: "Brier score",
    category: "model",
    categoryLabel: "مدل",
    text: "خطای پیش‌بینی احتمال",
    plain: "نمرهٔ خطا",
  },
  {
    key: "drawdown",
    fa: "افت از اوج",
    en: "Drawdown",
    category: "risk",
    categoryLabel: "ریسک",
    text: "بیشترین افت سرمایه",
    plain: "بدترین افت",
  },
];

describe("GlossarySearch", () => {
  it("lists every term before typing and filters by Persian or English name", () => {
    render(<GlossarySearch items={ITEMS} />);
    expect(screen.getAllByRole("link")).toHaveLength(2);
    const box = screen.getByTestId("glossary-search");
    fireEvent.change(box, { target: { value: "brier" } });
    expect(screen.getAllByRole("link")).toHaveLength(1);
    fireEvent.change(box, { target: { value: "افت" } });
    expect(screen.getByText("افت از اوج")).toBeTruthy();
    expect(screen.queryByText("نمرهٔ بریر")).toBeNull();
  });

  it("treats Arabic ي and ك like Persian ی and ک and says when nothing matches", () => {
    render(<GlossarySearch items={ITEMS} />);
    const box = screen.getByTestId("glossary-search");
    fireEvent.change(box, { target: { value: "بيشترين" } });
    expect(screen.getAllByRole("link")).toHaveLength(1);
    fireEvent.change(box, { target: { value: "zzzz" } });
    expect(screen.getByText("واژه‌ای با این نام پیدا نشد.")).toBeTruthy();
  });
});

describe("glossary places", () => {
  it("is generated from the source and every place is a real page link", () => {
    const places = allPlaces();
    expect(Object.keys(places).length).toBeGreaterThan(10);
    for (const list of Object.values(places)) {
      expect(list.length).toBeGreaterThan(0);
      for (const p of list) expect(p.href.startsWith("/")).toBe(true);
    }
    expect(placesFor("no_such_term")).toEqual([]);
  });

  it("matches the committed file (run node scripts/glossary-places.mjs when this fails)", () => {
    expect(() =>
      execFileSync("node", ["scripts/glossary-places.mjs", "--check"], { stdio: "pipe" }),
    ).not.toThrow();
  });
});
