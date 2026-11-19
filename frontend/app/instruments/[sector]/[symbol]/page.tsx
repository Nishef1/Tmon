import { notFound, redirect } from "next/navigation";
import { apiGet, type InstrumentSlug } from "@/lib/api";
import { slugPath } from "@/lib/slug";
import { ErrorState } from "@/components/ErrorState";

export const dynamic = "force-dynamic";

/** The first two-segment address (``/instruments/<industry>/<symbol>``) leads to the one address. */
export default async function InstrumentTwoSegments({
  params,
  searchParams,
}: {
  params: Promise<{ sector: string; symbol: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const p = await params;
  const sector = decodeURIComponent(p.sector);
  const symbol = decodeURIComponent(p.symbol);
  const res = await apiGet<InstrumentSlug>(
    `/instruments/by-slug/${encodeURIComponent(sector)}/${encodeURIComponent(symbol)}`,
  );
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
