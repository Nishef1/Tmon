import Link from "next/link";
import { notFound } from "next/navigation";
import { apiGet, type InstrumentDetail } from "@/lib/api";
import { featureInfo } from "@/lib/glossary";
import { jalali } from "@/lib/format";
import { LiveQuote } from "@/components/LiveQuote";
import { CandleChart, type Level } from "@/components/CandleChart";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { SignalTable } from "@/components/SignalTable";

export const dynamic = "force-dynamic";

export default async function InstrumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const res = await apiGet<InstrumentDetail>(`/instruments/${id}`);
  if (!res.ok && res.status === 404) notFound();
  if (!res.ok) {
    return (
      <main className="space-y-4">
        <ErrorState message={res.error} />
      </main>
    );
  }
  const d = res.data;
  const open = d.signals.find((s) => s.outcome === "pending");
  const levels: Level[] = open
    ? [
        { price: open.take_profit, title: "حد سود", color: "#1d6a43" },
        { price: open.entry_price, title: "مرجع", color: "#6b675f" },
        { price: open.stop_loss, title: "حد ضرر", color: "#a32d2d" },
      ]
    : [];

  return (
    <main className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-accent">
          ← توصیه‌های امروز
        </Link>
        <h1 className="mt-2 text-2xl font-extrabold">{d.instrument.symbol}</h1>
        {d.instrument.name && <p className="text-muted">{d.instrument.name}</p>}
      </div>

      <Disclaimer />

      <LiveQuote instrumentId={d.instrument.id} />

      <section className="rounded-2xl border border-line bg-surface p-4">
        <h2 className="mb-2 font-bold">نمودار قیمت تعدیل‌شده</h2>
        {d.candles.length === 0 ? (
          <p className="text-sm text-muted">دادهٔ قیمتی برای این نماد موجود نیست.</p>
        ) : (
          <>
            <CandleChart candles={d.candles} levels={levels} />
            <p className="mt-2 text-xs text-muted">
              قیمت‌ها برای سود نقدی و افزایش سرمایه{" "}
              <Link href="/glossary/adjusted_price" className="underline">
                تعدیل
              </Link>{" "}
              شده‌اند. روزهای توقف نماد نمایش داده نمی‌شوند.
              {open && " خط‌چین‌ها سطح‌های آخرین سیگنال بازِ این نماد هستند."}
            </p>
          </>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-4">
        <h2 className="mb-2 font-bold">
          شاخص‌ها
          {d.features_date && (
            <span className="text-sm font-normal text-muted">
              {" "}
              · {jalali(d.features_date, "short")}
            </span>
          )}
        </h2>
        {d.features.length === 0 ? (
          <p className="text-sm text-muted">شاخصی برای این نماد محاسبه نشده است.</p>
        ) : (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {d.features.map((f) => {
              const info = featureInfo(f.feature);
              return (
                <div key={f.feature} className="flex justify-between border-b border-line py-1.5">
                  <dt>
                    <Link href={`/glossary/${info.term}`} className="hover:text-accent">
                      {info.label}
                    </Link>
                  </dt>
                  <dd className="font-semibold">
                    <Num term={info.term} value={f.value} digits={2} />
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="font-bold">سیگنال‌های منتشرشده برای این نماد</h2>
        {d.signals.length === 0 ? (
          <p className="text-sm text-muted">تاکنون سیگنالی برای این نماد منتشر نشده است.</p>
        ) : (
          <SignalTable items={d.signals} showSymbol={false} />
        )}
      </section>
    </main>
  );
}
