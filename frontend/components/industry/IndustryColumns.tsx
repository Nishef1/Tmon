"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { IndustryDetail } from "@/lib/api";
import { colTone, fmtCol, type ColumnCatalog, type ColumnDef } from "@/lib/columns";

const KEYS = [
  "mcap",
  "pe_ttm",
  "pb",
  "ps_ttm",
  "roe",
  "net_margin",
  "debt_to_assets",
  "beta_90d",
  "vol_vs_30",
  "real_net_pct",
  "ret_1m",
  "ret_1y",
  "to_high_1y",
  "float_pct",
  "tech_score",
  "fund_score",
];

type Sort = { key: string; dir: 1 | -1 } | null;

/** The derived columns of every symbol of the industry, with the industry's and the market's
 *  median on top so a symbol can be read against both. */
export function IndustryColumns({ d, catalog }: { d: IndustryDetail; catalog: ColumnCatalog }) {
  const defs = useMemo(
    () =>
      KEYS.map((k) => catalog.columns.find((c) => c.key === k)).filter(
        (c): c is ColumnDef => c !== undefined,
      ),
    [catalog],
  );
  const [sort, setSort] = useState<Sort>(null);
  const rows = useMemo(() => {
    if (!sort) return d.members;
    const k = sort.key;
    return [...d.members].sort((a, b) => {
      const x = a.cols[k];
      const y = b.cols[k];
      if (typeof x !== "number" && typeof y !== "number") return 0;
      if (typeof x !== "number") return 1;
      if (typeof y !== "number") return -1;
      return sort.dir === 1 ? x - y : y - x;
    });
  }, [d.members, sort]);

  const head = (key: string) =>
    setSort((s) => (s?.key === key ? (s.dir === 1 ? { key, dir: -1 } : null) : { key, dir: -1 }));

  const medianRows = [
    ["میانهٔ صنعت", d.medians],
    ["میانهٔ بازار", d.market_medians],
  ] as const;

  return (
    <section className="card card-flush" data-testid="industry-columns">
      <div className="space-y-0.5 p-4 pb-2">
        <h2 className="text-lg font-black">ستون‌های ترکیبی نمادهای صنعت</h2>
        <p className="text-xs leading-6 text-muted">
          ارزش‌گذاری، سودآوری، بتا، حجم، پول حقیقی و شناوری هر نماد کنار میانهٔ صنعت و بازار. صورت
          مالی فقط برای نمادهایی هست که ذخیره کرده‌ایم؛ بقیه «—» می‌گیرند. روی عنوان هر ستون بزنید
          تا مرتب شود.
        </p>
      </div>
      <div className="max-h-[70vh] overflow-auto">
        <table className="w-full min-w-[60rem] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">ستون‌های ترکیبی نمادهای صنعت</caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky start-0 top-0 z-30 border-b border-line bg-surface px-3 py-2 text-start font-medium"
              >
                نماد
              </th>
              {defs.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  title={c.hint || c.label}
                  className="sticky top-0 z-20 whitespace-nowrap border-b border-line bg-surface px-2 py-2 text-start font-medium"
                >
                  <button type="button" onClick={() => head(c.key)} className="hover:text-accent">
                    {c.label}
                    {sort?.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                  </button>
                </th>
              ))}
            </tr>
            {medianRows.map(([label, med]) => (
              <tr key={label} className="bg-surface-2/60 text-xs">
                <th
                  scope="row"
                  className="sticky start-0 z-10 border-b border-line bg-surface-2 px-3 py-1.5 text-start font-bold"
                >
                  {label}
                </th>
                {defs.map((c) => (
                  <td
                    key={c.key}
                    className="whitespace-nowrap border-b border-line px-2 py-1.5 tabular-nums"
                  >
                    {c.key in med ? fmtCol(c, med[c.key]) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.instrument_id} className="hover:bg-accent-soft" data-symbol={m.symbol}>
                <th
                  scope="row"
                  className="sticky start-0 z-10 border-b border-line bg-surface px-3 py-1.5 text-start font-normal"
                >
                  <Link
                    href={`/instruments/${m.instrument_id}`}
                    className="font-bold hover:text-accent"
                  >
                    {m.symbol}
                  </Link>
                </th>
                {defs.map((c) => (
                  <td
                    key={c.key}
                    className={`whitespace-nowrap border-b border-line px-2 py-1.5 tabular-nums ${colTone(c, m.cols[c.key])}`}
                  >
                    {fmtCol(c, m.cols[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
