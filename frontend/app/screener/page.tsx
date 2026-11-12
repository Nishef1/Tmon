import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Recommendations, type Screener, type ScreenerRow } from "@/lib/api";
import { jalali } from "@/lib/format";
import { featureInfo } from "@/lib/glossary";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { WhyNoRecommendation } from "@/components/WhyNoRecommendation";

export const metadata: Metadata = { title: "همهٔ نمادها" };
export const dynamic = "force-dynamic";

const TIMEFRAMES = [
  ["D1", "روزانه"],
  ["W1", "هفتگی"],
  ["M1", "ماهانه"],
] as const;

const SORTS = [
  ["ev", "سود مورد انتظار مدل"],
  ["p_win", "احتمال موفقیت"],
  ["value", "ارزش معاملات"],
  ["change_pct", "تغییر قیمت"],
  ["ind_buy_power", "قدرت خریدار حقیقی"],
  ["rsi_14", "RSI"],
] as const;

const TOP = 10; // rows explained in the "best by the model" section

type SP = { timeframe?: string; sort?: string; q?: string; limit?: string };

function href(sp: SP, over: Partial<SP>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...sp, ...over })) if (v) p.set(k, v);
  return `/screener?${p.toString()}`;
}

export default async function ScreenerPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tf = TIMEFRAMES.find(([t]) => t === sp.timeframe)?.[0] ?? "D1";
  const sort = SORTS.find(([s]) => s === sp.sort)?.[0] ?? "ev";
  const limit = sp.limit === "all" ? 3000 : 200;
  const q = (sp.q ?? "").slice(0, 64);
  const [res, best, rec] = await Promise.all([
    apiGet<Screener>("/screener", { timeframe: tf, sort, q: q || undefined, limit }),
    apiGet<Screener>("/screener", { timeframe: tf, sort: "ev", limit: TOP }),
    apiGet<Recommendations>("/recommendations", { timeframe: tf }),
  ]);
  const cur: SP = { timeframe: tf, sort, q, limit: sp.limit };

  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">همهٔ نمادها</h1>
        <p className="mt-1 text-sm text-muted">
          همهٔ نمادهایی که در آخرین روز ذخیره‌شده معامله شده‌اند، با دادهٔ تابلو، چند شاخص و خروجی
          خام مدل. این فهرست توصیه نیست: فقط نمادهای صفحهٔ «توصیه‌های امروز» از همهٔ آستانه‌ها
          گذشته‌اند.
        </p>
      </div>
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="افق">
        {TIMEFRAMES.map(([t, label]) => (
          <Link
            key={t}
            href={href(cur, { timeframe: t })}
            aria-current={t === tf ? "page" : undefined}
            className="rounded-lg border border-line px-3 py-1 aria-[current=page]:bg-surface aria-[current=page]:font-bold"
          >
            {label}
          </Link>
        ))}
      </nav>
      <Disclaimer />
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : (
        <>
          <ModelStatus data={res.data} />
          {rec.ok && rec.data.no_recommendation && (
            <section
              className="rounded-2xl border border-line bg-surface p-5"
              data-testid="screener-why"
            >
              <h2 className="text-lg font-bold">چرا هیچ‌کدام از این نمادها توصیه نشده‌اند؟</h2>
              <WhyNoRecommendation diagnosis={rec.data.diagnosis} gate={rec.data.gate} />
            </section>
          )}
          {best.ok && <Best rows={best.data.rows} hasScores={best.data.scores_date != null} />}
          <section className="space-y-3">
            <h2 className="text-lg font-bold">
              فهرست کامل ({<Num value={res.data.total} kind="count" term="symbol" />} نماد)
            </h2>
            <form className="flex flex-wrap items-end gap-2 text-sm" action="/screener">
              <input type="hidden" name="timeframe" value={tf} />
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
              <button className="rounded-lg border border-line px-3 py-1.5 font-semibold">
                نمایش
              </button>
              {sp.limit !== "all" && res.data.total > res.data.rows.length && (
                <Link href={href(cur, { limit: "all" })} className="underline">
                  نمایش همهٔ {res.data.total} نماد
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

function ModelStatus({ data }: { data: Screener }) {
  return (
    <section className="space-y-1 rounded-2xl border border-line bg-surface p-4 text-sm">
      <p>
        قیمت‌ها: {data.prices_date ? jalali(data.prices_date) : "—"} · خروجی مدل:{" "}
        {data.scores_date ? jalali(data.scores_date) : "هنوز ذخیره نشده"}
        {data.model_version && <span className="text-muted"> ({data.model_version})</span>}
      </p>
      {data.tier_a_allowed === false && (
        <div className="text-amber-700 dark:text-amber-400">
          <p className="font-semibold">
            مدل در آزمون خارج از نمونه از روش پایه بهتر نبوده است؛ به احتمال‌های زیر با احتیاط نگاه
            کنید.
          </p>
          {data.gate_reasons.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-xs">
              {data.gate_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function Best({ rows, hasScores }: { rows: ScreenerRow[]; hasScores: boolean }) {
  if (!hasScores) {
    return (
      <p className="text-sm text-muted" data-testid="no-scores">
        خروجی مدل برای همهٔ نمادها هنوز ذخیره نشده است؛ پس از چرخهٔ روزانهٔ بعدی نمایش داده می‌شود.
      </p>
    );
  }
  const ranked = rows.filter((r) => r.ev != null);
  return (
    <section className="space-y-3" data-testid="best">
      <h2 className="text-lg font-bold">بالاترین سود مورد انتظار مدل (پیش از آستانه‌ها)</h2>
      <p className="text-sm text-muted">
        «چرا» در هر کارت همان عواملی است که بیشترین اثر را بر احتمال مدل داشته‌اند. اگر سود مورد
        انتظار منفی یا احتمال زیر آستانه است، مدل خرید را توجیه‌پذیر نمی‌داند.
      </p>
      <ol className="grid gap-3 md:grid-cols-2">
        {ranked.map((r, i) => (
          <li key={r.instrument.id} className="rounded-2xl border border-line bg-surface p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Link
                href={`/instruments/${r.instrument.id}`}
                className="text-lg font-bold hover:text-accent"
              >
                {i + 1}. {r.instrument.symbol}
              </Link>
              <span className="text-xs text-muted">{r.instrument.name}</span>
            </div>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
              <div>
                <dt className="text-xs text-muted">سود مورد انتظار</dt>
                <dd>
                  <Num value={r.ev} kind="percent" term="ev" digits={2} signed />
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">احتمال / آستانه</dt>
                <dd>
                  <Num value={r.p_win} kind="percent" term="p_win" digits={1} /> /{" "}
                  <Num value={r.p_min} kind="percent" term="p_win" digits={1} />
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">پایانی / تغییر</dt>
                <dd>
                  <Num value={r.close} kind="price" term="closing_price" />{" "}
                  <Num value={r.change_pct} kind="percent" term="change_pct" digits={2} signed />
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-xs">
              {r.signal
                ? "از همهٔ آستانه‌ها گذشته است."
                : (r.ev ?? 0) <= 0
                  ? "سود مورد انتظار پس از هزینه منفی است: خرید توجیه ندارد."
                  : (r.p_win ?? 0) < (r.p_min ?? 1)
                    ? "احتمال موفقیت زیر آستانهٔ لازم است."
                    : "سود مورد انتظار کمتر از حداقل لازم است."}
            </p>
            {r.reasons && r.reasons.length > 0 && (
              <ul className="mt-2 space-y-1 border-t border-line pt-2 text-sm">
                {r.reasons.map((x) => {
                  const info = featureInfo(x.feature);
                  return (
                    <li key={x.feature} className="flex flex-wrap justify-between gap-2">
                      <span>
                        <Link href={`/glossary/${info.term}`} className="hover:text-accent">
                          {info.label}
                        </Link>{" "}
                        = <Num term="feature_value" value={x.value} digits={2} />
                      </span>
                      <span className="text-muted">
                        {x.contribution >= 0 ? "افزایش" : "کاهش"} امتیاز{" "}
                        <Num term="shap" value={x.contribution} digits={2} signed />
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function Table({ rows }: { rows: ScreenerRow[] }) {
  const heads = [
    "نماد",
    "پایانی",
    "تغییر",
    "ارزش معاملات",
    "RSI",
    "حجم نسبی",
    "قدرت خریدار حقیقی",
    "ورود پول حقیقی",
    "احتمال مدل",
    "سود مورد انتظار",
  ];
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface p-2">
      <table className="w-full min-w-[60rem] text-sm" data-testid="screener-table">
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
                <Num value={r.close} kind="price" term="closing_price" />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.change_pct} kind="percent" term="change_pct" digits={2} signed />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.value} kind="price" term="trade_value" />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.rsi_14} kind="plain" term="rsi" digits={0} />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.rel_volume} kind="plain" term="rel_volume" digits={2} />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.ind_buy_power} kind="plain" term="buy_power" digits={2} />
              </td>
              <td className="px-2 py-1.5">
                <Num
                  value={r.ind_net_flow_ratio}
                  kind="percent"
                  term="net_flow"
                  digits={1}
                  signed
                />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.p_win} kind="percent" term="p_win" digits={1} />
              </td>
              <td className="px-2 py-1.5">
                <Num value={r.ev} kind="percent" term="ev" digits={2} signed />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
