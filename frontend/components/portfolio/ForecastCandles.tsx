import { faNumber } from "@/lib/format";
import type { Band } from "@/lib/portfolio";

export type CandleItem = { key: string; label: string; band: Band; sub?: string };

const pct = (x: number) => `${x >= 0 ? "+" : ""}${faNumber(x * 100, 0)}٪`;

/** Forecast ranges drawn like candles: the wick is the min..max (1st..99th percentile), the body
 *  the 80% band, the tick the median; green when the median is a gain. One shared zero line. */
export function ForecastCandles({ items, title }: { items: CandleItem[]; title: string }) {
  if (items.length === 0) return null;
  const W = Math.max(320, items.length * 84);
  const H = 220;
  const pad = { t: 14, b: 40, l: 8, r: 62 };
  const lo = Math.min(0, ...items.map((i) => i.band.q01 ?? i.band.q05));
  const hi = Math.max(0, ...items.map((i) => i.band.q99 ?? i.band.q95));
  const span = hi - lo || 1;
  const y = (v: number) => pad.t + ((hi - v) / span) * (H - pad.t - pad.b);
  const step = (W - pad.l - pad.r) / items.length;
  const ticks = [0, lo, hi, lo / 2, hi / 2].filter(
    (v, k, a) => a.findIndex((u) => Math.abs(u - v) < span * 0.08) === k,
  );
  return (
    <figure className="mt-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full max-w-3xl"
        role="img"
        aria-label={title}
        style={{ direction: "ltr" }}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line
              x1={pad.l}
              x2={W - pad.r}
              y1={y(v)}
              y2={y(v)}
              stroke={v === 0 ? "var(--line-strong)" : "var(--line-soft)"}
              strokeDasharray={v === 0 ? undefined : "3 3"}
            />
            <text
              x={W - pad.r + 4}
              y={y(v) + 4}
              fontSize="11"
              fill="var(--muted)"
              style={{ direction: "ltr", unicodeBidi: "plaintext" }}
            >
              {pct(v)}
            </text>
          </g>
        ))}
        {items.map((it, k) => {
          const b = it.band;
          const cx = pad.l + step * (k + 0.5);
          const bw = Math.min(30, step * 0.42);
          const up = (b.q50 ?? 0) >= 0;
          const color = up ? "var(--up)" : "var(--down)";
          const soft = up ? "var(--up-soft)" : "var(--down-soft)";
          const top = y(b.q90);
          const bottom = y(b.q10);
          return (
            <g key={it.key}>
              <title>
                {`${it.label}: کمینه ${pct(b.q01 ?? b.q05)}، بازهٔ ۸۰٪ ${pct(b.q10)} تا ${pct(b.q90)}، میانه ${pct(b.q50)}، بیشینه ${pct(b.q99 ?? b.q95)}`}
              </title>
              <line
                x1={cx}
                x2={cx}
                y1={y(b.q99 ?? b.q95)}
                y2={y(b.q01 ?? b.q05)}
                stroke={color}
                strokeWidth="1.5"
              />
              <rect
                x={cx - bw / 2}
                y={top}
                width={bw}
                height={Math.max(2, bottom - top)}
                fill={soft}
                stroke={color}
                strokeWidth="1.5"
                rx="2"
              />
              <line
                x1={cx - bw / 2}
                x2={cx + bw / 2}
                y1={y(b.q50)}
                y2={y(b.q50)}
                stroke={color}
                strokeWidth="2.5"
              />
              <text
                x={cx}
                y={H - pad.b + 16}
                fontSize="12"
                textAnchor="middle"
                fill="var(--ink, currentColor)"
                style={{ direction: "rtl" }}
              >
                {it.label}
              </text>
              {it.sub && (
                <text
                  x={cx}
                  y={H - pad.b + 31}
                  fontSize="10.5"
                  textAnchor="middle"
                  fill="var(--muted)"
                  style={{ direction: "rtl" }}
                >
                  {it.sub}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="text-xs text-muted">
        فتیله: کمینه تا بیشینه (صدک ۱ و ۹۹) · بدنه: بازهٔ ۸۰٪ (با خطای آزموده) · خط: میانه
      </figcaption>
    </figure>
  );
}
