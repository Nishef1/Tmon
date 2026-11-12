import { describe, expect, it } from "vitest";
import {
  EMPTY,
  applyFilters,
  byRelevance,
  gaugeWhy,
  industries,
  norm,
  searchScore,
  sortRows,
  type Row,
} from "@/lib/industry";

const base: Row = {
  id: 0,
  symbol: "",
  name: "",
  sector: "ص",
  verdict: "none",
  verdictLabel: "",
  gauge: null,
  gaugeNote: null,
  close: 1000,
  day: 0,
  week: null,
  month: null,
  m3: null,
  year: null,
  fromHigh: null,
  fromLow: null,
  value: 0,
  volume: 0,
  cap: 0,
  pe: null,
  sectorPe: null,
  eps: null,
  power: null,
  netReal: null,
  volRatio: null,
  rsi: null,
  meeting: null,
  rank: null,
  perBuy: null,
  perSell: null,
};
const row = (o: Partial<Row>): Row => ({ ...base, ...o });

const ROWS = [
  row({
    id: 1,
    symbol: "فولاد",
    name: "فولاد مبارکه اصفهان",
    sector: "فلزات اساسی",
    value: 9e11,
    cap: 5e13,
    day: 0.02,
    year: 1.2,
    verdict: "buy",
    gauge: 90,
    pe: 5,
  }),
  row({
    id: 2,
    symbol: "فولای",
    name: "فولاد آلیاژی ایران",
    sector: "فلزات اساسی",
    value: 1e11,
    cap: 1e13,
    day: -0.01,
    year: 0.5,
    verdict: "sell",
    gauge: 20,
    pe: 12,
  }),
  row({
    id: 3,
    symbol: "خودرو",
    name: "ايران خودرو",
    sector: "خودرو",
    value: 5e11,
    cap: 2e13,
    day: 0.03,
    year: 0.1,
    power: 1.4,
    netReal: 5e9,
  }),
  row({
    id: 4,
    symbol: "شپنا",
    name: "پالایش نفت اصفهان",
    sector: "فراورده‌های نفتی",
    value: 2e11,
    cap: 3e13,
    day: 0,
    netReal: -1e9,
  }),
];

describe("norm", () => {
  it("folds Arabic letters, ZWNJ, diacritics and digit scripts", () => {
    expect(norm("ايران كیش")).toBe("ایران کیش");
    expect(norm("فراورده‌های")).toBe("فرآوردههای".replace("آ", "ا"));
    expect(norm("وبملت۲ ٣")).toBe("وبملت2 3");
  });
});

describe("search", () => {
  it("finds a symbol prefix, a name word, the industry and similar spellings", () => {
    expect(searchScore(ROWS[0], "فول")).toBeGreaterThan(0);
    expect(searchScore(ROWS[0], "مبارکه")).toBeGreaterThan(0);
    expect(searchScore(ROWS[0], "فلزات")).toBeGreaterThan(0);
    expect(searchScore(ROWS[2], "ایران خودرو")).toBeGreaterThan(0); // Arabic yeh in the data
    expect(searchScore(ROWS[0], "فولاک")).not.toBeNull(); // one letter off
    expect(searchScore(ROWS[2], "فولاد")).toBeNull();
  });
  it("needs every word and ranks the exact symbol first", () => {
    expect(searchScore(ROWS[0], "فولاد اصفهان")).not.toBeNull();
    expect(searchScore(ROWS[1], "فولاد اصفهان")).toBeNull();
    expect(byRelevance(ROWS, "فولای")[0].symbol).toBe("فولای");
  });
});

describe("filters", () => {
  const today = new Date("2026-11-12T00:00:00Z");
  it("returns everything with no filter", () => {
    expect(applyFilters(ROWS, EMPTY, today)).toHaveLength(4);
  });
  it("filters by verdict, industry, range and flags; a missing number never passes", () => {
    expect(applyFilters(ROWS, { ...EMPTY, verdicts: ["buy"] }, today).map((r) => r.id)).toEqual([
      1,
    ]);
    expect(applyFilters(ROWS, { ...EMPTY, sectors: ["خودرو"] }, today).map((r) => r.id)).toEqual([
      3,
    ]);
    expect(applyFilters(ROWS, { ...EMPTY, year: { min: 1 } }, today).map((r) => r.id)).toEqual([1]);
    expect(applyFilters(ROWS, { ...EMPTY, pe: { max: 10 } }, today).map((r) => r.id)).toEqual([1]);
    expect(applyFilters(ROWS, { ...EMPTY, netBuyers: true }, today).map((r) => r.id)).toEqual([3]);
    expect(applyFilters(ROWS, { ...EMPTY, powerAbove1: true }, today).map((r) => r.id)).toEqual([
      3,
    ]);
    expect(applyFilters(ROWS, { ...EMPTY, minValue: 4e11 }, today).map((r) => r.id)).toEqual([
      1, 3,
    ]);
    expect(
      applyFilters(ROWS, { ...EMPTY, q: "فولاد", sectors: ["فلزات اساسی"] }, today),
    ).toHaveLength(2);
  });
  it("meeting within 30 days", () => {
    const rs = [
      row({ id: 1, meeting: "2026-11-20" }),
      row({ id: 2, meeting: "2026-12-30" }),
      row({ id: 3 }),
    ];
    expect(applyFilters(rs, { ...EMPTY, meetingSoon: true }, today).map((r) => r.id)).toEqual([1]);
  });
});

describe("industries", () => {
  it("ranks by traded value, with cap-weighted returns and verdict counts", () => {
    const list = industries(ROWS);
    expect(list.map((i) => i.name)).toEqual(["فلزات اساسی", "خودرو", "فراورده‌های نفتی"]);
    const metals = list[0];
    expect(metals.value).toBe(1e12);
    expect(metals.count).toBe(2);
    expect(metals.verdicts).toMatchObject({ buy: 1, sell: 1 });
    expect(metals.day).toBeCloseTo((0.02 * 5e13 + -0.01 * 1e13) / 6e13, 10);
    expect(metals.gauge).toBe(55);
    expect(industries(ROWS, "cap").map((i) => i.name)[0]).toBe("فلزات اساسی");
    expect(industries(ROWS, "day").map((i) => i.name)[0]).toBe("خودرو");
  });
});

describe("sortRows", () => {
  it("puts rows without the number last in both directions", () => {
    const rs = [row({ id: 1, year: null }), row({ id: 2, year: 0.5 }), row({ id: 3, year: 1.5 })];
    expect(sortRows(rs, "year", -1).map((r) => r.id)).toEqual([3, 2, 1]);
    expect(sortRows(rs, "year", 1).map((r) => r.id)).toEqual([2, 3, 1]);
  });
});

describe("gaugeWhy", () => {
  it("names the reason in a few words", () => {
    expect(gaugeWhy("امتیازی محاسبه نشد: در آخرین روز معامله نشده است.")).toBe("امروز معامله نشده");
    expect(gaugeWhy("دادهٔ لازم برای محاسبهٔ امتیاز کامل نیست")).toBe("سابقهٔ کافی ندارد");
    expect(gaugeWhy(null)).toBe("بی‌امتیاز");
  });
});
