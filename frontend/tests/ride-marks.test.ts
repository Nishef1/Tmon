import { describe, expect, it } from "vitest";
import { rideMarks, type Ride } from "@/components/stock/rideMarks";

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
