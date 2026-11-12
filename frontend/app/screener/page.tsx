import { redirect } from "next/navigation";

type SP = { q?: string; kind?: string };

/** The old «همهٔ نمادها» list is part of «صنایع و نمادها» now; old links keep working. */
export default async function ScreenerRedirect({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const p = new URLSearchParams();
  if (sp.q) p.set("q", sp.q);
  if (sp.kind === "all") p.set("kind", "all");
  redirect(`/industries${p.size ? `?${p}` : ""}`);
}
