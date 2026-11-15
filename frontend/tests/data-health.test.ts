import { describe as suite, expect, it } from "vitest";
import { describe } from "@/lib/data-health";
import { faNumber } from "@/lib/format";

const base = { first_seen: null, date: "2026-11-14" } as const;

suite("data health wording", () => {
  it("states both row counts and the shortfall for a partial day", () => {
    const t = describe(
      { ...base, kind: "prices_partial", have: 1212, expected: 2018 },
      "۲۳ آبان",
      faNumber,
    );
    expect(t).toContain(faNumber(1212));
    expect(t).toContain(faNumber(2018));
    expect(t).toContain(faNumber(806));
    expect(t).toContain("قیمت");
  });

  it("names the flows when those are the short ones", () => {
    const t = describe(
      { ...base, kind: "flows_partial", have: 10, expected: 100 },
      "۲۳ آبان",
      faNumber,
    );
    expect(t).toContain("حقیقی و حقوقی");
  });

  it("says a pending day is simply not fetched yet", () => {
    const t = describe(
      { ...base, kind: "today_pending", have: null, expected: null },
      "۲۴ آبان",
      faNumber,
    );
    expect(t).toContain("هنوز دریافت نشده");
  });
});
