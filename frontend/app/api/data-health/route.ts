import { API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

/** The data-completeness check and the refill button run in the browser; both go through here so
 *  the API host never has to be public. Nothing is cached: a gap that was just filled must show
 *  as filled on the next poll. */
async function forward(method: "GET" | "POST"): Promise<Response> {
  const url = new URL(method === "POST" ? "/data-health/refill" : "/data-health", API_BASE);
  const res = await fetch(url, { method, cache: "no-store" }).catch(() => null);
  if (!res) return Response.json({ detail: "ارتباط با سرور برقرار نشد." }, { status: 502 });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export const GET = () => forward("GET");
export const POST = () => forward("POST");
