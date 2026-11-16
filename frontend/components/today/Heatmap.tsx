import Link from "next/link";
import type { RankingRow } from "@/lib/api";
import { faPercent } from "@/lib/format";

type Box = { x: number; y: number; w: number; h: number; r: RankingRow };
type Item = { r: RankingRow; a: number };

/** Worst width/height ratio of a row of areas laid along a side of length `side`. */
function worst(row: Item[], side: number): number {
  const s = row.reduce((t, i) => t + i.a, 0);
  const hi = Math.max(...row.map((i) => i.a));
  const lo = Math.min(...row.map((i) => i.a));
  return Math.max((side * side * hi) / (s * s), (s * s) / (side * side * lo));
}

/** Squarified treemap (Bruls, Huizing, van Wijk): tiles stay close to square so each one has room
 *  for its symbol and its move. Areas must already sum to w*h. */
function squarify(items: Item[], x: number, y: number, w: number, h: number, out: Box[]): void {
  let rest = items;
  while (rest.length > 0) {
    const side = Math.min(w, h);
    let row: Item[] = [rest[0]];
    let k = 1;
    while (k < rest.length && worst([...row, rest[k]], side) <= worst(row, side)) {
      row = [...row, rest[k]];
      k++;
    }
    rest = rest.slice(k);
    const s = row.reduce((t, i) => t + i.a, 0);
    const thick = s / side;
    let off = 0;
    for (const i of row) {
      const len = i.a / thick;
      if (w >= h) out.push({ x, y: y + off, w: thick, h: len, r: i.r });
      else out.push({ x: x + off, y, w: len, h: thick, r: i.r });
      off += len;
    }
    if (w >= h) {
      x += thick;
      w -= thick;
    } else {
      y += thick;
      h -= thick;
    }
  }
}

const FULL = 0.05; // a move of 5% or more gets the strongest colour

/** Grey near zero, then deeper green or red as the move grows. */
function colour(c: number | null): string {
  if (c == null) return "var(--surface-2)";
  const k = Math.min(Math.abs(c) / FULL, 1) ** 0.7;
  const hue = c >= 0 ? 152 : 25;
  return `oklch(${(0.5 - k * 0.12).toFixed(3)} ${(0.02 + k * 0.13).toFixed(3)} ${hue})`;
}

function Canvas({
  rows,
  w,
  h,
  className,
}: {
  rows: RankingRow[];
  w: number;
  h: number;
  className: string;
}) {
  const weights = rows.map((r) => Math.sqrt(r.median_value ?? 1));
  const total = weights.reduce((s, v) => s + v, 0);
  const boxes: Box[] = [];
  squarify(
    rows.map((r, i) => ({ r, a: (weights[i] / total) * w * h })),
    0,
    0,
    w,
    h,
    boxes,
  );
  return (
    <div
      className={`relative w-full overflow-hidden rounded-xl ${className}`}
      style={{ aspectRatio: `${w} / ${h}` }}
    >
      {boxes.map(({ x, y, w: bw, h: bh, r }) => (
        <Link
          key={r.symbol}
          href={`/instruments/${r.instrument_id}`}
          title={`${r.symbol} · ${r.name ?? ""}${r.change_pct == null ? "" : ` · ${faPercent(r.change_pct, 2, true)}`}`}
          className="hm-tile absolute p-px"
          style={{
            right: `${(x / w) * 100}%`,
            top: `${(y / h) * 100}%`,
            width: `${(bw / w) * 100}%`,
            height: `${(bh / h) * 100}%`,
          }}
        >
          <span className="hm-face" style={{ background: colour(r.change_pct) }}>
            <span className="hm-sym">{r.symbol}</span>
            {r.change_pct != null && (
              <span className="hm-pct" dir="ltr">
                {faPercent(r.change_pct, 1, true)}
              </span>
            )}
          </span>
        </Link>
      ))}
    </div>
  );
}

/** Today's market as one picture: tile size is how much each stock usually trades, colour is
 *  today's move. Text scales with the tile; a tile too small for its move shows the symbol only,
 *  and the full move is in the tooltip. */
export function Heatmap({ rows }: { rows: RankingRow[] }) {
  const top = rows
    .filter((r) => r.median_value != null && r.median_value > 0 && r.instrument_id != null)
    .sort((a, b) => (b.median_value ?? 0) - (a.median_value ?? 0));
  if (top.length < 5) return null;
  return (
    <section className="card space-y-3" data-testid="heatmap">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">نقشهٔ بازار</h2>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span>اندازه: معاملهٔ معمول</span>
          <span className="hm-legend" aria-hidden />
          <span dir="ltr">−۵٪ … +۵٪</span>
        </div>
      </div>
      <Canvas rows={top.slice(0, 36)} w={100} h={120} className="sm:hidden" />
      <Canvas rows={top.slice(0, 80)} w={200} h={100} className="hidden sm:block" />
    </section>
  );
}
