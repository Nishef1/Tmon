import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Screener } from "@/lib/api";
import { jalali } from "@/lib/format";
import { toRow } from "@/lib/industry";
import { ErrorState } from "@/components/ErrorState";
import { IndustryTable } from "@/components/IndustryTable";

export const metadata: Metadata = { title: "صنایع و نمادها" };
export const dynamic = "force-dynamic";

type SP = { q?: string; kind?: string };

export default async function IndustriesPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const all = sp.kind === "all";
  const q = (sp.q ?? "").slice(0, 64);
  const res = await apiGet<Screener>("/screener", {
    sort: "value",
    stocks_only: all ? "false" : "true",
    limit: 3000,
  });
  return (
    <main className="space-y-5">
      <div>
        <h1 className="page-title">صنایع و نمادها</h1>
        <p className="lead">
          همهٔ نمادها به تفکیک صنعت، با بازدهٔ روز، هفته، ماه و سال، ارزش و حجم معاملات، P/E، جریان
          پول حقیقی و تصمیم مدل. صنایع بر پایهٔ معاملات واقعی آخرین روز رتبه‌بندی می‌شوند، نه «حجم
          مبنا»: حجم مبنای ثبت‌شده در بورس برای بیشتر نمادها فقط ۱ است و چیزی را از هم جدا نمی‌کند.
          روی هر نماد بزنید تا همهٔ داده‌هایش باز شود.
        </p>
      </div>
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span>
              قیمت‌ها: {res.data.prices_date ? jalali(res.data.prices_date) : "—"} · پول حقیقی و
              حقوقی: {res.data.flow_date ? jalali(res.data.flow_date) : "—"} · رتبه‌بندی مدل:{" "}
              {res.data.ranking_date ? jalali(res.data.ranking_date) : "هنوز محاسبه نشده"}
            </span>
            <Link
              href={all ? "/industries" : "/industries?kind=all"}
              className="tab tab-pill"
              data-testid="kind-toggle"
            >
              {all ? "نمایش فقط سهام" : "نمایش صندوق، اختیار و اوراق هم"}
            </Link>
          </p>
          <IndustryTable rows={res.data.rows.map(toRow)} initialQuery={q} />
        </>
      )}
    </main>
  );
}
