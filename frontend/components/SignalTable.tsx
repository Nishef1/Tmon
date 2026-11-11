import Link from "next/link";
import type { Signal } from "@/lib/api";
import { jalali } from "@/lib/format";
import { Num } from "./Num";
import { TierBadge } from "./TierBadge";

export const OUTCOME_LABEL: Record<string, string> = {
  pending: "باز",
  tp: "رسید به حد سود",
  sl: "رسید به حد ضرر",
  sl_same_day: "حد ضرر (همان روز)",
  expiry: "پایان افق",
};

export function SignalTable({
  items,
  showSymbol = true,
}: {
  items: Signal[];
  showSymbol?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="sr-only">سابقهٔ سیگنال‌ها و نتیجهٔ هرکدام</caption>
        <thead className="text-start text-xs text-muted">
          <tr className="border-b border-line">
            <th scope="col" className="px-3 py-2 text-start font-medium">
              تاریخ
            </th>
            {showSymbol && (
              <th scope="col" className="px-3 py-2 text-start font-medium">
                نماد
              </th>
            )}
            <th scope="col" className="px-3 py-2 text-start font-medium">
              رده
            </th>
            <th scope="col" className="px-3 py-2 text-start font-medium">
              احتمال
            </th>
            <th scope="col" className="px-3 py-2 text-start font-medium">
              نتیجه
            </th>
            <th scope="col" className="px-3 py-2 text-start font-medium">
              بازده ناخالص
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id} className="border-b border-line last:border-0">
              <td className="px-3 py-2">{jalali(s.date, "short")}</td>
              {showSymbol && (
                <td className="px-3 py-2 font-semibold">
                  <Link href={`/instruments/${s.instrument.id}`} className="hover:text-accent">
                    {s.instrument.symbol}
                  </Link>
                </td>
              )}
              <td className="px-3 py-2">
                <TierBadge tier={s.confidence_tier} />
              </td>
              <td className="px-3 py-2">
                <Num term="p_win" value={s.p_win} kind="percent" digits={0} />
              </td>
              <td className="px-3 py-2">{OUTCOME_LABEL[s.outcome] ?? s.outcome}</td>
              <td className="px-3 py-2">
                {s.outcome === "pending" ? (
                  <span className="text-muted">—</span>
                ) : (
                  <Num term="realized_return" value={s.realized_return} kind="percent" signed />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
