import Link from "next/link";
import { apiGet, type History } from "@/lib/api";
import type { GlossaryKey } from "@/lib/glossary";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { SignalTable } from "@/components/SignalTable";

const PAGE = 25;
const FILTERS = [
  { id: "", label: "همه" },
  { id: "tp", label: "حد سود" },
  { id: "sl", label: "حد ضرر" },
  { id: "expiry", label: "پایان بازهٔ نگهداری" },
  { id: "pending", label: "هنوز باز است" },
];

export type Search = { outcome?: string; offset?: string };

export async function HistorySection({ outcome = "", offset = "0" }: Search) {
  const off = Math.max(0, Number.parseInt(offset, 10) || 0);
  const res = await apiGet<History>("/signals/history", {
    timeframe: "D1",
    outcome,
    limit: PAGE,
    offset: off,
  });
  const href = (o: string, n: number) =>
    `/model?${new URLSearchParams({ ...(o ? { outcome: o } : {}), ...(n ? { offset: String(n) } : {}) })}#history`;

  return (
    <section id="history" className="scroll-mt-20 space-y-5">
      <div>
        <h2 className="text-xl font-extrabold">سابقهٔ سیگنال‌ها</h2>
        <p className="mt-1 text-sm text-muted">
          نتیجهٔ همهٔ سیگنال‌های منتشرشده، چه موفق و چه ناموفق. بازده‌ها ناخالص (پیش از هزینه‌ها) و
          مربوط به گذشته‌اند و آینده را تضمین نمی‌کنند.
        </p>
      </div>

      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <section aria-label="خلاصه" className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {(
              [
                ["کل سیگنال‌ها", "signals_count", res.data.summary.total],
                ["به حد سود رسید", "tp_count", res.data.summary.take_profit],
                ["به حد ضرر رسید", "sl_count", res.data.summary.stop_loss],
                ["پایان بازهٔ نگهداری", "expiry_count", res.data.summary.expired],
                ["هنوز باز است", "pending_count", res.data.summary.pending],
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
                className="tab tab-pill"
              >
                {f.label}
              </Link>
            ))}
          </nav>

          {res.data.items.length === 0 ? (
            <p data-testid="history-empty" className="card card-pad-lg text-sm text-muted">
              هنوز سیگنالی منتشر نشده است. تا وقتی هیچ نمادی شرایط توصیه را نداشته باشد، چیزی در این
              فهرست ثبت نمی‌شود؛ دلیل دقیق را در صفحهٔ رتبه‌بندی ببینید.
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
    </section>
  );
}
