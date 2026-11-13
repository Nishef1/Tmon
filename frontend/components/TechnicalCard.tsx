import Link from "next/link";
import type { InstrumentDashboard } from "@/lib/api";
import { faDigits, faNumber, faPercent, faPrice, jalali } from "@/lib/format";

type T = NonNullable<InstrumentDashboard["technical"]>;
type V = T["values"][number];
type F = T["fired"][number];

const TONE: Record<V["tone"], string> = { buy: "text-up", sell: "text-down", neutral: "" };

const LABEL_FA: Record<F["label"], string> = {
  works: "در گذشته کار کرده",
  direction_only: "فقط جهت را درست گفته",
  reverse_small: "کمی برعکس عمل کرده",
  backfires: "برعکس عمل کرده",
  no_edge: "برتری نداشته",
  too_few: "نمونهٔ کم",
};

function value(v: V): string {
  if (v.value == null) return "—";
  if (v.unit === "pct") return faPercent(v.value, 1);
  if (v.unit === "price") return faPrice(v.value);
  if (v.unit === "x") return `${faNumber(v.value, 2)}×`;
  return faNumber(v.value, 1);
}

function Risk({ r }: { r: NonNullable<T["risk"]> }) {
  const rows: [string, string, string][] = [
    ["بازده این دوره", r.ret_1y == null ? "—" : faPercent(r.ret_1y, 0, true), "realized_return"],
    ["نوسان سالانه", r.vol_ann == null ? "—" : faPercent(r.vol_ann, 0), "volatility"],
    ["VaR روزانهٔ ۹۵٪", r.var95 == null ? "—" : faPercent(r.var95, 1), "var"],
    ["بیشترین افت", r.max_dd == null ? "—" : faPercent(r.max_dd, 0), "max_drawdown"],
    ["شارپ", r.sharpe == null ? "—" : faNumber(r.sharpe, 2), "sharpe"],
    ["سورتینو", r.sortino == null ? "—" : faNumber(r.sortino, 2), "sortino"],
    ["بتا به شاخص کل", r.beta_index == null ? "—" : faNumber(r.beta_index, 2), "beta"],
  ];
  return (
    <div className="mt-4">
      <h3 className="mb-1 text-sm font-bold">ریسک</h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4" data-testid="ta-risk">
        {rows.map(([k, val, term]) => (
          <div key={k} className="flex justify-between gap-2 border-b border-line py-1">
            <dt>
              <Link href={`/glossary/${term}`} className="text-muted hover:text-accent">
                {k}
              </Link>
            </dt>
            <dd className="font-bold">{val}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-xs text-muted">
        روی {faNumber(r.days)} روز معاملاتی از {jalali(r.from_date, "short")} با قیمت تعدیل‌شده.
        {r.rf_annual != null &&
          ` شارپ و سورتینو با نرخ بدون ریسک ${faPercent(r.rf_annual, 1)} (بازده اوراق خزانه) حساب شده‌اند.`}{" "}
        VaR یعنی در ۹۵ از ۱۰۰ روز ضرر یک روز از این بیشتر نبوده است.
      </p>
    </div>
  );
}

/** The glossary's chart terms for this symbol: today's readings, what fired lately and how each
 *  reading did across the whole TSETMC history. */
export function TechnicalCard({ t }: { t: T }) {
  return (
    <section className="card" data-testid="technical">
      <h2 className="mb-1 font-bold">تابلوی تکنیکال: اندیکاتورها چه می‌گویند و در گذشته چه شد؟</h2>
      <ul className="list-disc space-y-1.5 ps-5">
        {t.lines.map((l) => (
          <li key={l}>{faDigits(l)}</li>
        ))}
      </ul>
      {t.fired.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm" data-testid="ta-fired">
            <thead className="text-muted">
              <tr>
                <th className="py-1 text-start font-normal">
                  نشانه‌های {faNumber(t.recent_days)} روز معاملاتی اخیر
                </th>
                <th className="py-1 text-start font-normal">در کل تاریخچهٔ بورس تهران</th>
              </tr>
            </thead>
            <tbody>
              {t.fired.map((f) => (
                <tr key={f.key} className="border-t border-line align-top">
                  <td className="py-1.5">
                    <span className={f.side === "buy" ? "text-up" : "text-down"}>
                      {f.side === "buy" ? "خرید" : "فروش"}
                    </span>{" "}
                    <Link href={`/glossary/${f.term}`} className="underline hover:text-accent">
                      {f.title}
                    </Link>
                    <div className="text-xs text-muted">
                      {jalali(f.date, "short")} ·{" "}
                      {f.ago === 0 ? "آخرین روز" : `${faNumber(f.ago)} روز پیش`}
                    </div>
                  </td>
                  <td className="py-1.5">
                    <span className="chip">{LABEL_FA[f.label]}</span>{" "}
                    <span className="text-muted">{faDigits(f.verdict)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm" data-testid="ta-values">
          <thead className="text-muted">
            <tr>
              <th className="py-1 text-start font-normal">
                اندیکاتور ({jalali(t.as_of, "short")})
              </th>
              <th className="py-1 font-normal">مقدار</th>
              <th className="py-1 text-start font-normal">خوانش کتابی</th>
            </tr>
          </thead>
          <tbody>
            {t.values.map((v) => (
              <tr key={v.key} className="border-t border-line">
                <td className="py-1.5">
                  <Link href={`/glossary/${v.term}`} className="hover:text-accent">
                    {v.name}
                  </Link>
                </td>
                <td className="py-1.5 text-center" dir="ltr">
                  {value(v)}
                </td>
                <td className={`py-1.5 ${TONE[v.tone]}`}>{faDigits(v.reading)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.risk && <Risk r={t.risk} />}
      <p className="mt-3 text-xs text-muted">
        «خوانش کتابی» همان چیزی است که کتاب‌های تحلیل تکنیکال می‌گویند، نه نتیجهٔ آزمون ما. آزمون هر
        خوانش روی همهٔ نمادهای بورس تهران، ۱ تا ۶۰ روز بعد، پس از کارمزد رفت‌وبرگشت{" "}
        {faPercent(t.round_trip_cost, 1)} و بدون روزهای صف در صفحهٔ هر واژه در واژه‌نامه آمده است.
        این‌ها توصیه نیستند.
      </p>
    </section>
  );
}
