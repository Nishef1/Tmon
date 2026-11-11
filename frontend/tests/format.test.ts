import { describe, expect, it } from "vitest";
import { faNumber, faPercent, faPrice, formatValue, jalali } from "@/lib/format";

describe("number formatting", () => {
  it("uses Persian digits and separators", () => {
    expect(faNumber(1234567)).toBe("۱٬۲۳۴٬۵۶۷");
    expect(faNumber(3.14159, 2)).toBe("۳٫۱۴");
  });

  it("formats percentages with an explicit sign when asked", () => {
    expect(faPercent(0.66, 0)).toBe("۶۶٪");
    expect(faPercent(0.031, 1, true)).toBe("+۳٫۱٪");
    expect(faPercent(-0.03, 1)).toBe("−۳٫۰٪");
  });

  it("never shows a signed zero", () => {
    expect(faPercent(0.00001, 1, true)).toBe("۰٫۰٪");
    expect(faPercent(-0.00001, 1)).toBe("۰٫۰٪");
  });

  it("rounds prices to whole rials", () => {
    expect(faPrice(1000.4)).toBe("۱٬۰۰۰");
  });

  it("renders missing values as a dash, never as zero", () => {
    expect(formatValue(null, "percent")).toBe("—");
    expect(formatValue(undefined, "price")).toBe("—");
    expect(formatValue(Number.NaN, "plain")).toBe("—");
  });
});

describe("Jalali dates", () => {
  it("converts a Gregorian date to the Persian calendar", () => {
    // 2025-03-21 is 1 Farvardin 1404 (Nowruz)
    expect(jalali("2025-03-21", "long")).toBe("۱ فروردین ۱۴۰۴");
  });

  it("keeps the calendar day stable for date-only values", () => {
    expect(jalali("2025-03-20", "long")).toBe("۳۰ اسفند ۱۴۰۳");
  });

  it("handles missing and invalid input", () => {
    expect(jalali(null)).toBe("—");
    expect(jalali("not-a-date")).toBe("—");
  });
});
