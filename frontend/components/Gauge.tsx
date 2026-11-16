import { faNumber } from "@/lib/format";

const SEGMENTS = 20;
const CX = 100;
const CY = 100;
const R = 78;

const pt = (deg: number, r = R) => {
  const a = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)] as const;
};

/** Where the zones start on the 0-100 scale when the API gave none: the model's configured
 *  hold (top 30%) and buy (top 10%) shares. */
export const DEFAULT_ZONES = { hold: 70, buy: 90 } as const;

const ZONE_HUE = { low: 2, mid: 42, high: 135 } as const;

/** The colour of a point on the scale is the zone it falls in, so the needle sits in the same
 *  colour as the verdict it belongs to (a linear red-to-green ramp showed 60 as "almost good"
 *  while 60 is in the sell zone). */
const zoneHue = (v: number, z: { hold: number; buy: number }) =>
  v >= z.buy ? ZONE_HUE.high : v >= z.hold ? ZONE_HUE.mid : ZONE_HUE.low;

/**
 * Semicircle gauge from 0 (left) to 100 (right) with a needle at `value`. The arc is coloured
 * by decision zone (below `zones.hold` red, up to `zones.buy` amber, then green) and drawn
 * left-to-right in every language direction. `value` null draws a grey, empty gauge.
 */
export function Gauge({
  value,
  label,
  size = "lg",
  zones = DEFAULT_ZONES,
}: {
  value: number | null | undefined;
  label?: string;
  size?: "lg" | "sm";
  zones?: { hold: number; buy: number };
}) {
  const v = value == null ? null : Math.min(100, Math.max(0, value));
  const segs = Array.from({ length: SEGMENTS }, (_, i) => {
    const [x1, y1] = pt(180 - (180 / SEGMENTS) * i);
    const [x2, y2] = pt(180 - (180 / SEGMENTS) * (i + 1));
    return {
      i,
      d: `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    };
  });
  const [nx, ny] = pt(180 - 1.8 * (v ?? 0), R - 14);
  const sm = size === "sm";
  return (
    <svg
      viewBox="0 0 200 132"
      role="img"
      aria-label={
        v == null
          ? (label ?? "امتیازی محاسبه نشده")
          : `${label ?? "امتیاز"}: ${faNumber(v, 0)} از ۱۰۰`
      }
      className={sm ? "h-8 w-14" : "h-auto w-full max-w-64"}
      data-testid="gauge"
      data-value={v == null ? "" : v.toFixed(1)}
    >
      {segs.map((s) => (
        <path
          key={s.i}
          d={s.d}
          fill="none"
          strokeWidth={sm ? 26 : 20}
          stroke={
            v == null ? "var(--color-line, #888)" : `hsl(${zoneHue(((s.i + 0.5) / SEGMENTS) * 100, zones)} 70% 42%)`
          }
          opacity={v == null ? 0.5 : 1}
        />
      ))}
      {v != null && (
        <>
          <line
            x1={CX}
            y1={CY}
            x2={nx.toFixed(2)}
            y2={ny.toFixed(2)}
            stroke="currentColor"
            strokeWidth={sm ? 9 : 5}
            strokeLinecap="round"
          />
          <circle cx={CX} cy={CY} r={sm ? 12 : 8} fill="currentColor" />
        </>
      )}
      {!sm && (
        <>
          <text
            x={CX}
            y={CY + 30}
            textAnchor="middle"
            fontSize="26"
            fontWeight="800"
            fill="currentColor"
          >
            {v == null ? "—" : faNumber(v, 0)}
          </text>
          <text x={CX - R} y={CY + 14} textAnchor="middle" fontSize="10" className="fill-bad">
            ضعیف
          </text>
          <text x={CX + R} y={CY + 14} textAnchor="middle" fontSize="10" className="fill-good">
            قوی
          </text>
        </>
      )}
    </svg>
  );
}
