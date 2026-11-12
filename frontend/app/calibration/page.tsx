import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Calibration, type CalibrationBlock } from "@/lib/api";
import { faDigits, friendlyWarning, jalali } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";

export const metadata: Metadata = { title: "کالیبراسیون" };
export const dynamic = "force-dynamic";

function Reliability({ block }: { block: CalibrationBlock }) {
  const rows = block.buckets.filter((b) => b.n > 0);
  if (rows.length === 0) return <p className="text-sm text-muted">دادهٔ کافی وجود ندارد.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] text-sm">
        <caption className="sr-only">احتمال پیش‌بینی‌شده در برابر نرخ موفقیت واقعی</caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th scope="col" className="px-2 py-1.5 text-start font-medium">
              بازهٔ احتمال
            </th>
            <th scope="col" className="px-2 py-1.5 text-start font-medium">
              نمونه
            </th>
            <th scope="col" className="px-2 py-1.5 text-start font-medium">
              پیش‌بینی
            </th>
            <th scope="col" className="px-2 py-1.5 text-start font-medium">
              واقعی
            </th>
            <th scope="col" className="w-1/3 px-2 py-1.5 text-start font-medium">
              مقایسه
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.bucket} className="border-b border-line last:border-0">
              <td className="px-2 py-1.5">
                <bdi dir="ltr">{faDigits(b.bucket)}</bdi>
              </td>
              <td className="px-2 py-1.5">
                <Num term="sample_size" value={b.n} kind="count" />
              </td>
              <td className="px-2 py-1.5">
                <Num term="p_win" value={b.mean_p} kind="percent" digits={0} />
              </td>
              <td className="px-2 py-1.5">
                <Num term="hit_rate" value={b.hit_rate} kind="percent" digits={0} />
              </td>
              <td className="px-2 py-1.5" aria-hidden="true">
                <div className="h-2 rounded bg-accent-soft">
                  <div
                    className="h-2 rounded bg-muted/60"
                    style={{ width: `${Math.round((b.mean_p ?? 0) * 100)}%` }}
                  />
                </div>
                <div className="mt-1 h-2 rounded bg-accent-soft">
                  <div
                    className="h-2 rounded bg-accent"
                    style={{ width: `${Math.round((b.hit_rate ?? 0) * 100)}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        نوار بالا: احتمال پیش‌بینی‌شده · نوار پایین: نرخ موفقیت واقعی. اگر مدل کالیبره باشد، دو نوار
        تقریباً هم‌اندازه‌اند.
      </p>
    </div>
  );
}

function Stats({ block }: { block: CalibrationBlock }) {
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
      {[
        ["نمونه", <Num key="n" term="sample_size" value={block.n} kind="count" />],
        [
          "نرخ پایه",
          <Num key="b" term="base_rate" value={block.base_rate} kind="percent" digits={1} />,
        ],
        ["AUC", <Num key="a" term="auc" value={block.auc} digits={3} />],
        ["امتیاز بریر", <Num key="br" term="brier" value={block.brier} digits={3} />],
        [
          "مهارت بریر",
          <Num key="s" term="brier_skill" value={block.brier_skill} digits={3} signed />,
        ],
      ].map(([label, node]) => (
        <div key={String(label)} className="rounded-xl border border-line bg-bg p-3">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="text-lg font-bold">{node}</dd>
        </div>
      ))}
    </dl>
  );
}

export default async function CalibrationPage() {
  const res = await apiGet<Calibration>("/metrics/calibration", { timeframe: "D1" });
  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">کالیبراسیون و کیفیت مدل</h1>
        <p className="mt-1 text-sm text-muted">
          آیا وقتی مدل می‌گوید «۶۰٪» تقریباً ۶۰٪ از موارد موفق می‌شوند؟ این صفحه هم آزمون گذشته‌نگر
          (خارج از نمونه) و هم نتیجهٔ سیگنال‌های واقعاً منتشرشده را نشان می‌دهد.
        </p>
      </div>
      <Disclaimer />
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <section className="rounded-2xl border border-line bg-surface p-4 text-sm">
            {res.data.model_version ? (
              <p>
                نسخهٔ مدل: <bdi dir="ltr">{res.data.model_version}</bdi>
                {res.data.trained_through && (
                  <> · آموزش تا {jalali(res.data.trained_through, "long")}</>
                )}
              </p>
            ) : (
              <p data-testid="no-model">هنوز مدلی آموزش داده نشده است.</p>
            )}
            {res.data.gate && (
              <div className="mt-3" data-testid="gate">
                <p className="font-semibold">
                  {res.data.gate.tier_a_allowed
                    ? "شرط‌های انتشار رده A برقرارند."
                    : "سیگنال رده A منتشر نمی‌شود."}
                </p>
                {res.data.gate.reasons.length > 0 && (
                  <ul className="mt-1 list-inside list-disc text-muted">
                    {res.data.gate.reasons.map((r) => (
                      <li key={r}>{faDigits(r)}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>

          {res.data.warnings.length > 0 && (
            <aside className="rounded-xl border border-warn/30 bg-warn-soft p-4 text-sm text-warn">
              <p className="font-semibold">هشدارها</p>
              <ul className="mt-1 list-inside list-disc">
                {res.data.warnings.map((w) => (
                  <li key={w}>{friendlyWarning(w)}</li>
                ))}
              </ul>
            </aside>
          )}

          <section className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <h2 className="font-bold">آزمون گذشته‌نگر (خارج از نمونه)</h2>
            {res.data.backtest ? (
              <>
                <Stats block={res.data.backtest} />
                <Reliability block={res.data.backtest} />
              </>
            ) : (
              <p className="text-sm text-muted">نتیجهٔ آزمونی ثبت نشده است.</p>
            )}
          </section>

          <section className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <h2 className="font-bold">سیگنال‌های منتشرشده (نتیجهٔ واقعی)</h2>
            {res.data.live.n === 0 ? (
              <p className="text-sm text-muted" data-testid="no-live">
                هنوز سیگنالی منتشر و بسته نشده است؛ پس از بسته شدن اولین سیگنال‌ها این بخش پر
                می‌شود.
              </p>
            ) : (
              <>
                <Stats block={res.data.live} />
                <Reliability block={res.data.live} />
              </>
            )}
          </section>

          <p className="text-sm">
            معنی هر عدد در{" "}
            <Link href="/glossary" className="text-accent underline">
              واژه‌نامه
            </Link>{" "}
            آمده است.
          </p>
        </>
      )}
    </main>
  );
}
