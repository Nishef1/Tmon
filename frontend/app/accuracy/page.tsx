import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type LiveAccuracy } from "@/lib/api";
import { faNumber, jalali } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";

export const metadata: Metadata = { title: "دقت زنده" };
export const dynamic = "force-dynamic";

const TIMEFRAMES = [
  ["D1", "روزانه"],
  ["W1", "هفتگی"],
  ["M1", "ماهانه"],
] as const;

export default async function AccuracyPage({
  searchParams,
}: {
  searchParams: Promise<{ timeframe?: string }>;
}) {
  const sp = await searchParams;
  const tf = TIMEFRAMES.find(([t]) => t === sp.timeframe)?.[0] ?? "D1";
  const res = await apiGet<LiveAccuracy>("/metrics/live", { timeframe: tf });

  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">دقت زنده</h1>
        <p className="mt-1 text-sm text-muted">
          نتیجهٔ سیگنال‌هایی که واقعاً منتشر شده‌اند، به تفکیک روز سیگنال. اگر امتیاز بریر بیست روز
          اخیر بیش از ۲۰٪ از بریر آزمون گذشته‌نگر بدتر شود، انتشار توصیه متوقف می‌شود.
        </p>
      </div>
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="افق">
        {TIMEFRAMES.map(([t, label]) => (
          <Link
            key={t}
            href={`/accuracy?timeframe=${t}`}
            aria-current={t === tf ? "page" : undefined}
            className="tab"
          >
            {label}
          </Link>
        ))}
      </nav>
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <section className="card space-y-2 text-sm">
            <p data-testid="kill-switch">
              {res.data.kill_switch_active ? (
                <strong className="text-down">
                  توقف انتشار فعال است: کیفیت احتمال‌ها در روزهای اخیر افت کرده است.
                </strong>
              ) : (
                <span>توقف انتشار فعال نیست.</span>
              )}
              {res.data.defensive_mode != null && (
                <>
                  {" "}
                  ·{" "}
                  <Link href="/glossary/defensive_mode" className="underline">
                    حالت دفاعی
                  </Link>{" "}
                  آخرین روز: {res.data.defensive_mode ? "روشن" : "خاموش"}
                </>
              )}
            </p>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted">سیگنال‌های بسته‌شده</dt>
                <dd>
                  <Num value={res.data.resolved} kind="count" term="sample_size" /> · باز:{" "}
                  <Num value={res.data.pending} kind="count" term="pending_count" />
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">نرخ موفقیت / میانگین احتمال</dt>
                <dd>
                  {res.data.hit_rate != null && res.data.mean_p != null ? (
                    <>
                      <Num value={res.data.hit_rate} kind="percent" term="hit_rate" digits={1} /> /{" "}
                      <Num value={res.data.mean_p} kind="percent" term="p_win" digits={1} />
                    </>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">امتیاز بریر (کمتر بهتر است)</dt>
                <dd>
                  {faNumber(res.data.recent_days)} روز اخیر ({faNumber(res.data.recent_n)} سیگنال):{" "}
                  {res.data.recent_brier != null ? (
                    <Num value={res.data.recent_brier} kind="plain" term="brier" digits={3} />
                  ) : (
                    "—"
                  )}
                  <br />
                  آزمون گذشته‌نگر:{" "}
                  {res.data.backtest_brier != null ? (
                    <Num value={res.data.backtest_brier} kind="plain" term="brier" digits={3} />
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
            </dl>
          </section>
          {res.data.days.length === 0 ? (
            <p className="text-sm text-muted" data-testid="no-resolved">
              هنوز هیچ سیگنالی در این افق بسته نشده است.
            </p>
          ) : (
            <div className="card overflow-x-auto">
              <table className="tbl min-w-[28rem]">
                <caption className="sr-only">دقت سیگنال‌ها به تفکیک روز</caption>
                <thead>
                  <tr className="border-b border-line">
                    {["روز سیگنال", "تعداد", "موفق", "میانگین احتمال", "بریر"].map((h) => (
                      <th key={h} scope="col">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {res.data.days.map((d) => (
                    <tr key={d.date} className="border-b border-line last:border-0">
                      <td className="px-2 py-1.5">{jalali(d.date)}</td>
                      <td className="px-2 py-1.5">
                        <Num value={d.n} kind="count" term="signals_count" />
                      </td>
                      <td className="px-2 py-1.5">
                        <Num value={d.hits} kind="count" term="tp_count" />
                      </td>
                      <td className="px-2 py-1.5">
                        <Num value={d.mean_p} kind="percent" term="p_win" digits={1} />
                      </td>
                      <td className="px-2 py-1.5">
                        <Num value={d.brier} kind="plain" term="brier" digits={3} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
