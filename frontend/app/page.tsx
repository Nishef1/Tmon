import Link from "next/link";
import { apiGet, type Ranking, type Recommendations } from "@/lib/api";
import { jalali } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { TradableRanking } from "@/components/TradableRanking";
import { SignalCard } from "@/components/SignalCard";
import { WhyNoRecommendation } from "@/components/WhyNoRecommendation";

export const dynamic = "force-dynamic";

const TIMEFRAMES = [
  { id: "D1", label: "روزانه (D1)" },
  { id: "W1", label: "هفتگی (W1)" },
  { id: "M1", label: "ماهانه (M1)" },
];

type Search = { tf?: string; date?: string };

export default async function Home({ searchParams }: { searchParams: Promise<Search> }) {
  const { tf = "D1", date } = await searchParams;
  const [res, rank] = await Promise.all([
    apiGet<Recommendations>("/recommendations", { timeframe: tf, date }),
    apiGet<Ranking>("/v2/ranking"),
  ]);

  return (
    <main className="space-y-5">
      <div className="space-y-1">
        <h1 className="text-2xl font-extrabold">توصیه‌های بازار سهام</h1>
        <p className="text-sm text-muted">
          برای هر سهم فقط سه تصمیم ممکن است: خرید، نگهداری یا فروش، همراه دلیل. اغلب روزها دلیلِ
          نبودِ توصیه با عدد گفته می‌شود.
        </p>
      </div>

      <Disclaimer />

      <nav aria-label="تایم‌فریم" className="flex flex-wrap gap-2">
        {TIMEFRAMES.map((t) => (
          <Link
            key={t.id}
            href={`/?tf=${t.id}`}
            aria-current={tf === t.id ? "page" : undefined}
            className={`rounded-full border px-4 py-1.5 text-sm ${
              tf === t.id
                ? "border-accent bg-accent text-surface"
                : "border-line bg-surface hover:bg-accent-soft"
            }`}
          >
            {t.label}
          </Link>
        ))}
      </nav>

      {rank.ok && rank.data.available && <TradableRanking d={rank.data} />}

      <h2 className="pt-2 text-lg font-bold">مدل احتمال v1 (آستانه‌های سود پس از هزینه؛ مکمل)</h2>

      {!res.ok ? <ErrorState message={res.error} /> : <Body data={res.data} tf={tf} />}
    </main>
  );
}

function Body({ data, tf }: { data: Recommendations; tf: string }) {
  if (!data.supported) {
    return (
      <section className="rounded-2xl border border-line bg-surface p-6" data-testid="unsupported">
        <p className="font-semibold">این تایم‌فریم هنوز فعال نیست</p>
        <p className="mt-1 text-sm text-muted">{data.message}</p>
      </section>
    );
  }
  const { run, gate, signals, diagnosis } = data;
  return (
    <>
      <section aria-label="تاریخ" className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="text-muted">داده تا </span>
          <strong>{jalali(data.date, "weekday")}</strong>
        </p>
        {data.available_dates.length > 1 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted">روزهای قبل</summary>
            <ul className="mt-2 flex flex-wrap gap-2">
              {data.available_dates.slice(0, 12).map((d) => (
                <li key={d}>
                  <Link
                    href={`/?tf=${tf}&date=${d}`}
                    className="rounded-md border border-line bg-surface px-2 py-1 hover:bg-accent-soft"
                  >
                    {jalali(d, "short")}
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {run?.defensive_mode && (
        <aside
          role="status"
          className="rounded-xl border border-warn/30 bg-warn-soft p-4 text-sm text-warn"
        >
          <strong>حالت دفاعی فعال است.</strong> عرض بازار ضعیف است یا پول حقیقی چند روز پیاپی خارج
          شده؛ آستانهٔ پذیرش سیگنال بالاتر رفته است.{" "}
          <Link href="/glossary/defensive_mode" className="underline">
            توضیح بیشتر
          </Link>
        </aside>
      )}

      {data.no_recommendation ? (
        <section
          data-testid="no-recommendation"
          className="rounded-2xl border border-line bg-surface p-6 sm:p-8"
        >
          <h2 className="text-xl font-bold">امروز توصیه‌ای وجود ندارد</h2>
          <p className="mt-2 text-muted">{data.message}</p>
          <p className="mt-3 text-sm">
            این وضعیت عادی است. سامانه فقط وقتی سیگنال می‌دهد که احتمال موفقیت و سود مورد انتظار پس
            از هزینه‌ها هر دو از آستانه‌ها بگذرند؛ در بسیاری از روزها هیچ نمادی نمی‌گذراند.
          </p>
          {run && (
            <p className="mt-3 text-sm text-muted">
              نمادهای واجد شرایط پیش از محدودیت‌های پرتفوی:{" "}
              <Num term="candidates" value={run.n_candidates} kind="count" />
            </p>
          )}
          <WhyNoRecommendation diagnosis={diagnosis} gate={gate} />
        </section>
      ) : (
        <section aria-label="فهرست توصیه‌ها" className="space-y-4">
          <p className="text-sm text-muted">
            تعداد توصیه‌ها: <Num term="rank" value={signals.length} kind="count" />
            {run && (
              <>
                {" "}
                از <Num term="candidates" value={run.n_candidates} kind="count" /> نماد واجد شرایط
              </>
            )}
          </p>
          {signals.map((s) => (
            <SignalCard key={s.id} s={s} />
          ))}
        </section>
      )}

      {gate && !gate.tier_a_allowed && !data.no_recommendation && (
        <section
          data-testid="tier-a-gate"
          className="rounded-2xl border border-line bg-surface p-5 text-sm"
        >
          <h2 className="font-bold">چرا سیگنال رده A منتشر نمی‌شود؟</h2>
          <p className="mt-1 text-muted">
            رده A تنها وقتی فعال می‌شود که مدل در آزمون خارج از نمونه، پس از هزینه‌ها، از روش مبنا
            بهتر باشد. این شرط‌ها هنوز برقرار نیستند:
          </p>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {gate.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="mt-3">
            <Link href="/calibration" className="text-accent underline">
              مشاهدهٔ کالیبراسیون و نتایج آزمون
            </Link>
          </p>
        </section>
      )}

      {run && (
        <p className="text-xs text-muted">
          نسخهٔ مدل: <bdi dir="ltr">{run.model_version}</bdi> · شناسهٔ داده:{" "}
          <bdi dir="ltr">{run.data_snapshot_id}</bdi>
        </p>
      )}
    </>
  );
}
