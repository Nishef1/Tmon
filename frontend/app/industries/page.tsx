import Link from "next/link";
import type { Metadata } from "next";
import {
  apiGet,
  type IndustryMap as MapDoc,
  type IndustryOverview,
  type Screener,
} from "@/lib/api";
import { numericKeys, type ColumnCatalog } from "@/lib/columns";
import { jalali } from "@/lib/format";
import { toRow } from "@/lib/industry";
import { ErrorState } from "@/components/ErrorState";
import { IndustryCards } from "@/components/industry/IndustryCards";
import { MarketBlockCard } from "@/components/industry/MarketBlockCard";
import { IndustryMap } from "@/components/IndustryMap";
import { IndustryTable } from "@/components/IndustryTable";

export const metadata: Metadata = { title: "صنایع و نمادها" };
export const dynamic = "force-dynamic";

type SP = { q?: string; kind?: string };

export default async function IndustriesPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const all = sp.kind === "all";
  const q = (sp.q ?? "").slice(0, 64);
  const catalog = await apiGet<ColumnCatalog>("/columns/catalog");
  const [res, map, overview] = await Promise.all([
    apiGet<Screener>("/screener", {
      sort: "value",
      stocks_only: all ? "false" : "true",
      limit: 3000,
      columns: catalog.ok ? numericKeys(catalog.data).join(",") : undefined,
    }),
    apiGet<MapDoc>("/industries/map"),
    apiGet<IndustryOverview>("/industries/overview"),
  ]);
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
      {overview.ok && overview.data.market && <MarketBlockCard m={overview.data.market} />}
      {overview.ok && overview.data.available && <IndustryCards doc={overview.data} />}
      {map.ok && <IndustryMap doc={map.data} />}
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
          <IndustryTable
            rows={res.data.rows.map(toRow)}
            initialQuery={q}
            catalog={catalog.ok ? catalog.data : null}
          />
        </>
      )}
    </main>
  );
}
