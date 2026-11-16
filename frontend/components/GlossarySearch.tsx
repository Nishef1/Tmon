"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

export type GlossaryItem = {
  key: string;
  fa: string;
  en: string;
  category: string;
  categoryLabel: string;
  text: string;
};

/** Persian digits and the Arabic forms of ی/ک are folded so «كالیبراسیون» finds «کالیبراسیون». */
function fold(s: string): string {
  return s
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[‌‏]/g, " ")
    .toLowerCase();
}

export function GlossarySearch({ items }: { items: GlossaryItem[] }) {
  const [q, setQ] = useState("");
  const needle = fold(q.trim());
  const shown = useMemo(
    () =>
      needle ? items.filter((i) => fold(`${i.fa} ${i.en} ${i.text}`).includes(needle)) : items,
    [items, needle],
  );
  const groups = useMemo(() => {
    const m = new Map<string, { label: string; rows: GlossaryItem[] }>();
    for (const i of shown) {
      if (!m.has(i.category)) m.set(i.category, { label: i.categoryLabel, rows: [] });
      m.get(i.category)?.rows.push(i);
    }
    return [...m];
  }, [shown]);
  return (
    <div className="space-y-6">
      <label className="block text-sm">
        <span className="mb-1 block font-semibold">جست‌وجو در واژه‌ها</span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="مثلاً Brier، سرانه، افت، مجمع"
          className="ctl w-full"
          data-testid="glossary-search"
        />
      </label>
      <p className="text-xs text-muted" role="status">
        {needle ? `${shown.length.toLocaleString("fa-IR")} واژه پیدا شد.` : ""}
      </p>
      {groups.length === 0 && <p className="card text-muted">واژه‌ای با این نام پیدا نشد.</p>}
      {groups.map(([category, g]) => (
        <section key={category} aria-labelledby={`g-${category}`}>
          <h2 id={`g-${category}`} className="mb-2 font-bold">
            {g.label}
          </h2>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {g.rows.map((i) => (
              <li key={i.key}>
                <Link href={`/glossary/${i.key}`} className="chip block w-full">
                  <span className="font-semibold">{i.fa}</span>
                  <span className="block text-xs text-muted" dir="ltr">
                    {i.en}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
