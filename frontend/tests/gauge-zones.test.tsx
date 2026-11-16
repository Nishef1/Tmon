import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Gauge } from "@/components/Gauge";

const hues = (zones?: { hold: number; buy: number }) =>
  Array.from(
    render(<Gauge value={60} zones={zones} />).container.querySelectorAll("path"),
    (p) => Number(/hsl\((\d+)/.exec(p.getAttribute("stroke") ?? "")?.[1]),
  );

describe("Gauge zones", () => {
  it("colours the arc by decision zone, not by a linear ramp", () => {
    const h = hues({ hold: 70, buy: 90 });
    expect(h).toHaveLength(20);
    expect(new Set(h.slice(0, 14)).size).toBe(1); // 0-70 one red
    expect(new Set(h.slice(14, 18)).size).toBe(1); // 70-90 one amber
    expect(new Set(h.slice(18)).size).toBe(1); // 90-100 one green
    expect(new Set(h).size).toBe(3);
  });

  it("follows zones given by the API", () => {
    const h = hues({ hold: 50, buy: 80 });
    expect(h[9]).not.toBe(h[10]); // boundary at 50
  });
});
