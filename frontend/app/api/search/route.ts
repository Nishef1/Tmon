import { apiGet, type SymbolSearch } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Browser-side symbol search goes through here so the API host never has to be public. */
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const q = (params.get("q") ?? "").trim().slice(0, 64);
  if (!q) return Response.json({ query: "", total: 0, hits: [] });
  const res = await apiGet<SymbolSearch>("/search", {
    q,
    limit: 12,
    active_only: params.get("active") === "1" ? "true" : undefined,
  });
  if (!res.ok) return Response.json({ error: res.error }, { status: res.status });
  return Response.json(res.data);
}
