import { notFound, redirect } from "next/navigation";
import { apiGet, type InstrumentSlug } from "@/lib/api";
import { slugPath } from "@/lib/slug";
import { ErrorState } from "@/components/ErrorState";

export const dynamic = "force-dynamic";

/** Old numeric links (``/instruments/123``) go to the readable address. */
export default async function InstrumentById({
  params,
  searchParams,
}: {
  params: Promise<{ sector: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { sector } = await params;
  if (!/^\d+$/.test(sector)) notFound();
  const res = await apiGet<InstrumentSlug>(`/instruments/${sector}/slug`);
  if (!res.ok && res.status === 404) notFound();
  if (!res.ok) {
    return (
      <main className="space-y-4">
        <ErrorState message={res.error} />
      </main>
    );
  }
  const q = await searchParams;
  const keep = new URLSearchParams(
    Object.entries(q).flatMap(([k, v]) => (v === undefined ? [] : [[k, v]])),
  ).toString();
  redirect(slugPath(res.data) + (keep ? `?${keep}` : ""));
}
