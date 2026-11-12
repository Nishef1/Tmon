import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Screener, type ScreenerRow } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Gauge } from "@/components/Gauge";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";

export const metadata: Metadata = { title: "همهٔ نمادها" };
export const dynamic = "force-dynamic";

const SORTS = [
  ["gauge", "امتیاز مدل"],
  ["rank", "رتبهٔ سبد پرمعامله"],
  ["value", "ارزش معاملات"],
  ["change_pct", "تغییر قیمت"],
  ["power", "قدرت خریدار"],
  ["net_real_value", "خالص ورود پول حقیقی"],
  ["volume_ratio_30", "نسبت حجم به ۳۰ روز"],
  ["rsi_14", "RSI"],
] as const;

const VERDICTS = [
  ["", "همه"],
  ["buy", "خرید"],
  ["hold", "نگهداری"],
  ["sell", "فروش"],
  ["none", "تصمیمی نیست"],
] as const;

const BADGE: Record<string, string> = {
  buy: "bg-good text-white",
  hold: "bg-hold text-white",
  sell: "bg-bad text-white",
  none: "bg-line text-muted",
};

const PAGE = 200;

type SP = { sort?: string; q?: string; v?: string; kind?: string; limit?: string };

function href(sp: SP, over: Partial<SP>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...sp, ...over })) if (v) p.set(k, v);
  return `/screener?${p.toString()}`;
}

/** Rial amount in short toman units. */
function toman(rial: number | null | undefined): string {
  if (rial == null) return "—";
  const t = rial / 10;
  const a = Math.abs(t);
  if (a >= 1e12) return `${faNumber(t / 1e12, 2)} همت`;
  if (a >= 1e9) return `${faNumber(t / 1e9, 1)} میلیارد`;
  if (a >= 1e6) return `${faNumber(t / 1e6, 1)} میلیون`;
  return faNumber(t);
}

const tone = (n: number | null | undefined) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");

