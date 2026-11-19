import { describe, expect, it } from "vitest";
import { colTone, fmtCol, isSigned } from "@/lib/columns";
import { sortRows, type Row } from "@/lib/industry";

const pct = { key: "ret_1m", group: "returns", kind: "percent" };
const multiple = { key: "pe_ttm", group: "valuation", kind: "multiple" };
const score = { key: "tech_score", group: "scores", kind: "score" };

describe("fmtCol", () => {
  it("shows a dash for a missing value", () => {
    expect(fmtCol(pct, null)).toBe("—");
    expect(fmtCol(pct, undefined)).toBe("—");
  });

  it("writes the decimal mark of a multiple as a dot", () => {
    const out = fmtCol(multiple, 9.6);
    expect(out).toContain(".");
    expect(out).not.toContain("٫");
  });

  it("signs returns but not valuation multiples", () => {
    expect(isSigned(pct)).toBe(true);
    expect(isSigned(multiple)).toBe(false);
  });

  it("writes a score as a count out of a hundred", () => {
    expect(fmtCol(score, 67)).toContain("از");
  });

  it("gives no tone to an empty value", () => {
    expect(colTone(pct, null)).toBe("");
  });
});

describe("sorting by a derived column", () => {
  const base = { x: {} } as unknown as Row;
  const rows = [
    { ...base, symbol: "a", x: { pe_ttm: 12 } },
    { ...base, symbol: "b", x: {} },
    { ...base, symbol: "c", x: { pe_ttm: 5 } },
  ] as Row[];

  it("orders ascending and puts symbols without the value last", () => {
    expect(sortRows(rows, "x:pe_ttm", 1).map((r) => r.symbol)).toEqual(["c", "a", "b"]);
  });

  it("orders descending and still puts the empty one last", () => {
    expect(sortRows(rows, "x:pe_ttm", -1).map((r) => r.symbol)).toEqual(["a", "c", "b"]);
  });
});
