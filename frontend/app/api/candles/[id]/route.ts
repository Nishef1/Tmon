import { apiGet, type InstrumentDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Browser-side symbol candles (an industry's member opened in place) go through here so the API
 *  host never has to be public. Only the adjusted candles are passed on. */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^\d{1,9}$/.test(id)) return Response.json({ error: "bad id" }, { status: 400 });
  const days = Math.min(
    Math.max(Number(new URL(request.url).searchParams.get("days")) || 180, 20),
    600,
  );
  const res = await apiGet<InstrumentDetail>(`/instruments/${id}`, { days });
  if (!res.ok) return Response.json({ error: res.error }, { status: res.status });
  return Response.json({ candles: res.data.candles });
}
