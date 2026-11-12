// Logic of the industries page: Persian-aware search, filters and per-industry totals.
// Pure functions, so the page's behaviour is testable without a browser.

import type { ScreenerRow } from "./api";

export type Verdict = "buy" | "hold" | "sell" | "none";

/** One stock, flattened from the screener row to what the table needs. */
export type Row = {
  id: number;
  symbol: string;
  name: string;
  sector: string;
  verdict: Verdict;
  verdictLabel: string;
  gauge: number | null;
  gaugeNote: string | null;
  close: number | null;
  day: number | null;
  week: number | null;
  month: number | null;
  m3: number | null;
  year: number | null;
  fromHigh: number | null;
  fromLow: number | null;
  value: number | null;
  volume: number | null;
  cap: number | null;
  pe: number | null;
  sectorPe: number | null;
  eps: number | null;
  power: number | null;
  netReal: number | null;
  volRatio: number | null;
  rsi: number | null;
  meeting: string | null;
};

export const NO_SECTOR = "بدون گروه صنعتی";

export function toRow(r: ScreenerRow): Row {
  return {
    id: r.instrument.id,
    symbol: r.instrument.symbol,
    name: r.instrument.name ?? "",
    sector: r.sector_name || NO_SECTOR,
    verdict: r.verdict,
    verdictLabel: r.verdict_label,
    gauge: r.gauge ?? null,
    gaugeNote: r.gauge_note ?? null,
    close: r.close ?? null,
    day: r.change_pct ?? null,
    week: r.ret_week ?? null,
    month: r.ret_month ?? null,
    m3: r.ret_3m ?? null,
    year: r.ret_year ?? null,
    fromHigh: r.from_year_high ?? null,
    fromLow: r.from_year_low ?? null,
    value: r.value ?? null,
    volume: r.volume ?? null,
    cap: r.market_cap ?? null,
    pe: r.pe ?? null,
    sectorPe: r.sector_pe ?? null,
    eps: r.eps ?? null,
    power: r.power ?? null,
    netReal: r.net_real_value ?? null,
    volRatio: r.volume_ratio_30 ?? null,
    rsi: r.rsi_14 ?? null,
    meeting: r.meeting_date ?? null,
  };
}

// ---------------------------------------------------------------------------------- search

/** Arabic letter forms, ZWNJ, diacritics and every digit script folded to one spelling. */
export function norm(text: string): string {
  return text
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[ۀة]/g, "ه")
    .replace(/[أإآ]/g, "ا")
    .replace(/[‌‏‎ً-ٰٟـ]/g, "")
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x6f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x660))
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function distance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

const CACHE = new WeakMap<Row, { sym: string; name: string; sector: string }>();

function keys(row: Row) {
  let k = CACHE.get(row);
  if (!k) {
    k = { sym: norm(row.symbol), name: norm(row.name), sector: norm(row.sector) };
    CACHE.set(row, k);
  }
  return k;
}

/**
 * How well one typed word matches a stock: symbol prefix, then symbol/name/industry contains,
 * then a near-miss spelling of the symbol (one letter off) so similar symbols still show up.
 * ``null`` = no match.
 */
function tokenScore(row: Row, token: string): number | null {
  const { sym, name, sector } = keys(row);
  if (sym === token) return 100;
  if (sym.startsWith(token)) return 90;
  if (sym.includes(token)) return 70;
  if (name.split(" ").some((w) => w.startsWith(token))) return 60;
  if (name.includes(token)) return 50;
  if (sector.includes(token)) return 30;
  if (token.length >= 3) {
    const d = Math.min(
      distance(sym, token, 1),
      sym.length > token.length ? distance(sym.slice(0, token.length), token, 1) : 9,
    );
    if (d <= 1) return 10;
  }
  return null;
}

/** Score of a whole query (every word must match); ``null`` when some word matches nothing. */
export function searchScore(row: Row, query: string): number | null {
  const tokens = norm(query).split(" ").filter(Boolean);
  if (tokens.length === 0) return 0;
  let total = 0;
  for (const t of tokens) {
    const s = tokenScore(row, t);
    if (s == null) return null;
    total += s;
  }
  return total;
}

// --------------------------------------------------------------------------------- filters

export type Range = { min?: number; max?: number };

export type Filters = {
  q: string;
  verdicts: Verdict[]; // empty = all
  sectors: string[]; // empty = all
  day: Range; // fractions: 0.05 = 5 %
  week: Range;
  month: Range;
  year: Range;
  pe: Range;
  gauge: Range; // 0..100
  minValue?: number; // rial traded on the last day
  minCap?: number; // rial
  powerAbove1: boolean;
  netBuyers: boolean; // net real-money inflow > 0
  nearHigh: boolean; // within 10 % of the year high
  meetingSoon: boolean; // assembly within 30 days
};

export const EMPTY: Filters = {
  q: "",
  verdicts: [],
  sectors: [],
  day: {},
  week: {},
  month: {},
  year: {},
  pe: {},
  gauge: {},
  powerAbove1: false,
  netBuyers: false,
  nearHigh: false,
  meetingSoon: false,
};

const within = (v: number | null, r: Range): boolean => {
  if (r.min == null && r.max == null) return true;
  if (v == null) return false; // a missing number never passes a numeric filter
  return (r.min == null || v >= r.min) && (r.max == null || v <= r.max);
};

export function activeCount(f: Filters): number {
  let n = f.q.trim() ? 1 : 0;
  n += f.verdicts.length ? 1 : 0;
  n += f.sectors.length ? 1 : 0;
  for (const r of [f.day, f.week, f.month, f.year, f.pe, f.gauge])
    n += r.min != null || r.max != null ? 1 : 0;
  n += f.minValue != null ? 1 : 0;
  n += f.minCap != null ? 1 : 0;
  n += [f.powerAbove1, f.netBuyers, f.nearHigh, f.meetingSoon].filter(Boolean).length;
  return n;
}

