import { apiGet, type SymbolSearch } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Browser-side symbol search goes through here so the API host never has to be public. */
export async function GET(request: Request) {
  const q = (new URL(request.url).searchParams.get("q") ?? "").trim().slice(0, 64);
  if (!q) return Response.json({ query: "", total: 0, hits: [] });
  const res = await apiGet<SymbolSearch>("/search", { q, limit: 12 });
  if (!res.ok) return Response.json({ error: res.error }, { status: res.status });
  return Response.json(res.data);
}
