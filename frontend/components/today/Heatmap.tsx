import Link from "next/link";
import type { RankingRow } from "@/lib/api";
import { faPercent } from "@/lib/format";

type Tile = { r: RankingRow; w: number };
type Box = { x: number; y: number; w: number; h: number; r: RankingRow };

/** Split the tiles into two groups of about equal weight and recurse, cutting the longer side. */
function layout(tiles: Tile[], x: number, y: number, w: number, h: number, out: Box[]): void {
  if (tiles.length === 0) return;
  if (tiles.length === 1) {
    out.push({ x, y, w, h, r: tiles[0].r });
    return;
  }
  const total = tiles.reduce((s, t) => s + t.w, 0);
  let acc = 0;
  let k = 0;
  while (k < tiles.length - 1 && acc + tiles[k].w / 2 < total / 2) acc += tiles[k++].w;
  k = Math.max(1, k);
  const a = tiles.slice(0, k);
  const b = tiles.slice(k);
  const share = a.reduce((s, t) => s + t.w, 0) / total;
  if (w >= h) {
    layout(a, x, y, w * share, h, out);
    layout(b, x + w * share, y, w * (1 - share), h, out);
  } else {
    layout(a, x, y, w, h * share, out);
    layout(b, x, y + h * share, w, h * (1 - share), out);
  }
}

const FULL = 0.04; // a move of 4% or more gets the strongest colour

function colour(c: number | null): { background: string; color: string } {
  if (c == null) return { background: "var(--surface-2)", color: "inherit" };
  const k = Math.min(Math.abs(c) / FULL, 1);
  const base = c >= 0 ? "#1d6a43" : "#a32d2d";
  return {
    background: `color-mix(in srgb, ${base} ${Math.round(15 + k * 85)}%, var(--surface-2))`,
    color: k > 0.45 ? "#fff" : "inherit",
  };
}

function Canvas({
  rows,
  height,
  ratio,
  className,
}: {
  rows: RankingRow[];
  height: number;
  ratio: string;
  className: string;
}) {
  const boxes: Box[] = [];
  layout(
    rows.map((r) => ({ r, w: Math.sqrt(r.median_value ?? 1) })),
    0,
    0,
    100,
    height,
    boxes,
  );
  const k = 100 / height;
  return (
    <div
      className={`relative w-full overflow-hidden rounded-lg ${className}`}
      style={{ aspectRatio: ratio }}
      dir="ltr"
    >
      {boxes.map(({ x, y, w, h, r }) => (
        <Link
          key={r.symbol}
          href={`/instruments/${r.instrument_id}`}
          title={`${r.name ?? r.symbol}${r.change_pct == null ? "" : ` · ${faPercent(r.change_pct, 1, true)}`}`}
          className="absolute flex flex-col items-center justify-center overflow-hidden border border-surface text-center leading-tight"
          style={{
            left: `${x}%`,
            top: `${y * k}%`,
            width: `${w}%`,
            height: `${h * k}%`,
            ...colour(r.change_pct),
          }}
          dir="rtl"
        >
          {w > 6 && h * k > 7 && (
            <span className="text-[11px] font-bold sm:text-xs">{r.symbol}</span>
          )}
          {w > 9 && h * k > 12 && r.change_pct != null && (
            <span className="text-[10px]">{faPercent(r.change_pct, 1, true)}</span>
          )}
        </Link>
      ))}
    </div>
  );
}

/** Today's market as one picture: tile size is how much each stock trades, colour is its move.
 *  Only the most traded names are drawn so every tile stays readable; a phone gets a taller
 *  map with fewer tiles. */
export function Heatmap({ rows }: { rows: RankingRow[] }) {
  const top = rows
    .filter((r) => r.median_value != null && r.median_value > 0 && r.instrument_id != null)
    .sort((a, b) => (b.median_value ?? 0) - (a.median_value ?? 0));
  if (top.length < 5) return null;
  return (
    <section className="card space-y-2" data-testid="heatmap">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">نقشهٔ بازار</h2>
        <span className="text-xs text-muted">اندازه = حجم معاملهٔ معمول · رنگ = تغییر امروز</span>
      </div>
      <Canvas rows={top.slice(0, 30)} height={100} ratio="1 / 1.1" className="sm:hidden" />
      <Canvas rows={top.slice(0, 70)} height={50} ratio="2 / 1" className="hidden sm:block" />
    </section>
  );
}
