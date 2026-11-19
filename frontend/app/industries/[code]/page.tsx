import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { apiGet, type IndustryDetail } from "@/lib/api";
import type { ColumnCatalog } from "@/lib/columns";
import { ErrorState } from "@/components/ErrorState";
import { IndustryDetailView } from "@/components/industry/IndustryDetailView";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ code: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { code } = await params;
  const res = /^\d{1,3}$/.test(code)
    ? await apiGet<IndustryDetail>(`/industries/${code}/detail`)
    : null;
  return { title: res?.ok ? `صنعت ${res.data.name}` : "صنعت" };
}

export default async function IndustryPage({ params }: Props) {
  const { code } = await params;
  if (!/^\d{1,3}$/.test(code)) notFound();
  const [res, catalog] = await Promise.all([
    apiGet<IndustryDetail>(`/industries/${code}/detail`, { days: 300 }),
    apiGet<ColumnCatalog>("/columns/catalog"),
  ]);
  if (!res.ok && res.status === 404) notFound();
  return (
    <main className="space-y-5">
      <div className="space-y-1">
        <nav className="text-xs text-muted" aria-label="مسیر">
          <Link href="/industries" className="underline">
            صنایع و نمادها
          </Link>
        </nav>
        <h1 className="page-title">{res.ok ? res.data.name : "صنعت"}</h1>
        <p className="lead">
          صنعت به‌صورت اجماع همهٔ نمادهایش: کندل‌های صنعت، حال نمادها و جای هر نماد در حرکت صنعت.
        </p>
      </div>
      {res.ok ? (
        <IndustryDetailView d={res.data} catalog={catalog.ok ? catalog.data : null} />
      ) : (
        <ErrorState message={res.error} />
      )}
    </main>
  );
}
