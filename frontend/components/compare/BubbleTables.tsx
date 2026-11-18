"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Fund, Right } from "@/lib/api";
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

type FundKey = "bubble" | "symbol" | "kind" | "nav" | "price";

/** Listed funds: kind, full name, NAV, close and bubble; cheapest against NAV first. */
export function FundsTable({ funds }: { funds: Fund[] }) {
  const kinds = useMemo(
    () =>
      [...new Set(funds.map((f) => f.kind ?? "صندوق"))].sort((a, b) => a.localeCompare(b, "fa")),
    [funds],
  );
  const [kind, setKind] = useState("");
  const [sort, onSort] = useSort<FundKey>("bubble");
  const rows = useMemo(() => {
    const val = (f: Fund): number | string | null | undefined =>
      ({
        bubble: f.bubble,
        symbol: f.symbol ?? f.name,
        kind: `${f.kind ?? ""} ${f.industry ?? ""}`,
        nav: f.cancel_nav,
        price: f.price,
      })[sort.key];
    return funds
      .filter((f) => !kind || (f.kind ?? "صندوق") === kind)
      .sort(
        (a, b) =>
          (sort.key === "bubble"
            ? trust(a.bubble, a.bubble_note) - trust(b.bubble, b.bubble_note)
            : 0) || cmp(val(a), val(b), sort.dir),
      );
  }, [funds, kind, sort]);
  const cheap = rows.filter((f) => f.bubble != null && !f.bubble_note && f.bubble < 0).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="fund-kind">نوع صندوق:</label>
        <select
          id="fund-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded border border-line bg-surface px-2 py-1"
        >
          <option value="">همه ({faNumber(funds.length)})</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {k} ({faNumber(funds.filter((f) => (f.kind ?? "صندوق") === k).length)})
            </option>
          ))}
        </select>
        <span className="text-muted">
          {faNumber(rows.length)} صندوق؛ {faNumber(cheap)} صندوق زیر NAV ابطال معامله شد.
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="tbl min-w-[44rem]" data-testid="funds-table">
          <caption className="sr-only">صندوق‌های بورسی: نوع، NAV ابطال، قیمت و حباب</caption>
          <thead>
            <tr className="border-b border-line">
              <Head k="symbol" label="نماد صندوق" sort={sort} onSort={onSort} />
              <Head k="kind" label="نوع" sort={sort} onSort={onSort} />
              <Head k="nav" label="NAV ابطال" sort={sort} onSort={onSort} />
              <Head k="price" label="قیمت پایانی" sort={sort} onSort={onSort} />
              <Head k="bubble" label="حباب" sort={sort} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.reg_no} className="border-b border-line last:border-0">
                <td className="px-2 py-1.5">
                  {f.instrument_id ? (
                    <Link
                      href={`/instruments/${f.instrument_id}`}
                      className="font-semibold underline"
                    >
                      {f.symbol ?? f.name}
                    </Link>
                  ) : (
                    f.symbol
                  )}
                  {f.name && <span className="block text-xs text-muted">{f.name}</span>}
                </td>
                <td className="px-2 py-1.5">
                  {f.kind ?? "صندوق"}
                  {f.industry && (
                    <span className="block text-xs text-muted">صنعت {f.industry}</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {f.cancel_nav != null ? (
                    <Num value={f.cancel_nav} kind="price" term="fund_nav" />
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {f.price != null ? <Num value={f.price} kind="price" term="last_price" /> : "—"}
                </td>
                <td className="px-2 py-1.5">
                  {f.bubble != null && (
                    <Num value={f.bubble} kind="percent" term="etf_bubble" digits={1} signed />
                  )}
                  {f.bubble_note && (
                    <span className="block text-xs text-muted">{f.bubble_note}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
