import type { RegimePaper } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

const STATE: Record<string, string> = { falling: "نزولی", flat: "خنثی", rising: "صعودی" };
const ACTION: Record<string, string> = {
  dust: "خرید ۱۰ سهمی که بیشترین فاصله را از سقف خود دارند",
  cash: "بیرون از سهم، با سود اوراق یک‌ساله",
  trend: "خرید ۱۰ سهم با بیشترین بازدهٔ ۱۲۰ روزه که نزدیک سقف ۶۰ روزهٔ خود هستند",
};
const KIND: Record<string, string> = {
  enter: "ورود",
  exit: "خروج",
  switch: "جابجایی",
  wait: "صبر",
};

function mt(toman: number): string {
  return `${faNumber(toman / 1e6, 1)} میلیون`;
}

/** The market-state plan run forward on paper: today's state, the action, the log, the account. */
export function RegimePlan({ r }: { r: RegimePaper }) {
  const [lo, hi] = r.edges;
  const last = r.path.at(-1);
  const first = r.capital ?? 0;
  const rows: [string, number | undefined][] = [
    ["برنامه", last?.plan],
    ["داشتن کل ۱۰۰ سهم", last?.basket],
    ["نقد با سود اوراق", last?.cash],
  ];
  return (
    <section className="card space-y-3" data-testid="regime-plan">
      <h2 className="text-lg font-bold">وضع بازار و برنامهٔ هر وضع (آزمون کاغذی)</h2>
      <p className="text-sm leading-7">
        <b>فراخی بازار</b> یعنی چه سهمی از ۱۰۰ سهم پرمعامله بالای میانگین ۶۰ روزهٔ خود هستند. در
        پایانی {jalali(r.as_of)} این عدد {faPercent(r.breadth ?? 0, 0)} بود. اگر به{" "}
        {faPercent(lo, 0)} یا کمتر برسد بازار نزولی است، بالای {faPercent(hi, 0)} صعودی، و بین این
        دو خنثی. وضع تازه فقط وقتی پذیرفته می‌شود که {faNumber(r.confirm_days ?? 0)} روز کاری پشت سر
        هم دیده شود.
      </p>
      <p className="text-sm leading-7" data-testid="regime-state">
        خوانش آخرین پایانی: <b>{STATE[r.raw_state ?? ""]}</b>، {faNumber(r.run_days ?? 0)} روز پشت
        سر هم. وضعی که برنامه بر اساس آن عمل می‌کند: <b>{STATE[r.state ?? ""]}</b>.
      </p>
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr className="text-right">
              <th>وضع بازار</th>
              <th>کار برنامه</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(STATE)
              .reverse()
              .map((s) => (
                <tr
                  key={s}
                  className={`border-t border-line ${s === r.state ? "font-bold" : ""}`}
                  data-testid={`regime-row-${s}`}
                >
                  <td className="py-1.5">
                    {STATE[s]}
                    {s === r.state && " (اکنون)"}
                  </td>
                  <td>{ACTION[r.plan[s] ?? ""]}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm leading-7" data-testid="regime-now">
        {r.pending ? (
          <>
            تصمیم پایانی {jalali(r.pending.date)}: <b>{KIND[r.pending.kind]}</b>
            {r.pending.names?.length ? ` با ${r.pending.names.join("، ")}` : ""}؛ در پایانی روز کاری
            بعد اجرا می‌شود.{" "}
          </>
        ) : null}
        {r.holding.length > 0
          ? `در دست: ${r.holding.join("، ")}. نوبت بعدی نوسازی نام‌ها: ${faNumber(r.days_to_renew ?? 0)} روز کاری دیگر، یا زودتر اگر وضع بازار عوض شود.`
          : "اکنون سهمی در دست نیست؛ پول با سود اوراق می‌ماند."}
      </p>
      <div>
        <h3 className="text-sm font-bold">
          حساب کاغذی از {jalali(r.start)} با {mt(first)} تومان
        </h3>
        <div className="grid grid-cols-1 gap-2 pt-1 sm:grid-cols-3" data-testid="regime-account">
          {rows.map(([label, v]) => (
            <div key={label} className="tile">
              <div className="text-xs text-muted">{label}</div>
              <div className="mt-1 font-bold">
                {v == null ? "—" : `${mt(v)} تومان`}
                {v != null && first > 0 && (
                  <span className="text-xs font-normal text-muted">
                    {" "}
                    ({faPercent(v / first - 1, 1, true)})
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
        <p className="pt-1 text-xs text-muted">
          با هزینهٔ خرید ۰٫۶۲٪ و فروش ۱٫۱۳٪. ستون «کل ۱۰۰ سهم» سهم‌های صف خرید را هم دارد که در عمل
          خریدنی نبودند، پس کمی خوش‌بینانه است.
        </p>
      </div>
      <div>
        <h3 className="text-sm font-bold">دفتر تصمیم‌ها</h3>
        <div className="overflow-x-auto">
          <table className="tbl" data-testid="regime-log">
            <thead>
              <tr className="text-right">
                <th>پایانی روز</th>
                <th>وضع</th>
                <th>فراخی</th>
                <th>تصمیم</th>
                <th>خرید شد</th>
              </tr>
            </thead>
            <tbody>
              {[...r.log].reverse().map((e) => (
                <tr key={e.date} className="border-t border-line">
                  <td className="py-1.5">{jalali(e.date)}</td>
                  <td>{STATE[e.state]}</td>
                  <td>{faPercent(e.breadth, 0)}</td>
                  <td>{KIND[e.kind]}</td>
                  <td className="text-xs">
                    {e.filled_on
                      ? e.names?.length
                        ? e.names.join("، ")
                        : "نقد"
                      : "در انتظار پایانی روز بعد"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-xs leading-6 text-muted">
        برنامه از دادهٔ ۱۳۹۷ تا ۱۴۰۳ انتخاب شد. در ۱۴۰۴ تا آبان ۱۴۰۵ ماهانه حدود ۵٫۷٪ داد، نزدیک
        داشتن کل سبد (۵٫۵٪)، ولی ماه‌های منفی کمتری داشت (۱۱٪ از ماه‌ها در برابر ۳۲٪) و بیشترین افتش
        کمتر بود (۲۰٪ در برابر ۲۵٪). آن دوره پیش از ساختن این آزمون دیده شده بود؛ آزمون واقعی فقط
        روزهای پس از {jalali(r.start)} است. بیشتر داده‌ها از یک دورهٔ صعودی پرتورم است. آزمون کاغذی
        است و هیچ سفارشی ثبت نمی‌شود. رتبه‌بندی مدل، توصیه نیست.
      </p>
    </section>
  );
}
