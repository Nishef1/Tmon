import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type History } from "@/lib/api";
import type { GlossaryKey } from "@/lib/glossary";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { SignalTable } from "@/components/SignalTable";

export const metadata: Metadata = { title: "سابقه سیگنال‌ها" };
export const dynamic = "force-dynamic";

const PAGE = 25;
const FILTERS = [
  { id: "", label: "همه" },
  { id: "tp", label: "حد سود" },
  { id: "sl", label: "حد ضرر" },
  { id: "expiry", label: "پایان افق" },
  { id: "pending", label: "باز" },
];

type Search = { outcome?: string; offset?: string };

export default async function HistoryPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { outcome = "", offset = "0" } = await searchParams;
  const off = Math.max(0, Number.parseInt(offset, 10) || 0);
  const res = await apiGet<History>("/signals/history", {
    timeframe: "D1",
    outcome,
    limit: PAGE,
    offset: off,
  });
  const href = (o: string, n: number) =>
    `/history?${new URLSearchParams({ ...(o ? { outcome: o } : {}), ...(n ? { offset: String(n) } : {}) })}`;

  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">سابقهٔ سیگنال‌ها</h1>
        <p className="mt-1 text-sm text-muted">
          نتیجهٔ همهٔ سیگنال‌های منتشرشده، چه موفق و چه ناموفق. بازده‌ها ناخالص (پیش از هزینه‌ها) و
          مربوط به گذشته‌اند و آینده را تضمین نمی‌کنند.
        </p>
      </div>
      <Disclaimer />

      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <section aria-label="خلاصه" className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {(
              [
                ["کل سیگنال‌ها", "signals_count", res.data.summary.total],
                ["رسید به حد سود", "tp_count", res.data.summary.take_profit],
                ["رسید به حد ضرر", "sl_count", res.data.summary.stop_loss],
                ["پایان افق", "expiry_count", res.data.summary.expired],
                ["هنوز باز", "pending_count", res.data.summary.pending],
              ] as [string, GlossaryKey, number][]
            ).map(([label, term, value]) => (
              <div key={term} className="tile">
                <p className="text-xs text-muted">{label}</p>
                <p className="text-xl font-bold">
                  <Num term={term} value={value} kind="count" />
                </p>
              </div>
            ))}
          </section>
          {res.data.summary.mean_realized_return !== null && (
            <p className="text-sm">
              میانگین بازدهٔ ناخالص سیگنال‌های بسته‌شده:{" "}
              <Num
                term="realized_return"
                value={res.data.summary.mean_realized_return}
                kind="percent"
                digits={2}
                signed
              />
            </p>
          )}

          <nav aria-label="فیلتر نتیجه" className="flex flex-wrap gap-2 text-sm">
            {FILTERS.map((f) => (
              <Link
                key={f.id}
                href={href(f.id, 0)}
                aria-current={outcome === f.id ? "page" : undefined}
                className={`rounded-full border px-3 py-1 ${
                  outcome === f.id
                    ? "border-accent bg-accent text-surface"
                    : "border-line bg-surface hover:bg-accent-soft"
                }`}
              >
                {f.label}
              </Link>
            ))}
          </nav>

          {res.data.items.length === 0 ? (
            <p
              data-testid="history-empty"
              className="card card-pad-lg text-sm text-muted"
            >
              هنوز سیگنالی منتشر نشده است. تا وقتی نمادی شرایط توصیه را نداشته باشد (دلیل دقیق در
              صفحهٔ رتبه‌بندی آمده)، چیزی در این فهرست ثبت نمی‌شود.
            </p>
          ) : (
            <SignalTable items={res.data.items} />
          )}

          <div className="flex justify-between text-sm">
            {off > 0 ? (
              <Link href={href(outcome, Math.max(0, off - PAGE))} className="text-accent">
                → قبلی
              </Link>
            ) : (
              <span />
            )}
            {off + PAGE < res.data.total && (
              <Link href={href(outcome, off + PAGE)} className="text-accent">
                بعدی ←
              </Link>
            )}
          </div>
        </>
      )}
    </main>
  );
}
