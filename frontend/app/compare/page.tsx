import Link from "next/link";
import type { Metadata } from "next";
import {
  apiGet,
  type Compare,
  type SymbolsValue,
  type Rights,
  type LeveragedFunds,
  type InstrumentDashboard,
  type InstrumentDetail,
} from "@/lib/api";
import { faNumber, jalali } from "@/lib/format";
import { CompareChart } from "@/components/compare/CompareChart";
import { SymbolPicker } from "@/components/compare/SymbolPicker";
import { SymbolsTable, type Picked } from "@/components/compare/SymbolsTable";
import { MAX_SYMBOLS } from "@/components/compare/colors";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { RightsTable, ValueTable } from "@/components/compare/BubbleTables";
import { LeveragedFundsSection } from "@/components/compare/LeveragedFunds";

export const metadata: Metadata = { title: "مقایسه" };
export const dynamic = "force-dynamic";

type Search = { months?: string; source?: string; s?: string };
const MONTHS = [1, 3, 12] as const;

export default async function ComparePage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const months = MONTHS.find((m) => String(m) === sp.months) ?? 12;
  const source = sp.source === "cbi" ? "cbi" : "sci";
  const ids = [...new Set((sp.s ?? "").split(",").filter((x) => /^\d+$/.test(x)))].slice(
    0,
    MAX_SYMBOLS,
  );
  const [cmp, vals, rights, lev, picked] = await Promise.all([
    apiGet<Compare>("/compare", { months, inflation_source: source }),
    apiGet<SymbolsValue>("/compare/symbols", { months, inflation_source: source }),
    apiGet<Rights>("/rights"),
    apiGet<LeveragedFunds>("/funds/leveraged"),
    Promise.all(
      ids.map(async (id): Promise<Picked | null> => {
        const [d, dash] = await Promise.all([
          apiGet<InstrumentDetail>(`/instruments/${id}`),
          apiGet<InstrumentDashboard>(`/instruments/${id}/dashboard`),
        ]);
        return d.ok ? { detail: d.data, dash: dash.ok ? dash.data : null } : null;
      }),
    ),
  ]);
  const chosen = picked.filter((p): p is Picked => p != null);
  const sq = chosen.length ? `&s=${chosen.map((p) => p.detail.instrument.id).join(",")}` : "";
  const lines = chosen.map((p) => ({
    id: p.detail.instrument.id,
    symbol: p.detail.instrument.symbol,
    closes: p.detail.candles.flatMap((c) =>
      c.close == null ? [] : [{ date: c.date, close: c.close }],
    ),
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">مقایسه</h1>
        <p className="lead">
          چند نماد را کنار هم بگذارید: بازده از یک روز مشترک، ریسک، این‌که الان چند کندل سبز یا قرمز
          پشت سر هم دارند و بعد از چنین وضعی در گذشته کندل‌های بعدی چند بار بالاتر رفته‌اند.
          پایین‌تر، دارایی‌های ساده در برابر تورم آمده‌اند و بعد حباب صندوق‌ها و حق‌تقدم‌ها.
        </p>
        <nav aria-label="بخش‌های صفحه" className="mt-3 flex flex-wrap gap-2">
          <a href="#symbols" className="tab tab-pill">
            مقایسهٔ نمادها
          </a>
          <a href="#inflation" className="tab tab-pill">
            دارایی‌ها و تورم
          </a>
          <a href="#funds" className="tab tab-pill">
            حباب و تورم همهٔ نمادها
          </a>
          <a href="#leveraged" className="tab tab-pill">
            صندوق‌های اهرمی
          </a>
          <a href="#rights" className="tab tab-pill">
            حباب حق‌تقدم‌ها
          </a>
        </nav>
      </div>

      <section id="symbols" className="card space-y-4" data-testid="compare-symbols">
        <h2 className="font-bold">مقایسهٔ نمادها</h2>
        <SymbolPicker
          chosen={chosen.map((p) => ({
            id: p.detail.instrument.id,
            symbol: p.detail.instrument.symbol,
          }))}
          keep={`months=${months}&source=${source}`}
        />
        {chosen.length === 0 ? (
          <p className="text-sm text-muted">
            یک تا {faNumber(MAX_SYMBOLS)} نماد اضافه کنید تا بازده، ریسک و شانس کندل‌های بعدی‌شان
            کنار هم دیده شود.
          </p>
        ) : (
          <>
            <CompareChart lines={lines} />
            <SymbolsTable picked={chosen} />
          </>
        )}
      </section>

      <h2 id="inflation" className="text-xl font-extrabold">
        دارایی‌ها در برابر تورم
      </h2>
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="بازهٔ زمانی و منبع تورم">
        {MONTHS.map((m) => (
          <Link
            key={m}
            href={`/compare?months=${m}&source=${source}${sq}#inflation`}
            aria-current={m === months ? "page" : undefined}
            className="tab"
          >
            {faNumber(m)} ماه
          </Link>
        ))}
        {(["sci", "cbi"] as const).map((s) => (
          <Link
            key={s}
            href={`/compare?months=${months}&source=${s}${sq}#inflation`}
            aria-current={s === source ? "page" : undefined}
            className="tab"
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
        <section className="card space-y-3">
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
            <table className="tbl min-w-[32rem]">
              <caption className="sr-only">بازده اسمی و واقعی دارایی‌ها</caption>
              <thead>
                <tr className="border-b border-line">
                  <th scope="col">دارایی</th>
                  <th scope="col">از</th>
                  <th scope="col">بازده اسمی</th>
                  <th scope="col">بازده واقعی</th>
                  <th scope="col">از تورم جلو؟</th>
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

      <section id="funds" className="card space-y-3">
        <h2 className="font-bold">همهٔ نمادها: حباب و بازده در برابر تورم</h2>
        <div className="space-y-1 text-sm text-muted">
          <p>
            سهم‌ها و صندوق‌هایی که در آخرین روز معامله شدند، و حق‌تقدم‌هایی که در ۳۰ روز گذشته
            معامله شدند. ستون «نوع» می‌گوید هر نماد سهم است یا صندوق (و چه صندوقی) یا حق‌تقدم.
          </p>
          <p>
            <b>حباب</b> فقط جایی حساب می‌شود که ارزش روشن باشد: برای صندوق NAV ابطال همان روز، برای
            حق‌تقدم قیمت سهم پایه منهای ۱۰۰۰ ریال. سهم عادی NAV ندارد، پس حباب ندارد. حباب منفی یعنی
            زیر ارزش معامله شده است.
          </p>
          <p>
            <b>جلوتر از تورم</b> یعنی اگر نماد را از {faNumber(months)} ماه پیش نگه داشته بودید،
            پولتان پس از کسر تورم چقدر بیشتر شده است: (۱ + بازده) ÷ (۱ + تورم) − ۱. بازده با قیمت
            تعدیل‌شده است، پس سود نقدی و افزایش سرمایه را هم دارد.
            {vals.ok && vals.data.inflation != null && (
              <>
                {" "}
                تورم این دوره:{" "}
                <Num value={vals.data.inflation} kind="percent" term="inflation" digits={1} />
                {vals.data.inflation_note && <> ({vals.data.inflation_note})</>}.
              </>
            )}
          </p>
          <p>
            ترتیب پیش‌فرض: اول نمادهایی که حباب بی‌یادداشت دارند، از منفی‌ترین؛ بعد بقیه، از بیشترین
            جلوافتادگی از تورم. با کلیک روی سر هر ستون ترتیب عوض می‌شود. این فهرست توصیه نیست.
          </p>
        </div>
        <nav className="flex flex-wrap gap-2 text-sm" aria-label="دورهٔ نگه‌داری">
          {MONTHS.map((m) => (
            <Link
              key={m}
              href={`/compare?months=${m}&source=${source}${sq}#funds`}
              aria-current={m === months ? "page" : undefined}
              className="tab"
            >
              نگه‌داری {faNumber(m)} ماه
            </Link>
          ))}
        </nav>
        {!vals.ok ? (
          <ErrorState message={vals.error} />
        ) : vals.data.rows.length === 0 ? (
          <p className="text-sm text-muted">هنوز قیمتی ثبت نشده است.</p>
        ) : (
          <ValueTable rows={vals.data.rows} months={months} />
        )}
      </section>

      <section id="leveraged" className="card space-y-3">
        <h2 className="font-bold">صندوق‌های اهرمی: ماهی ۱۰ درصد؟</h2>
        {!lev.ok ? <ErrorState message={lev.error} /> : <LeveragedFundsSection data={lev.data} />}
      </section>

      <section id="rights" className="card space-y-3">
        <h2 className="font-bold">حباب حق‌تقدم‌ها</h2>
        <p className="text-sm text-muted">
          سهم عادی NAV ندارد، پس حباب ندارد. در میان نمادهای سهامی فقط حق‌تقدم یک ارزش روشن دارد:
          قیمت پایانی سهم پایه منهای قیمت اسمی ۱۰۰۰ ریال. حباب منفی یعنی با خرید حق‌تقدم و پرداخت
          ۱۰۰۰ ریال، سهم را ارزان‌تر از تابلو می‌گیرید؛ در عوض پول تا ثبت افزایش سرمایه قفل می‌ماند.
          فقط حق‌تقدم‌هایی آمده‌اند که در ۳۰ روز گذشته معامله شده‌اند.
        </p>
        {!rights.ok ? (
          <ErrorState message={rights.error} />
        ) : rights.data.rights.length === 0 ? (
          <p className="text-sm text-muted">در ۳۰ روز گذشته حق‌تقدمی معامله نشده است.</p>
        ) : (
          <RightsTable rights={rights.data.rights} />
        )}
      </section>
    </div>
  );
}
