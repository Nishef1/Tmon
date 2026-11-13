"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { SearchHit, SymbolSearch } from "@/lib/api";
import { COLORS, MAX_SYMBOLS } from "./colors";

/** The symbols being compared: remove one, or search and add up to four. The choice lives in the
 *  address (?s=id,id) so a comparison can be shared or bookmarked. */
export function SymbolPicker({
  chosen,
  keep,
}: {
  chosen: { id: number; symbol: string }[];
  keep: string; // the page's other query parameters, already encoded
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const seq = useRef(0);
  const ids = chosen.map((c) => c.id);

  function go(next: number[]) {
    const s = next.length ? `s=${next.join(",")}` : "";
    const qs = [s, keep].filter(Boolean).join("&");
    router.push(`/compare${qs ? `?${qs}` : ""}#symbols`, { scroll: false });
  }

  function change(value: string) {
    setQ(value);
    clearTimeout(timer.current);
    const text = value.trim();
    if (!text) {
      seq.current++;
      setHits([]);
      return;
    }
    timer.current = setTimeout(async () => {
      const mine = ++seq.current;
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(text)}`);
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as SymbolSearch;
        if (mine !== seq.current) return;
        setHits(data.hits.filter((h) => !ids.includes(h.instrument.id)).slice(0, 8));
        setFailed(false);
      } catch {
        if (mine === seq.current) {
          setHits([]);
          setFailed(true);
        }
      }
    }, 180);
  }

  return (
    <div className="space-y-2" data-testid="symbol-picker">
      <ul className="flex flex-wrap gap-2">
        {chosen.map((c, i) => (
          <li
            key={c.id}
            className="ind"
            style={{ "--sw": COLORS[i % COLORS.length] } as React.CSSProperties}
          >
            <span className="sw" aria-hidden />
            {c.symbol}
            <button
              type="button"
              className="ms-1 text-muted hover:text-down"
              aria-label={`حذف ${c.symbol} از مقایسه`}
              onClick={() => go(ids.filter((x) => x !== c.id))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      {chosen.length < MAX_SYMBOLS ? (
        <div className="relative max-w-sm">
          <input
            type="search"
            value={q}
            onChange={(e) => change(e.target.value)}
            placeholder="افزودن نماد: نام یا نماد را بنویسید"
            aria-label="افزودن نماد به مقایسه"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          {hits.length > 0 && (
            <ul
              className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-lg border border-line bg-surface shadow-pop"
              role="listbox"
              aria-label="نتیجه‌های جستجو"
            >
              {hits.map((h) => (
                <li key={h.instrument.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    className="block w-full px-3 py-1.5 text-start text-sm hover:bg-surface-2"
                    onClick={() => {
                      setQ("");
                      setHits([]);
                      go([...ids, h.instrument.id]);
                    }}
                  >
                    <b>{h.instrument.symbol}</b>{" "}
                    <span className="text-muted">{h.instrument.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {failed && <p className="mt-1 text-xs text-down">جستجو انجام نشد.</p>}
        </div>
      ) : (
        <p className="text-xs text-muted">حداکثر {MAX_SYMBOLS} نماد را می‌شود کنار هم دید.</p>
      )}
    </div>
  );
}
