import Link from "next/link";
import { apiGet, type MarketOverview, type Ranking, type Recommendations } from "@/lib/api";
import { jalali } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { TradableRanking } from "@/components/TradableRanking";
import { ZoneTables } from "@/components/ZoneTables";
import { OutsideBasket } from "@/components/OutsideBasket";
import { ExposureCard } from "@/components/ExposureCard";
import { SignalCard } from "@/components/SignalCard";
import { WhyNoRecommendation } from "@/components/WhyNoRecommendation";
import { Heatmap } from "@/components/today/Heatmap";
import { MarketStrip } from "@/components/today/MarketStrip";
import { StockTable } from "@/components/today/StockTable";

export const dynamic = "force-dynamic";

const TIMEFRAMES = [
  { id: "D1", label: "روزانه (D1)" },
  { id: "W1", label: "هفتگی (W1)" },
  { id: "M1", label: "ماهانه (M1)" },
];

type Search = { tf?: string; date?: string };

export default async function Home({ searchParams }: { searchParams: Promise<Search> }) {
  const { tf = "D1", date } = await searchParams;
  const [res, rank, market] = await Promise.all([
    apiGet<Recommendations>("/recommendations", { timeframe: tf, date }),
    apiGet<Ranking>("/v2/ranking"),
    apiGet<MarketOverview>("/market/overview"),
  ]);
  const ranked = rank.ok && rank.data.available ? rank.data : null;
  // what an ordinary buyer can act on: no funds, nothing stuck in a sell queue
  const rows = ranked
    ? ranked.rows.filter(
        (r) => !(r.name ?? "").startsWith("صندوق") && r.queue_state !== "sell_queue",
      )
    : [];

  return (
    <main className="space-y-5">
      <div className="space-y-1">
        <h1 className="page-title">امروز بازار چه شد؟</h1>
        <p className="lead">
          خلاصهٔ بازار، نقشهٔ سهم‌های پرمعامله و رتبهٔ هر سهم. رتبه‌بندی فقط یک ابزار کمکی است و
          توصیهٔ قطعی نیست.
        </p>
      </div>

      {market.ok && market.data.available && <MarketStrip m={market.data} />}

      {ranked && (
        <>
          <Heatmap rows={rows} />
          <StockTable rows={rows} />
          <p className="text-xs leading-6 text-muted" data-testid="today-note">
            رتبه‌بندی برای نگه‌داری حدود یک هفته یا بیشتر آزموده شده و برای یک روز، پس از کارمزد،
            سودی ندارد. هنوز همهٔ آزمون‌های اعتبار نگذشته‌اند؛ دلیل هر سهم در صفحهٔ خودش است.{" "}
            <Link href="/model#v2" className="text-accent underline">
              نتیجهٔ آزمون‌ها
            </Link>
          </p>
          <details className="card" data-testid="zone-details">
            <summary className="cursor-pointer font-semibold">
              نمای ناحیه‌ها، خارج از سبد و میزان سرمایه در سهام
            </summary>
            <div className="mt-4 space-y-5">
              <TradableRanking d={ranked} />
              <OutsideBasket d={ranked} />
              <ExposureCard d={ranked} />
              <ZoneTables d={ranked} />
            </div>
          </details>
        </>
      )}

      <details className="card" data-testid="v1-details" open={tf !== "D1" || date != null}>
        <summary className="cursor-pointer font-semibold">
          مدل احتمال (آزمایشی): سیگنال روزانه، هفتگی و ماهانه
        </summary>
        <div className="mt-4 space-y-4">
          <p className="text-sm text-muted">
            این مدل هنوز از آزمون‌ها نگذشته؛ اغلب روزها هیچ سیگنالی نمی‌دهد و نباید مبنای خرید باشد.
          </p>
          <nav aria-label="تایم‌فریم" className="flex flex-wrap gap-2">
            {TIMEFRAMES.map((t) => (
              <Link
                key={t.id}
                href={`/?tf=${t.id}`}
                aria-current={tf === t.id ? "page" : undefined}
                className="tab tab-pill"
              >
                {t.label}
              </Link>
            ))}
          </nav>
          {!res.ok ? <ErrorState message={res.error} /> : <Body data={res.data} tf={tf} />}
        </div>
      </details>
    </main>
  );
}

function Body({ data, tf }: { data: Recommendations; tf: string }) {
  if (!data.supported) {
    return (
      <section className="card card-pad-lg" data-testid="unsupported">
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
                  <Link href={`/?tf=${tf}&date=${d}`} className="chip">
                    {jalali(d, "short")}
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {run?.defensive_mode && (
        <aside role="status" className="alert-warn alert-lg">
          <strong>حالت دفاعی فعال است.</strong> عرض بازار ضعیف است یا پول حقیقی چند روز پیاپی خارج
          شده؛ آستانهٔ پذیرش سیگنال بالاتر رفته است.{" "}
          <Link href="/glossary/defensive_mode" className="underline">
            توضیح بیشتر
          </Link>
        </aside>
      )}

      {data.no_recommendation ? (
        <section data-testid="no-recommendation" className="card card-pad-lg sm:p-8">
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
        <section data-testid="tier-a-gate" className="card p-5 text-sm">
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
            <Link href="/model#calibration" className="text-accent underline">
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
