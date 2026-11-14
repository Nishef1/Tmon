import { API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Browser-side "I bought it" goes through here so the API host never has to be public. */
export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as {
    instrument_id?: number;
    paid_price?: number | null;
    note?: string | null;
  } | null;
  if (!body || !Number.isInteger(body.instrument_id)) {
    return Response.json({ error: "نماد نامعتبر است." }, { status: 400 });
  }
  const res = await fetch(new URL("/picks", API_BASE), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      instrument_id: body.instrument_id,
      paid_price: body.paid_price || null,
      note: body.note?.slice(0, 300) || null,
    }),
    cache: "no-store",
  }).catch(() => null);
  if (!res) return Response.json({ error: "ارتباط با سرور برقرار نشد." }, { status: 502 });
  return Response.json(await res.json().catch(() => ({})), { status: res.status });
}
