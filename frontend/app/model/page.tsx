import type { Metadata } from "next";
import { apiGet, type Ranking } from "@/lib/api";
import { RankingTrust } from "@/components/model/RankingTrust";
import { CalibrationSection } from "@/components/model/CalibrationSection";
import { AccuracySection } from "@/components/model/AccuracySection";
import { HistorySection } from "@/components/model/HistorySection";

export const metadata: Metadata = { title: "اعتبار مدل" };
export const dynamic = "force-dynamic";

const PARTS = [
  ["v2", "رتبه‌بندی و آزمون"],
  ["calibration", "کالیبراسیون"],
  ["accuracy", "دقت زنده"],
  ["history", "سابقهٔ سیگنال‌ها"],
] as const;

type SP = { outcome?: string; offset?: string; timeframe?: string };

/** Everything that says how far to trust the model, in one place: tests, calibration, live accuracy, history. */
export default async function ModelPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const rank = await apiGet<Ranking>("/v2/ranking");
  return (
    <main className="space-y-10">
      <div>
        <h1 className="page-title">اعتبار مدل</h1>
        <p className="lead">
          چقدر می‌شود به خروجی مدل اعتماد کرد؟ آزمون گذشته‌نگر رتبه‌بندی، کالیبراسیون احتمال‌ها، دقت
          سیگنال‌های واقعاً منتشرشده و سابقهٔ همهٔ آن‌ها، همه در یک صفحه آمده است.
        </p>
        <nav aria-label="بخش‌های صفحه" className="mt-3 flex flex-wrap gap-2">
          {PARTS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="tab tab-pill">
              {label}
            </a>
          ))}
        </nav>
      </div>
      {rank.ok && rank.data.available && <RankingTrust d={rank.data} />}
      <CalibrationSection />
      <AccuracySection timeframe={sp.timeframe} />
      <HistorySection outcome={sp.outcome} offset={sp.offset} />
    </main>
  );
}
