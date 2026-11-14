import type { Metadata } from "next";
import { apiGet, entryOdds, orderbookResearch, type Ranking } from "@/lib/api";
import { BookResearch } from "@/components/book/BookResearch";
import { EntryLab } from "@/components/entry/EntryLab";
import { RankingTrust } from "@/components/model/RankingTrust";
import { CalibrationSection } from "@/components/model/CalibrationSection";
import { AccuracySection } from "@/components/model/AccuracySection";
import { HistorySection } from "@/components/model/HistorySection";

export const metadata: Metadata = { title: "شانس ورود و اعتبار مدل" };
export const dynamic = "force-dynamic";

const PARTS = [
  ["entry", "آزمایشگاه ورود"],
  ["v2", "رتبه‌بندی و آزمون"],
  ["book", "تابلو و صف"],
  ["calibration", "کالیبراسیون"],
  ["accuracy", "دقت زنده"],
  ["history", "سابقهٔ سیگنال‌ها"],
] as const;

type SP = { outcome?: string; offset?: string; timeframe?: string };

/** Everything that says how far to trust the model, in one place: tests, calibration, live accuracy, history. */
export default async function ModelPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const [rank, odds, book] = await Promise.all([
    apiGet<Ranking>("/v2/ranking"),
    entryOdds(),
    orderbookResearch(),
  ]);
  return (
    <main className="space-y-10">
      <div>
        <h1 className="page-title">شانس ورود و اعتبار مدل</h1>
        <p className="lead">
          سؤال اصلی خریدار این است که «از فردا هم سبز می‌ماند؟». بخش اول نشان می‌دهد بعد از هر نوع
          کندل (چند سبز یا قرمز پشت سر هم، خروج از کف، اصلاح در روند صعودی) کندل‌های بعدی در کل
          تاریخچهٔ بورس چند بار بالاتر رفته‌اند و آیا این از خریدن هر سهم دیگری بهتر بوده. بخش‌های
          بعد می‌گویند به رتبه‌بندی و احتمال‌های مدل چقدر می‌شود اعتماد کرد.
        </p>
        <nav aria-label="بخش‌های صفحه" className="mt-3 flex flex-wrap gap-2">
          {PARTS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="tab tab-pill">
              {label}
            </a>
          ))}
        </nav>
      </div>
      {odds?.available ? (
        <EntryLab d={odds} />
      ) : (
        <section id="entry" className="card text-sm text-muted">
          آزمون شانس ورود هنوز ساخته نشده یا در دسترس نیست.
        </section>
      )}
      {rank.ok && rank.data.available && <RankingTrust d={rank.data} />}
      {book?.available ? (
        <BookResearch d={book} />
      ) : (
        <section id="book" className="card text-sm text-muted">
          آزمون تابلو و صف هنوز ساخته نشده یا در دسترس نیست.
        </section>
      )}
      <CalibrationSection />
      <AccuracySection timeframe={sp.timeframe} />
      <HistorySection outcome={sp.outcome} offset={sp.offset} />
    </main>
  );
}
