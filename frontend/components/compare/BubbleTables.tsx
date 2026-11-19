"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Right, SymbolValue } from "@/lib/api";
import { faNumber } from "@/lib/format";
import { Num } from "@/components/Num";

type Dir = 1 | -1;
type Sort<K extends string> = { key: K; dir: Dir };

/** Rows with a clean bubble first, then flagged ones, then those without a bubble. */
function trust(bubble: number | null | undefined, note: string | null | undefined): number {
  if (bubble == null) return 2;
  return note ? 1 : 0;
}

function cmp(
  a: number | string | null | undefined,
  b: number | string | null | undefined,
  dir: Dir,
) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "string" || typeof b === "string")
    return String(a).localeCompare(String(b), "fa") * dir;
  return (a - b) * dir;
}

function Head<K extends string>({
  k,
  label,
  sort,
  onSort,
}: {
  k: K;
  label: string;
  sort: Sort<K>;
  onSort: (k: K) => void;
}) {
  const on = sort.key === k;
  return (
    <th
      scope="col"
      aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
      className="whitespace-nowrap"
    >
      <button type="button" onClick={() => onSort(k)} className="font-medium hover:text-accent">
        {label}
        {on ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}

function useSort<K extends string>(first: K) {
  const [sort, setSort] = useState<Sort<K>>({ key: first, dir: 1 });
  const onSort = (k: K) =>
    setSort((s) => (s.key === k ? { key: k, dir: (s.dir * -1) as Dir } : { key: k, dir: 1 }));
  return [sort, onSort] as const;
}

type ValueKey = "bubble" | "symbol" | "kind" | "close" | "fair" | "nominal" | "real";

const ALL_FUNDS = "همهٔ صندوق‌ها";
const RIGHT = "حق‌تقدم";
const PAGE = 100;
const isFund = (r: SymbolValue) => r.kind.startsWith("صندوق");
const inGroup = (r: SymbolValue, g: string) => !g || (g === ALL_FUNDS ? isFund(r) : r.kind === g);

function value(r: SymbolValue, k: ValueKey): number | string | null | undefined {
  switch (k) {
    case "bubble":
      return r.bubble;
    case "symbol":
      return r.symbol;
    case "kind":
      return `${r.kind} ${r.industry ?? ""}`;
    case "close":
      return r.close;
    case "fair":
      return r.fair_value;
    case "nominal":
      return r.nominal_return;
    case "real":
      return r.real_return;
  }
}

/** Stocks, funds and rights in one list: the bubble where a value is known, and the period
 *  return against inflation. Clean bubbles first from the most negative, then the rest from the
 *  best real return. */
export function ValueTable({ rows, months }: { rows: SymbolValue[]; months: number }) {
  const groups = useMemo(() => {
    const kinds = [...new Set(rows.filter(isFund).map((r) => r.kind))].sort((a, b) =>
      a.localeCompare(b, "fa"),
    );
    return ["سهم", RIGHT, ALL_FUNDS, ...kinds];
  }, [rows]);
  const [group, setGroup] = useState("");
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const [sort, onSort] = useSort<ValueKey>("bubble");
  const shown = useMemo(() => {
    const needle = q.trim();
    return rows
      .filter((r) => inGroup(r, group))
      .filter((r) => !needle || r.symbol.includes(needle) || (r.name ?? "").includes(needle))
      .sort((a, b) =>
        sort.key === "bubble"
          ? trust(a.bubble, a.bubble_note) - trust(b.bubble, b.bubble_note) ||
            cmp(a.bubble, b.bubble, sort.dir) ||
            cmp(a.real_return, b.real_return, -1)
          : cmp(value(a, sort.key), value(b, sort.key), sort.dir),
      );
  }, [rows, group, q, sort]);
  const withReal = shown.filter((r) => r.real_return != null);
  const ahead = withReal.filter((r) => (r.real_return ?? 0) > 0).length;
  const visible = all ? shown : shown.slice(0, PAGE);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="value-group">نوع نماد:</label>
        <select
          id="value-group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          className="rounded border border-line bg-surface px-2 py-1"
        >
          <option value="">همه ({faNumber(rows.length)})</option>
          {groups.map((g) => (
            <option key={g} value={g}>
              {g} ({faNumber(rows.filter((r) => inGroup(r, g)).length)})
            </option>
          ))}
        </select>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="نماد یا نام…"
          aria-label="جست‌وجو در فهرست"
          className="rounded border border-line bg-surface px-2 py-1"
        />
        <span className="text-muted" data-testid="value-summary">
          {faNumber(shown.length)} نماد
          {withReal.length > 0 && (
            <>
              ؛ {faNumber(ahead)} نماد از {faNumber(withReal.length)} نمادِ دارای بازده در{" "}
              {faNumber(months)} ماه گذشته از تورم جلو بودند.
            </>
          )}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="tbl min-w-[54rem]" data-testid="value-table">
          <caption className="sr-only">همهٔ نمادها: حباب و بازده در برابر تورم</caption>
          <thead>
            <tr className="border-b border-line">
              <Head k="symbol" label="نماد" sort={sort} onSort={onSort} />
              <Head k="kind" label="نوع" sort={sort} onSort={onSort} />
              <Head k="close" label="قیمت پایانی" sort={sort} onSort={onSort} />
              <Head k="fair" label="ارزش" sort={sort} onSort={onSort} />
              <Head k="bubble" label="حباب" sort={sort} onSort={onSort} />
              <Head
                k="nominal"
                label={`بازده ${faNumber(months)} ماه`}
                sort={sort}
                onSort={onSort}
              />
              <Head k="real" label="جلوتر از تورم" sort={sort} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.instrument_id} className="border-b border-line last:border-0">
                <td className="px-2 py-1.5">
                  <Link
                    href={`/instruments/${r.instrument_id}`}
                    className="font-semibold underline"
                  >
                    {r.symbol}
                  </Link>
                  {r.name && <span className="block text-xs text-muted">{r.name}</span>}
                </td>
                <td className="px-2 py-1.5">
                  {r.kind}
                  {r.industry && <span className="block text-xs text-muted">{r.industry}</span>}
                </td>
                <td className="px-2 py-1.5">
                  {r.close != null ? <Num value={r.close} kind="price" term="last_price" /> : "—"}
                </td>
                <td className="px-2 py-1.5">
                  {r.fair_value != null ? (
                    <Num
                      value={r.fair_value}
                      kind="price"
                      term={r.kind === RIGHT ? "rights" : "fund_nav"}
                    />
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {r.bubble != null && (
                    <Num
                      value={r.bubble}
                      kind="percent"
                      term={r.kind === RIGHT ? "rights_bubble" : "etf_bubble"}
                      digits={1}
                      signed
                    />
                  )}
                  {r.bubble_note && (
                    <span className="block text-xs text-muted">{r.bubble_note}</span>
                  )}
                  {r.bubble == null && !r.bubble_note && r.kind === "سهم" && (
                    <span className="text-xs text-muted">سهم NAV ندارد</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {r.nominal_return != null ? (
                    <Num
                      value={r.nominal_return}
                      kind="percent"
                      term="nominal_return"
                      digits={1}
                      signed
                    />
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {r.real_return != null ? (
                    <Num
                      value={r.real_return}
                      kind="percent"
                      term="real_return"
                      digits={1}
                      signed
                    />
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!all && shown.length > PAGE && (
        <button type="button" onClick={() => setAll(true)} className="tab">
          نمایش همهٔ {faNumber(shown.length)} نماد
        </button>
      )}
    </div>
  );
}

type RightKey = "bubble" | "symbol" | "price" | "value";

/** Right issues against base close minus nominal; most below value first. */
export function RightsTable({ rights }: { rights: Right[] }) {
  const [sort, onSort] = useSort<RightKey>("bubble");
  const rows = useMemo(() => {
    const val = (r: Right) =>
      ({ bubble: r.bubble, symbol: r.symbol, price: r.price, value: r.value })[sort.key];
    return [...rights].sort(
      (a, b) =>
        (sort.key === "bubble"
          ? trust(a.bubble, a.bubble_note) - trust(b.bubble, b.bubble_note)
          : 0) || cmp(val(a), val(b), sort.dir),
    );
  }, [rights, sort]);
  return (
    <div className="overflow-x-auto">
      <table className="tbl min-w-[40rem]" data-testid="rights-table">
        <caption className="sr-only">حق‌تقدم‌ها: قیمت، ارزش و حباب</caption>
        <thead>
          <tr className="border-b border-line">
            <Head k="symbol" label="حق‌تقدم" sort={sort} onSort={onSort} />
            <th scope="col">سهم پایه</th>
            <Head k="price" label="قیمت پایانی" sort={sort} onSort={onSort} />
            <Head k="value" label="ارزش" sort={sort} onSort={onSort} />
            <Head k="bubble" label="حباب" sort={sort} onSort={onSort} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.instrument_id} className="border-b border-line last:border-0">
              <td className="px-2 py-1.5">
                <Link href={`/instruments/${r.instrument_id}`} className="font-semibold underline">
                  {r.symbol}
                </Link>
                {r.name && <span className="block text-xs text-muted">{r.name}</span>}
              </td>
              <td className="px-2 py-1.5">
                {r.base_id ? (
                  <Link href={`/instruments/${r.base_id}`} className="underline">
                    {r.base_symbol}
                  </Link>
                ) : (
                  "—"
                )}
                {r.base_close != null && (
                  <span className="block text-xs text-muted">
                    پایانی <Num value={r.base_close} kind="price" term="last_price" />
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.price} kind="price" term="last_price" />
              </td>
              <td className="px-2 py-1.5">
                {r.value != null ? <Num value={r.value} kind="price" term="rights" /> : "—"}
              </td>
              <td className="px-2 py-1.5">
                {r.bubble != null && (
                  <Num value={r.bubble} kind="percent" term="rights_bubble" digits={1} signed />
                )}
                {r.bubble_note && <span className="block text-xs text-muted">{r.bubble_note}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
