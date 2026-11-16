"use client";

import { QueueBadge } from "@/components/QueueBadge";
import Link from "next/link";
import { TradeBadge } from "@/components/TradeBadge";
import { useMemo, useState } from "react";
import type { RankingRow } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { rowVerdict, verdictPill } from "@/lib/ui";

type Zone = "all" | V;
type Key = "rank" | "change" | "close" | "value";

const LABEL = { buy: "خرید", hold: "صبر", sell: "فروش" } as const;
type V = keyof typeof LABEL;

/** The verdict the stock's own page shows (zone softened by the tested month); falls back to the
 *  zone for an older API that has no `verdict`. */
const verdictOf = (r: RankingRow): V | null => rowVerdict(r);
const PAGE = 40;

/** One sortable, filterable table of the liquid stocks: what a visitor scans first. */
export function StockTable({ rows }: { rows: RankingRow[] }) {
  const [zone, setZone] = useState<Zone>("all");
  const [q, setQ] = useState("");
  const [key, setKey] = useState<Key>("rank");
  const [asc, setAsc] = useState(true);
  const [thin, setThin] = useState(false);
  const [more, setMore] = useState(PAGE);

  // position among the liquid stocks shown here (the raw rank counts every listed symbol)
  const pos = useMemo(() => {
    const m = new Map<string, number>();
    rows
      .filter((r) => r.in_basket !== false)
      .sort((a, b) => a.rank - b.rank)
      .forEach((r, i) => m.set(r.symbol, i + 1));
    return m;
  }, [rows]);

  const counts = useMemo(() => {
    const c = { all: 0, buy: 0, hold: 0, sell: 0 };
    for (const r of rows) {
      if (!thin && r.in_basket === false) continue;
      c.all++;
      const v = verdictOf(r);
      if (v) c[v]++;
    }
    return c;
  }, [rows, thin]);

  const shown = useMemo(() => {
    const needle = q.trim();
    const get = (r: RankingRow): number =>
      key === "rank"
        ? (pos.get(r.symbol) ?? 1e6 + r.rank)
        : key === "change"
          ? (r.change_pct ?? -9)
          : key === "close"
            ? (r.close ?? 0)
            : (r.median_value ?? 0);
    return rows
      .filter((r) => (thin || r.in_basket !== false) && (zone === "all" || verdictOf(r) === zone))
      .filter((r) => !needle || r.symbol.includes(needle) || (r.name ?? "").includes(needle))
      .sort((a, b) => (asc ? 1 : -1) * (get(a) - get(b)));
  }, [rows, zone, q, key, asc, thin, pos]);

  const sortBy = (k: Key) => {
    if (k === key) setAsc(!asc);
    else {
      setKey(k);
      setAsc(k === "rank");
    }
    setMore(PAGE);
  };
  const arrow = (k: Key) => (k === key ? (asc ? " ▲" : " ▼") : "");
  const tabs: { id: Zone; label: string }[] = [
    { id: "all", label: "همه" },
    { id: "buy", label: "خرید" },
    { id: "hold", label: "صبر" },
    { id: "sell", label: "فروش" },
  ];

  return (
    <section className="card space-y-3" data-testid="stock-table">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">رتبهٔ سهم‌ها امروز</h2>
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setMore(PAGE);
          }}
          placeholder="جستجو در همین جدول…"
          aria-label="جستجو در جدول"
          className="w-full max-w-60 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={zone === t.id}
            onClick={() => {
              setZone(t.id);
              setMore(PAGE);
            }}
            className="tab tab-pill"
            aria-current={zone === t.id ? "page" : undefined}
          >
            {t.label} <span className="text-muted">{faNumber(counts[t.id])}</span>
          </button>
        ))}
        <label className="ms-auto flex items-center gap-1.5 text-xs text-muted">
          <input type="checkbox" checked={thin} onChange={(e) => setThin(e.target.checked)} />
          کم‌معامله‌ها هم نمایش داده شوند
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th className="py-1.5 text-start font-medium">
                <button onClick={() => sortBy("rank")}>رتبه{arrow("rank")}</button>
              </th>
              <th className="py-1.5 text-start font-medium">نماد</th>
              <th className="py-1.5 text-start font-medium">
                <button onClick={() => sortBy("close")}>قیمت پایانی{arrow("close")}</button>
              </th>
              <th className="py-1.5 text-start font-medium">
                <button onClick={() => sortBy("change")}>تغییر امروز{arrow("change")}</button>
              </th>
              <th className="hidden py-1.5 text-start font-medium sm:table-cell">
                <button onClick={() => sortBy("value")}>معاملهٔ معمول{arrow("value")}</button>
              </th>
              <th className="py-1.5 text-start font-medium">وضعیت</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, more).map((r) => (
              <tr key={r.symbol} className="border-t border-line">
                <td className="py-2 text-muted">
                  {pos.has(r.symbol) ? faNumber(pos.get(r.symbol) ?? 0) : "—"}
                </td>
                <td className="py-2">
                  <Link
                    href={
                      r.instrument_id == null
                        ? `/industries?q=${encodeURIComponent(r.symbol)}`
                        : `/instruments/${r.instrument_id}`
                    }
                    className="font-bold hover:underline"
                  >
                    {r.symbol}
                  </Link>
                  <TradeBadge
                    state={r.trade_state}
                    idleDays={r.idle_days}
                    lastTrade={r.last_trade_date}
                  />
                  <span className="block max-w-44 truncate text-xs text-muted">{r.name}</span>
                </td>
                <td className="py-2">{r.close == null ? "—" : faNumber(r.close)}</td>
                <td
                  className={`py-2 font-semibold ${(r.change_pct ?? 0) > 0 ? "text-up" : (r.change_pct ?? 0) < 0 ? "text-down" : "text-muted"}`}
                >
                  {r.change_pct == null ? "—" : faPercent(r.change_pct, 1, true)}
                </td>
                <td className="hidden py-2 text-muted sm:table-cell">
                  {r.median_value == null ? "—" : `${faNumber(r.median_value / 1e10, 1)} میلیارد ت`}
                </td>
                <td className="py-2">
                  {verdictOf(r) ? (
                    <span className={verdictPill(verdictOf(r) as V)}>
                      {LABEL[verdictOf(r) as V]}
                    </span>
                  ) : (
                    "—"
                  )}
                  <QueueBadge r={r} className="ms-1" />
                  {r.in_basket === false && (
                    <span className="ms-1 rounded bg-warn-soft px-1 text-[10px] text-warn">
                      کم‌معامله
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <p className="py-4 text-sm text-muted">نمادی با این شرط نیست.</p>}
      </div>
      {shown.length > more && (
        <button className="tab tab-pill" onClick={() => setMore(more + PAGE)}>
          {faNumber(shown.length - more)} سهم دیگر
        </button>
      )}
    </section>
  );
}
