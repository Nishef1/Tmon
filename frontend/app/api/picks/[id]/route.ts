import { API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function DELETE(_: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ error: "شناسه نامعتبر است." }, { status: 400 });
  const res = await fetch(new URL(`/picks/${id}`, API_BASE), {
    method: "DELETE",
    cache: "no-store",
  }).catch(() => null);
  if (!res) return Response.json({ error: "ارتباط با سرور برقرار نشد." }, { status: 502 });
  return Response.json(await res.json().catch(() => ({})), { status: res.status });
}
