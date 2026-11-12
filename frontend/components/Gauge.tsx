import { faNumber } from "@/lib/format";

const SEGMENTS = 20;
const CX = 100;
const CY = 100;
const R = 78;

const pt = (deg: number, r = R) => {
  const a = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)] as const;
};

/** Hue 0 (red) .. 130 (green) so the whole half circle runs red -> orange -> yellow -> green. */
const hue = (t: number) => Math.round(130 * t);

/**
 * Semicircle gauge from red (left, 0) to green (right, 100) with a needle at `value`. The
 * arc is drawn left-to-right in every language direction so red is always the weak end.
 * `value` null draws a grey, empty gauge.
 */
export function Gauge({
  value,
  label,
  size = "lg",
}: {
  value: number | null | undefined;
  label?: string;
  size?: "lg" | "sm";
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
            v == null ? "var(--color-line, #888)" : `hsl(${hue((s.i + 0.5) / SEGMENTS)} 70% 45%)`
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
