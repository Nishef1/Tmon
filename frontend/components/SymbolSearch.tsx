"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { SearchHit, SymbolSearch as Result } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { verdictPill } from "@/lib/ui";

/** Search box in the header: symbol, company name or industry group, with a one-line summary. */
export function SymbolSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState(-1);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const seq = useRef(0);

  function change(value: string) {
    setQ(value);
    setActive(-1);
    clearTimeout(timer.current);
    const text = value.trim();
    if (!text) {
      seq.current++;
      setHits([]);
      setOpen(false);
      setBusy(false);
      return;
    }
    setOpen(true);
    setBusy(true);
    timer.current = setTimeout(async () => {
      const mine = ++seq.current;
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(text)}`);
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as Result;
        if (mine !== seq.current) return; // a newer keystroke already asked again
        setHits(data.hits);
        setTotal(data.total);
        setFailed(false);
      } catch {
        if (mine === seq.current) {
          setHits([]);
          setFailed(true);
        }
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 180);
  }

  function go(h: SearchHit) {
    setOpen(false);
    setQ("");
    router.push(`/instruments/${h.instrument.id}`);
  }

  function key(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" && hits.length) {
      e.preventDefault();
      setActive((a) => (a + 1) % hits.length);
    } else if (e.key === "ArrowUp" && hits.length) {
      e.preventDefault();
      setActive((a) => (a <= 0 ? hits.length - 1 : a - 1));
    } else if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "Enter" && open && hits.length && !busy) {
      e.preventDefault();
      go(hits[active >= 0 ? active : 0]);
    }
  }

  return (
    <form
      action="/industries"
      role="search"
      className="relative w-full sm:max-w-md"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <input
        name="q"
        value={q}
        onChange={(e) => change(e.target.value)}
        onFocus={() => q.trim() && setOpen(true)}
        onKeyDown={key}
        type="search"
        autoComplete="off"
        placeholder="جست‌وجوی نماد یا شرکت…"
        aria-label="جست‌وجوی نماد"
        role="combobox"
        aria-expanded={open}
        aria-controls="symbol-search-list"
        className="w-full bg-surface-2 px-3 py-2 text-sm"
        data-testid="symbol-search"
      />
      {open && (
        <div
          id="symbol-search-list"
          role="listbox"
          data-testid="search-results"
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-[70vh] overflow-y-auto popover sm:inset-x-auto sm:left-0 sm:w-[34rem] sm:max-w-[calc(100vw-2rem)]"
        >
          {busy && hits.length === 0 && (
            <p className="px-3 py-2 text-sm text-muted">در حال جست‌وجو…</p>
          )}
          {failed && (
            <p className="px-3 py-2 text-sm text-down">جست‌وجو ممکن نشد؛ دوباره تلاش کنید.</p>
          )}
          {!busy && !failed && hits.length === 0 && (
            <p className="px-3 py-2 text-sm text-muted">نمادی با این نام پیدا نشد.</p>
          )}
          {hits.map((h, i) => (
            <button
              type="button"
              key={h.instrument.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => go(h)}
              className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-start hover:bg-accent-soft sm:flex-nowrap ${
                i === active ? "bg-accent-soft" : ""
              }`}
              data-testid="search-hit"
            >
              <span className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                <span className="block truncate font-bold">
                  {h.instrument.symbol}{" "}
                  <span className="text-sm font-normal text-muted">{h.instrument.name}</span>
                </span>
                <span className="block truncate text-sm text-muted">
                  {h.kind}
                  {h.sector_name ? ` · ${h.sector_name}` : ""}
                  {h.pe != null
                    ? ` · P/E ${faNumber(h.pe, 1)}${h.sector_pe ? ` (گروه ${faNumber(h.sector_pe, 1)})` : ""}`
                    : ""}
                  {h.eps != null ? ` · EPS ${faNumber(h.eps)}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-end text-sm">
                {h.close != null && <span className="block">{faNumber(h.close)}</span>}
                {h.change_pct != null && (
                  <span className={`block ${h.change_pct >= 0 ? "text-up" : "text-down"}`}>
                    {faPercent(h.change_pct, 1, true)}
                  </span>
                )}
              </span>
              <span className="flex shrink-0 flex-col items-center gap-0.5">
                <span className={`${verdictPill(h.verdict)}`}>{h.verdict_label}</span>
                {h.gauge != null && (
                  <span className="text-xs text-muted">امتیاز {faNumber(h.gauge, 0)}</span>
                )}
              </span>
            </button>
          ))}
          {hits.length > 0 && (
            <a
              href={`/industries?kind=all&q=${encodeURIComponent(q.trim())}`}
              className="block rounded-lg px-3 py-2 text-sm font-semibold text-accent hover:bg-accent-soft"
            >
              نمایش همهٔ {faNumber(total)} نتیجه در فهرست نمادها
            </a>
          )}
        </div>
      )}
    </form>
  );
}
