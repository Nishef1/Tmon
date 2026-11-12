"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { Gauge } from "@/components/Gauge";
import { faNumber, faPrice, faToman } from "@/lib/format";
import { gaugeWhy, sortRows, type Row, type SortKey } from "@/lib/industry";
import { heatProps, signTone, signedPct, verdictPill } from "@/lib/ui";

export type SectorSummary = {
  code: string;
  name: string;
  n: number;
  value: number;
  avgChange: number | null;
  netReal: number | null;
};

type GroupKey = "name" | "n" | "value" | "avgChange" | "netReal";

const GROUP_COLS: [GroupKey, string][] = [
  ["name", "گروه"],
  ["n", "سهام"],
  ["value", "ارزش معاملات"],
  ["avgChange", "تغییر میانگین"],
  ["netReal", "خالص پول حقیقی"],
];

const MEMBER_COLS: [SortKey, string][] = [
  ["symbol", "نماد"],
  ["gauge", "تصمیم و امتیاز"],
  ["close", "پایانی"],
  ["day", "امروز"],
  ["week", "هفته"],
  ["month", "ماه"],
  ["year", "سال"],
  ["value", "ارزش معاملات"],
  ["netReal", "پول حقیقی"],
  ["pe", "P/E"],
];

function Arrow({ on, dir }: { on: boolean; dir: 1 | -1 }) {
  return (
    <span className={on ? "text-accent" : "text-muted/50"}>
      {on ? (dir === 1 ? "▲" : "▼") : "↕"}
    </span>
  );
}

/** Expandable market groups: click a group to list every stock in it; both tables are sortable. */
export function SectorTable({
  sectors,
  members,
}: {
  sectors: SectorSummary[];
  members: Record<string, Row[]>;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [gk, setGk] = useState<GroupKey>("value");
  const [gd, setGd] = useState<1 | -1>(-1);
  const [mk, setMk] = useState<SortKey>("value");
  const [md, setMd] = useState<1 | -1>(-1);

  const ordered = useMemo(() => {
    const text = gk === "name";
    return [...sectors].sort((a, b) => {
      const x = a[gk];
      const y = b[gk];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = text ? String(x).localeCompare(String(y), "fa") : (x as number) - (y as number);
      return gd === 1 ? c : -c;
    });
  }, [sectors, gk, gd]);

  const maxValue = Math.max(1, ...sectors.map((s) => s.value));

  function sortGroups(k: GroupKey) {
    if (k === gk) setGd(gd === 1 ? -1 : 1);
    else {
      setGk(k);
      setGd(k === "name" ? 1 : -1);
    }
  }
  function sortMembers(k: SortKey) {
    if (k === mk) setMd(md === 1 ? -1 : 1);
    else {
      setMk(k);
      setMd(k === "symbol" ? 1 : -1);
    }
  }

  return (
    <div className="card card-flush overflow-x-auto">
      <table className="tbl min-w-[40rem]" data-testid="sector-table">
        <thead className="bg-accent-soft text-xs text-muted">
          <tr className="text-right">
            <th className="w-8" />
            {GROUP_COLS.map(([k, label]) => (
              <th key={k}>
                <button
                  type="button"
                  onClick={() => sortGroups(k)}
                  className="inline-flex items-center gap-1 hover:text-ink"
                  aria-label={`مرتب‌سازی گروه‌ها بر پایهٔ ${label}`}
                >
                  {label} <Arrow on={gk === k} dir={gd} />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordered.map((s) => {
            const isOpen = open === s.code;
            const list = members[s.code] ?? [];
            return (
              <Fragment key={s.code}>
                <tr
                  onClick={() => setOpen(isOpen ? null : s.code)}
                  className={`cursor-pointer border-t border-line hover:bg-accent-soft ${isOpen ? "bg-accent-soft" : ""}`}
                  data-sector={s.code}
                  aria-expanded={isOpen}
                >
                  <td className="px-2 text-center text-muted">{isOpen ? "▾" : "◂"}</td>
                  <td className="px-3 py-2 font-bold">{s.name}</td>
                  <td className="px-3">{faNumber(s.n)}</td>
                  <td className="px-3">
                    <div>{faToman(s.value)}</div>
                    <div className="mt-1 h-1 w-28 overflow-hidden rounded-full bg-line">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${Math.max(2, (s.value / maxValue) * 100).toFixed(1)}%` }}
                      />
                    </div>
                  </td>
                  <td
                    className={`px-3 font-semibold ${signTone(s.avgChange)}`}
                    {...heatProps(s.avgChange)}
                  >
                    {signedPct(s.avgChange, 2)}
                  </td>
                  <td className={`px-3 ${signTone(s.netReal)}`}>{faToman(s.netReal)}</td>
                </tr>
                {isOpen && (
                  <tr data-testid="sector-members">
                    <td colSpan={6} className="border-t border-line bg-bg p-0">
                      {list.length === 0 ? (
                        <p className="p-4 text-muted">نمادی از این گروه در جدول سهام نیست.</p>
                      ) : (
                        <div className="max-h-[32rem] overflow-auto">
                          <table className="tbl min-w-[56rem]">
                            <thead className="sticky top-0 z-10 bg-surface text-xs text-muted">
                              <tr className="text-right">
                                {MEMBER_COLS.map(([k, label]) => (
                                  <th key={k}>
                                    <button
                                      type="button"
                                      onClick={() => sortMembers(k)}
                                      className="inline-flex items-center gap-1 hover:text-ink"
                                    >
                                      {label} <Arrow on={mk === k} dir={md} />
                                    </button>
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {sortRows(list, mk, md).map((r) => (
                                <tr
                                  key={r.id}
                                  className="border-t border-line hover:bg-accent-soft"
                                >
                                  <td className="px-3 py-1.5">
                                    <Link
                                      href={`/instruments/${r.id}`}
                                      className="font-bold text-accent hover:underline"
                                    >
                                      {r.symbol}
                                    </Link>
                                    <div
                                      className="max-w-48 truncate text-xs text-muted"
                                      title={r.name}
                                    >
                                      {r.name}
                                    </div>
                                  </td>
                                  <td className="px-3">
                                    <div className="flex items-center gap-2">
                                      {r.gauge != null && <Gauge value={r.gauge} size="sm" />}
                                      <div>
                                        <span className={`${verdictPill(r.verdict)}`}>
                                          {r.verdictLabel}
                                        </span>
                                        <div className="text-xs text-muted">
                                          {r.gauge == null ? gaugeWhy(r.gaugeNote) : ""}
                                        </div>
                                      </div>
                                    </div>
                                  </td>
                                  <td className="px-3">
                                    {r.close == null ? "—" : faPrice(r.close)}
                                  </td>
                                  {[r.day, r.week, r.month, r.year].map((v, i) => (
                                    <td
                                      key={i}
                                      className={`px-3 font-semibold ${signTone(v)}`}
                                      {...heatProps(v)}
                                    >
                                      {signedPct(v)}
                                    </td>
                                  ))}
                                  <td className="px-3">{faToman(r.value)}</td>
                                  <td className={`px-3 ${signTone(r.netReal)}`}>
                                    {faToman(r.netReal)}
                                  </td>
                                  <td className="px-3">{r.pe == null ? "—" : faNumber(r.pe, 1)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
