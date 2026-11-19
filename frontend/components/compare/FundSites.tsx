"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Fund } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";

const ONLY_SITE = "فقط از سایت صندوق";
const BOTH = "در بورس، و صدور و ابطال";

/** What buying at the issue NAV and redeeming at the cancel NAV on the same day loses. */
export function issueGap(f: Fund): number | null {
  return f.issue_nav && f.cancel_nav ? f.issue_nav / f.cancel_nav - 1 : null;
}

/** Every fund with its own site, where units are issued and redeemed at NAV. */
export function FundSitesTable({ funds }: { funds: Fund[] }) {
  const kinds = useMemo(
    () =>
      [...new Set(funds.map((f) => f.kind ?? "صندوق"))].sort((a, b) => a.localeCompare(b, "fa")),
    [funds],
  );
  const [kind, setKind] = useState("");
  const [way, setWay] = useState("");
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim();
    return funds
      .filter((f) => !kind || (f.kind ?? "صندوق") === kind)
      .filter((f) => !way || (way === ONLY_SITE ? !f.listed : f.listed))
      .filter(
        (f) =>
          !needle ||
          (f.name ?? "").includes(needle) ||
          (f.symbol ?? "").includes(needle) ||
          (f.manager ?? "").includes(needle) ||
          (f.website ?? "").includes(needle),
      )
      .sort((a, b) => (a.name ?? "").trim().localeCompare((b.name ?? "").trim(), "fa"));
  }, [funds, kind, way, q]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="site-kind">نوع صندوق:</label>
        <select
          id="site-kind"
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
        <label htmlFor="site-way">راه خرید:</label>
        <select
          id="site-way"
          value={way}
          onChange={(e) => setWay(e.target.value)}
          className="rounded border border-line bg-surface px-2 py-1"
        >
          <option value="">همه</option>
          <option value={ONLY_SITE}>{ONLY_SITE}</option>
          <option value={BOTH}>{BOTH}</option>
        </select>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="نام، نماد یا مدیر…"
          aria-label="جست‌وجو در سایت صندوق‌ها"
          className="rounded border border-line bg-surface px-2 py-1"
        />
        <span className="text-muted" data-testid="fund-sites-summary">
          {faNumber(shown.length)} صندوق
        </span>
      </div>
      <div className="max-h-[36rem] overflow-auto">
        <table className="tbl min-w-[54rem]" data-testid="fund-sites-table">
          <caption className="sr-only">سایت هر صندوق</caption>
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-line">
              <th className="px-2 py-1.5 text-start">صندوق</th>
              <th className="px-2 py-1.5 text-start">نوع</th>
              <th className="px-2 py-1.5 text-start">راه خرید</th>
              <th className="px-2 py-1.5 text-start">فاصلهٔ NAV صدور و ابطال</th>
              <th className="px-2 py-1.5 text-start">مدیر</th>
              <th className="px-2 py-1.5 text-start">سایت صندوق</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f.reg_no} className="border-b border-line last:border-0">
                <td className="px-2 py-1.5">
                  {f.name ?? f.reg_no}
                  {f.symbol && f.instrument_id != null && (
                    <Link
                      href={`/instruments/${f.instrument_id}`}
                      className="block text-xs font-semibold underline"
                    >
                      {f.symbol}
                    </Link>
                  )}
                </td>
                <td className="px-2 py-1.5">{f.kind}</td>
                <td className="px-2 py-1.5">{f.listed ? BOTH : ONLY_SITE}</td>
                <td className="px-2 py-1.5">
                  {issueGap(f) != null ? faPercent(issueGap(f) ?? 0, 2) : "—"}
                </td>
                <td className="px-2 py-1.5 text-xs">{f.manager ?? "—"}</td>
                <td className="px-2 py-1.5">
                  {f.website ? (
                    <a
                      href={f.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      dir="ltr"
                      className="underline"
                    >
                      {f.website.replace(/^https:\/\//, "")}
                    </a>
                  ) : (
                    "—"
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
