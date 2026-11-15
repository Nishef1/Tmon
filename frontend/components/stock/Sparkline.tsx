import type { Candle } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";

/** The last ~30 closes as one thin line, so the header says where the price has been, not only
 *  where it is. Direction is also written as text (the end-to-end change), never colour alone. */
export function Sparkline({ candles, days = 30 }: { candles: Candle[]; days?: number }) {
  const xs = candles
    .slice(-days)
    .map((c) => c.close)
    .filter((v): v is number => v != null);
  if (xs.length < 5) return null;
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const W = 120;
  const H = 36;
  const span = hi - lo || 1;
  // time runs left to right, like the candle chart (the figure is dir=ltr)
  const pts = xs.map(
    (v, i) =>
      `${((i / (xs.length - 1)) * W).toFixed(1)},${(H - 3 - ((v - lo) / span) * (H - 6)).toFixed(1)}`,
  );
  const change = xs[xs.length - 1] / xs[0] - 1;
  const up = change >= 0;
  return (
    <figure
      className="flex items-center gap-2"
      data-testid="sparkline"
      dir="ltr"
      aria-label={`روند ${faNumber(xs.length)} روز اخیر: ${faPercent(change, 1, true)}`}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-hidden>
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke={up ? "var(--up)" : "var(--down)"}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle
          cx={W}
          cy={pts[pts.length - 1].split(",")[1]}
          r="3"
          fill={up ? "var(--up)" : "var(--down)"}
        />
      </svg>
      <figcaption className="text-xs leading-tight text-muted" dir="rtl">
        <span className={`block text-sm font-bold ${up ? "text-up" : "text-down"}`}>
          {faPercent(change, 1, true)}
        </span>
        {faNumber(xs.length)} روز اخیر
      </figcaption>
    </figure>
  );
}
