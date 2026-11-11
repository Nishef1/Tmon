import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Compare, type Funds } from "@/lib/api";
import { jalali } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";

export const metadata: Metadata = { title: "مقایسه با تورم" };
export const dynamic = "force-dynamic";

type Search = { months?: string; source?: string };
const MONTHS = [1, 3, 12] as const;

export default async function ComparePage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const months = MONTHS.find((m) => String(m) === sp.months) ?? 12;
  const source = sp.source === "cbi" ? "cbi" : "sci";
  const [cmp, funds] = await Promise.all([
    apiGet<Compare>("/compare", { months, inflation_source: source }),
    apiGet<Funds>("/funds"),
  ]);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">مقایسه با تورم</h1>
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="بازهٔ زمانی و منبع تورم">
        {MONTHS.map((m) => (
          <Link
            key={m}
            href={`/compare?months=${m}&source=${source}`}
            aria-current={m === months ? "page" : undefined}
            className="rounded-lg border border-line px-3 py-1 aria-[current=page]:bg-surface aria-[current=page]:font-bold"
          >
            {m} ماه
          </Link>
        ))}
        {(["sci", "cbi"] as const).map((s) => (
          <Link
            key={s}
            href={`/compare?months=${months}&source=${s}`}
            aria-current={s === source ? "page" : undefined}
            className="rounded-lg border border-line px-3 py-1 aria-[current=page]:bg-surface aria-[current=page]:font-bold"
          >
            {s === "sci" ? "مرکز آمار" : "بانک مرکزی"}
          </Link>
        ))}
      </nav>

      {!cmp.ok ? (
        <ErrorState message={cmp.error} />
      ) : cmp.data.as_of == null ? (
        <p className="text-sm text-muted">هنوز دادهٔ بازار آزاد ثبت نشده است.</p>
      ) : (
        <section className="space-y-3 rounded-2xl border border-line bg-surface p-4">
          <p className="text-sm">
            تا {jalali(cmp.data.as_of)} — تورم دوره:{" "}
            {cmp.data.inflation ? (
              <Num value={cmp.data.inflation.value} kind="percent" term="inflation" digits={1} />
            ) : (
              <span className="text-muted">برای این منبع و بازه منتشر یا وارد نشده است</span>
            )}
            {cmp.data.annualised_monthly != null && (
              <>
                {" "}
                · تورم ماه آخر سالانه‌شده:{" "}
                <Num
                  value={cmp.data.annualised_monthly}
                  kind="percent"
                  term="inflation_threshold"
                  digits={1}
                />
              </>
            )}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">بازده اسمی و واقعی دارایی‌ها</caption>
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    دارایی
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    از
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    بازده اسمی
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    بازده واقعی
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    از تورم جلو؟
                  </th>
                </tr>
              </thead>
              <tbody>
                {cmp.data.rows.map((r) => (
                  <tr key={r.series} className="border-b border-line last:border-0">
                    <td className="px-2 py-1.5">{r.label}</td>
                    <td className="px-2 py-1.5">{r.start_date ? jalali(r.start_date) : "—"}</td>
                    <td className="px-2 py-1.5">
                      {r.nominal_return != null ? (
                        <Num
                          value={r.nominal_return}
                          kind="percent"
                          term="nominal_return"
                          digits={1}
                          signed
                        />
                      ) : (
                        <span className="text-muted">{r.note ?? "—"}</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {r.real_return != null ? (
                        <Num
                          value={r.real_return}
                          kind="percent"
                          term="real_return"
                          digits={1}
                          signed
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {r.beats_inflation == null ? "—" : r.beats_inflation ? "بله" : "خیر"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cmp.data.inflation && (
            <ul className="text-xs text-muted">
              {cmp.data.inflation.releases.map((x) => (
                <li key={`${x.ref_period}`}>
                  ماه {jalali(x.ref_period)}، منتشرشده {jalali(x.release_date)}
                  {x.source_url && (
                    <>
                      {" — "}
                      <a href={x.source_url} className="underline" rel="noreferrer" target="_blank">
                        منبع
                      </a>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="space-y-3 rounded-2xl border border-line bg-surface p-4">
        <h2 className="font-bold">صندوق‌های بورسی: NAV و حباب</h2>
        {!funds.ok ? (
          <ErrorState message={funds.error} />
        ) : funds.data.funds.length === 0 ? (
          <p className="text-sm text-muted">هنوز NAV صندوقی ثبت نشده است.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">ارزش ابطال و حباب صندوق‌ها</caption>
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    نماد
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    NAV ابطال
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    قیمت پایانی
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-medium">
                    حباب
                  </th>
                </tr>
              </thead>
              <tbody>
                {funds.data.funds.map((f) => (
                  <tr key={f.reg_no} className="border-b border-line last:border-0">
                    <td className="px-2 py-1.5">
                      {f.instrument_id ? (
                        <Link href={`/instruments/${f.instrument_id}`} className="underline">
                          {f.symbol ?? f.name}
                        </Link>
                      ) : (
                        f.name
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {f.cancel_nav != null ? (
                        <Num value={f.cancel_nav} kind="price" term="fund_nav" />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {f.price != null ? (
                        <Num value={f.price} kind="price" term="last_price" />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {f.bubble != null && (
                        <Num value={f.bubble} kind="percent" term="etf_bubble" digits={1} signed />
                      )}
                      {f.bubble_note && (
                        <span className="block text-xs text-muted">{f.bubble_note}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Disclaimer />
    </div>
  );
}
