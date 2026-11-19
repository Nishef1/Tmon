import { describe, expect, it } from "vitest";
import {
  rideLevels,
  rideMarks,
  ridePaths,
  rideWarning,
  type Ride,
} from "@/components/stock/rideMarks";

const ride = {
  rides: [{ entry_date: "2025-05-24", exit_date: null, gain: 9.79 }],
  swings: [
    { date: "2022-11-01", kind: "low", close: 912 },
    { date: "2023-05-03", kind: "high", close: 2534 },
    { date: "2025-03-18", kind: "low", close: 1123 },
  ],
} as unknown as Ride;

describe("rideMarks", () => {
  it("marks the rule's buys and the hindsight lows and highs on the chart", () => {
    const m = rideMarks(ride, "2023-01-01");
    expect(m.map((x) => [x.time, x.text])).toEqual([
      ["2025-05-24", "روند خرید"],
      ["2023-05-03", "سقف"],
      ["2025-03-18", "کف"],
    ]);
    expect(m.find((x) => x.text === "سقف")?.above).toBe(true);
    expect(m.find((x) => x.text === "کف")?.shape).toBe("circle");
  });
});

describe("ride warning band", () => {
  const open = {
    status: "open",
    stop: 100,
    last_close: 102,
    warn_band: 0.03,
    sell_line: [
      { date: "2026-11-15", value: 100 },
      { date: "2026-11-17", value: null },
    ],
    buy_line: [],
  } as unknown as Ride;

  it("warns of a sale when the close is within the band above the sell line", () => {
    expect(rideWarning(open)).toEqual({ side: "sell", move: expect.closeTo(0.02) });
    expect(rideWarning({ ...open, last_close: 104 })).toBeNull();
  });

  it("warns of a buy when the needed rise is within the band", () => {
    const closed = { ...open, status: "closed", stop: null, buy_trigger: 102, last_close: 100 };
    expect(rideWarning(closed as Ride)).toEqual({ side: "buy", move: expect.closeTo(0.02) });
    expect(rideLevels(closed as Ride)).toEqual([
      { price: 102, title: "قیمت ورود فردا", color: "var(--up)" },
    ]);
  });

  it("draws the sell line with its band edge and keeps the gap", () => {
    const [line, edge] = ridePaths(open);
    expect(line.points).toEqual([
      { time: "2026-11-15", value: 100 },
      { time: "2026-11-17", value: null },
    ]);
    expect(edge.dotted).toBe(true);
    expect(edge.points[0].value).toBeCloseTo(103);
  });
});