export function applyFilters(rows: Row[], f: Filters, today: Date): Row[] {
  const soon = new Date(today.getTime() + 30 * 86_400_000).toISOString().slice(0, 10);
  const now = today.toISOString().slice(0, 10);
  const out: Row[] = [];
  for (const r of rows) {
    if (f.verdicts.length && !f.verdicts.includes(r.verdict)) continue;
    if (f.sectors.length && !f.sectors.includes(r.sector)) continue;
    if (!within(r.day, f.day) || !within(r.week, f.week)) continue;
    if (!within(r.month, f.month) || !within(r.year, f.year)) continue;
    if (!within(r.pe, f.pe) || !within(r.gauge, f.gauge)) continue;
    if (f.minValue != null && (r.value ?? 0) < f.minValue) continue;
    if (f.minCap != null && (r.cap ?? 0) < f.minCap) continue;
    if (f.powerAbove1 && !(r.power != null && r.power >= 1)) continue;
    if (f.netBuyers && !(r.netReal != null && r.netReal > 0)) continue;
    if (f.nearHigh && !(r.fromHigh != null && r.fromHigh >= -0.1)) continue;
    if (f.meetingSoon && !(r.meeting != null && r.meeting >= now && r.meeting <= soon)) continue;
    if (f.q.trim() && searchScore(r, f.q) == null) continue;
    out.push(r);
  }
  return out;
}

// -------------------------------------------------------------------------------- industries

export type Industry = {
  name: string;
  count: number;
  value: number; // rial traded on the last day
  volume: number; // shares traded
  cap: number; // market capitalisation, rial
  netReal: number; // net real-money inflow, rial
  day: number | null; // return of the industry, weighted by market cap
  week: number | null;
  month: number | null;
  m3: number | null;
  year: number | null;
  gauge: number | null; // mean score of the scored stocks
  verdicts: Record<Verdict, number>;
  rows: Row[];
};

function weighted(rows: Row[], pick: (r: Row) => number | null): number | null {
  let sum = 0;
  let weight = 0;
  for (const r of rows) {
    const v = pick(r);
    if (v == null) continue;
    const w = r.cap && r.cap > 0 ? r.cap : 1;
    sum += v * w;
    weight += w;
  }
  return weight > 0 ? sum / weight : null;
}

export type IndustrySort = "value" | "volume" | "cap" | "day" | "week" | "month" | "year" | "count";

export function industries(rows: Row[], by: IndustrySort = "value"): Industry[] {
  const groups = new Map<string, Row[]>();
  for (const r of rows) groups.set(r.sector, [...(groups.get(r.sector) ?? []), r]);
  const list: Industry[] = [];
  for (const [name, rs] of groups) {
    const scored = rs.filter((r) => r.gauge != null);
    const verdicts: Record<Verdict, number> = { buy: 0, hold: 0, sell: 0, none: 0 };
    for (const r of rs) verdicts[r.verdict] += 1;
    list.push({
      name,
      count: rs.length,
      value: rs.reduce((a, r) => a + (r.value ?? 0), 0),
      volume: rs.reduce((a, r) => a + (r.volume ?? 0), 0),
      cap: rs.reduce((a, r) => a + (r.cap ?? 0), 0),
      netReal: rs.reduce((a, r) => a + (r.netReal ?? 0), 0),
      day: weighted(rs, (r) => r.day),
      week: weighted(rs, (r) => r.week),
      month: weighted(rs, (r) => r.month),
      m3: weighted(rs, (r) => r.m3),
      year: weighted(rs, (r) => r.year),
      gauge: scored.length ? scored.reduce((a, r) => a + (r.gauge ?? 0), 0) / scored.length : null,
      verdicts,
      rows: rs,
    });
  }
  const key = (i: Industry): number => (i[by] ?? -Infinity) as number;
  return list.sort((a, b) => key(b) - key(a) || a.name.localeCompare(b.name, "fa"));
}

// ------------------------------------------------------------------------------------ sorting

export type SortKey = keyof Pick<
  Row,
  | "symbol"
  | "gauge"
  | "close"
  | "day"
  | "week"
  | "month"
  | "m3"
  | "year"
  | "fromHigh"
  | "value"
  | "volume"
  | "cap"
  | "pe"
  | "eps"
  | "power"
  | "netReal"
  | "volRatio"
  | "rsi"
  | "meeting"
>;

/** ``dir`` 1 = ascending, -1 = descending; rows with no number always go last. */
export function sortRows(rows: Row[], key: SortKey, dir: 1 | -1): Row[] {
  const text = key === "symbol" || key === "meeting";
  return [...rows].sort((a, b) => {
    const x = a[key];
    const y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    const c = text ? String(x).localeCompare(String(y), "fa") : (x as number) - (y as number);
    return dir === 1 ? c : -c;
  });
}

/** Best match first; ties keep the traded-value order. */
export function byRelevance(rows: Row[], query: string): Row[] {
  return [...rows].sort(
    (a, b) =>
      (searchScore(b, query) ?? 0) - (searchScore(a, query) ?? 0) ||
      (b.value ?? 0) - (a.value ?? 0),
  );
}

/** One short phrase for why a stock has no gauge; the full sentence is on its own page. */
export function gaugeWhy(note: string | null): string {
  if (!note) return "بی‌امتیاز";
  if (note.includes("معامله نشده")) return "امروز معامله نشده";
  if (note.includes("دادهٔ لازم") || note.includes("دادهٔ کافی")) return "سابقهٔ کافی ندارد";
  if (note.includes("صف")) return "در صف خرید/فروش";
  return "بی‌امتیاز";
}
