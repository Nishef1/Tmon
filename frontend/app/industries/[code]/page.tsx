import Link from "next/link";
import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { apiGet, type IndustryDetail } from "@/lib/api";
import type { ColumnCatalog } from "@/lib/columns";
import { ErrorState } from "@/components/ErrorState";
import { IndustryDetailView } from "@/components/industry/IndustryDetailView";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ code: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { code } = await params;
  const res = await apiGet<IndustryDetail>(
    `/industries/${encodeURIComponent(readable(code))}/detail`,
  );
  return { title: res.ok ? `صنعت ${res.data.name}` : "صنعت" };
}

/** The address carries the industry's name (``/industries/<name>``); the old numeric code works
 *  and leads to the name. */
function readable(code: string): string {
  try {
    return decodeURIComponent(code);
  } catch {
    return code;
  }
}

export default async function IndustryPage({ params }: Props) {
  const key = readable((await params).code);
  const [res, catalog] = await Promise.all([
    apiGet<IndustryDetail>(`/industries/${encodeURIComponent(key)}/detail`, { days: 300 }),
    apiGet<ColumnCatalog>("/columns/catalog"),
  ]);
  if (!res.ok && res.status === 404) notFound();
  if (res.ok && /^\d{1,3}$/.test(key) && res.data.slug) {
    redirect(`/industries/${encodeURIComponent(res.data.slug)}`);
  }
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
