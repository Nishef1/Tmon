import { API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path?: string[] }> };

/** The portfolio pages run in the browser (each owner keeps their key there); every call goes
 * through here with the key header, so the API host never has to be public. */
async function forward(request: Request, ctx: Ctx): Promise<Response> {
  const { path = [] } = await ctx.params;
  if (path.some((p) => !/^[\w-]+$/.test(p))) {
    return Response.json({ detail: "مسیر نامعتبر است." }, { status: 400 });
  }
  const url = new URL(["/portfolios", ...path].join("/").replace(/\/+$/, ""), API_BASE);
  url.search = new URL(request.url).search;
  const headers: Record<string, string> = { "content-type": "application/json" };
  const key = request.headers.get("x-portfolio-key");
  if (key) headers["X-Portfolio-Key"] = key;
  const body = ["POST", "PATCH", "PUT"].includes(request.method) ? await request.text() : undefined;
  const res = await fetch(url, { method: request.method, headers, body, cache: "no-store" }).catch(
    () => null,
  );
  if (!res) return Response.json({ detail: "ارتباط با سرور برقرار نشد." }, { status: 502 });
  if (res.status === 204) return new Response(null, { status: 204 });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