export default async function ScreenerPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const sort = SORTS.find(([s]) => s === sp.sort)?.[0] ?? "gauge";
  const verdict = VERDICTS.find(([v]) => v === sp.v)?.[0] ?? "";
  const stocksOnly = sp.kind !== "all";
  const limit = sp.limit === "all" ? 3000 : PAGE;
  const q = (sp.q ?? "").slice(0, 64);
  const res = await apiGet<Screener>("/screener", {
    sort,
    q: q || undefined,
    verdict: verdict || undefined,
    stocks_only: stocksOnly ? "true" : undefined,
    limit,
  });
  const cur: SP = { sort, q, v: verdict, kind: sp.kind, limit: sp.limit };

  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">همهٔ نمادها</h1>
        <p className="mt-1 text-sm text-muted">
          هر نماد با قیمت، حجم، پول حقیقی، سرانه و قدرت خریدار و یکی از سه تصمیم نهایی. تصمیم فقط
          برای سهم‌های پرمعامله صادر می‌شود؛ بقیه «تصمیمی نیست» دارند و دلیلشان در صفحهٔ نماد است.
        </p>
      </div>
      <Disclaimer />
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <section className="space-y-2 rounded-2xl border border-line bg-surface p-4 text-sm">
            <p>
              قیمت‌ها: {res.data.prices_date ? jalali(res.data.prices_date) : "—"} · پول حقیقی و
              حقوقی: {res.data.flow_date ? jalali(res.data.flow_date) : "—"} · رتبه‌بندی مدل:{" "}
              {res.data.ranking_date ? jalali(res.data.ranking_date) : "هنوز محاسبه نشده"}
            </p>
            <ul className="flex flex-wrap gap-2" data-testid="verdict-counts">
              {VERDICTS.slice(1).map(([v, label]) => (
                <li key={v}>
                  <Link
                    href={href(cur, { v: verdict === v ? "" : v })}
                    aria-current={verdict === v ? "page" : undefined}
                    className={`inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 hover:bg-accent-soft aria-[current=page]:border-accent`}
                  >
                    <span className={`rounded-full px-2 text-xs font-bold ${BADGE[v]}`}>
                      {label}
                    </span>
                    {faNumber(res.data.verdict_counts[v] ?? 0)}
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-bold">فهرست ({faNumber(res.data.total)} نماد)</h2>
            <form className="flex flex-wrap items-end gap-2 text-sm" action="/screener">
              <input type="hidden" name="v" value={verdict} />
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">جست‌وجوی نماد یا نام</span>
                <input
                  name="q"
                  defaultValue={q}
                  className="rounded-lg border border-line bg-surface px-3 py-1.5"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">مرتب‌سازی</span>
                <select
                  name="sort"
                  defaultValue={sort}
                  className="rounded-lg border border-line bg-surface px-3 py-1.5"
                >
                  {SORTS.map(([s, l]) => (
                    <option key={s} value={s}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">نوع نماد</span>
                <select
                  name="kind"
                  defaultValue={stocksOnly ? "stock" : "all"}
                  className="rounded-lg border border-line bg-surface px-3 py-1.5"
                >
                  <option value="stock">فقط سهام</option>
                  <option value="all">سهام، صندوق، اختیار و اوراق</option>
                </select>
              </label>
              <button className="rounded-lg border border-line px-3 py-1.5 font-semibold">
                نمایش
              </button>
              {sp.limit !== "all" && res.data.total > res.data.rows.length && (
                <Link href={href(cur, { limit: "all" })} className="underline">
                  نمایش همهٔ {faNumber(res.data.total)} نماد
                </Link>
              )}
            </form>
            <Table rows={res.data.rows} />
          </section>
        </>
      )}
    </main>
  );
}

function Table({ rows }: { rows: ScreenerRow[] }) {
  const heads = [
    "نماد",
    "تصمیم",
    "امتیاز",
    "رتبه",
    "پایانی",
    "تغییر",
    "ارزش معاملات",
    "نسبت حجم",
    "سرانهٔ خرید",
    "سرانهٔ فروش",
    "قدرت خریدار",
    "خالص ورود حقیقی",
    "RSI",
  ];
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface p-2">
      <table className="w-full min-w-[64rem] text-sm" data-testid="screener-table">
        <caption className="sr-only">همهٔ نمادها</caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            {heads.map((h) => (
              <th key={h} scope="col" className="px-2 py-1.5 text-start font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.instrument.id} className="border-b border-line last:border-0">
              <td className="px-2 py-1.5">
                <Link
                  href={`/instruments/${r.instrument.id}`}
                  className="font-semibold hover:text-accent"
                  title={r.instrument.name ?? undefined}
                >
                  {r.instrument.symbol}
                </Link>
              </td>
              <td className="px-2 py-1.5">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-bold ${BADGE[r.verdict]}`}
                  data-verdict={r.verdict}
                >
                  {r.verdict_label}
                </span>
              </td>
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-1.5">
                  <Gauge value={r.gauge} size="sm" label="امتیاز ترکیبی مدل" />
                  <span className="text-xs">{r.gauge == null ? "—" : faNumber(r.gauge, 0)}</span>
                </div>
              </td>
              <td className="px-2 py-1.5">{r.rank == null ? "—" : faNumber(r.rank)}</td>
              <td className="px-2 py-1.5">{r.close == null ? "—" : faNumber(r.close)}</td>
              <td className={`px-2 py-1.5 ${tone(r.change_pct)}`}>
                {r.change_pct == null ? "—" : faPercent(r.change_pct, 2, true)}
              </td>
              <td className="px-2 py-1.5">{toman(r.value)}</td>
              <td className="px-2 py-1.5">
                {r.volume_ratio_30 == null ? "—" : faNumber(r.volume_ratio_30, 2)}
              </td>
              <td className="px-2 py-1.5">{toman(r.per_capita_buy)}</td>
              <td className="px-2 py-1.5">{toman(r.per_capita_sell)}</td>
              <td
                className={`px-2 py-1.5 ${r.power == null ? "" : r.power >= 1 ? "text-up" : "text-down"}`}
              >
                {r.power == null ? "—" : faNumber(r.power, 2)}
              </td>
              <td className={`px-2 py-1.5 ${tone(r.net_real_value)}`}>{toman(r.net_real_value)}</td>
              <td className="px-2 py-1.5">{r.rsi_14 == null ? "—" : faNumber(r.rsi_14, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
