import Link from "next/link";
import type { InstrumentBook } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

/** Where the book leans, in words, from the day's percentile among the stocks with a stored book. */
export function lean(p: number | null | undefined): { text: string; cls: string } {
  if (p == null) return { text: "نامشخص", cls: "text-muted" };
  if (p >= 0.8) return { text: "بیشتر از اغلب نمادها به سمت خریدار", cls: "text-up" };
  if (p <= 0.2) return { text: "بیشتر از اغلب نمادها به سمت فروشنده", cls: "text-down" };
  return { text: "حدود میانهٔ نمادها", cls: "text-ink" };
}

/** A 0..1 position on a bar, 0.5 marked. */
function Position({ p }: { p: number | null | undefined }) {
  if (p == null) return <span className="text-muted">—</span>;
  const tone = p >= 0.8 ? "bg-up" : p <= 0.2 ? "bg-down" : "bg-accent";
  return (
    <div className="flex items-center gap-2">
      <span className="relative h-2 w-28 shrink-0 rounded bg-surface-2" aria-hidden>
        <span
          className={`absolute inset-y-0 start-0 rounded ${tone}`}
          style={{ width: `${100 * p}%` }}
        />
        <span className="absolute inset-y-0 start-1/2 w-px bg-ink/30" />
      </span>
      <span className="text-xs">{faNumber(Math.round(100 * p))}٪</span>
    </div>
  );
}

/** The symbol's order book of the last days (bids vs. offers over five levels, and how long it sat
 *  in a buy or sell queue) and where its book stood among the 100 most traded stocks. Shown only for
 *  the symbols with a stored book. A reading of the past, not a recommendation. */
export function BookCard({ b }: { b: InstrumentBook }) {
  if (!b.available || !b.as_of) return null;
  const l = lean(b.score_percentile);
  const days = b.days.slice(0, 10);
  return (
    <section className="card space-y-3" data-testid="book-card">
      <div>
        <h2 className="font-bold">تابلو و صف: خریدارها یا فروشنده‌ها پررنگ‌ترند؟</h2>
        <p className="text-xs text-muted">
          تا {jalali(b.as_of)}، در مقایسه با {faNumber(b.universe_size ?? 0)} نمادِ پرمعامله‌ای که
          تابلویشان همان روز ذخیره شده. این یک خوانش از تاریخ است، نه پیش‌بینی و نه توصیه.
        </p>
      </div>

      <p className="text-sm" data-testid="book-lean">
        تابلوی این نماد در آخرین روز <b className={l.cls}>{l.text}</b> بود (میانگین جایگاه پنج
        ویژگی:{" "}
        <b>
          {b.score_percentile == null ? "—" : `${faNumber(Math.round(100 * b.score_percentile))}٪`}
        </b>
        ؛ ۵۰٪ یعنی میانه).
      </p>

      <div className="overflow-x-auto">
        <table className="tbl min-w-[28rem]" data-testid="book-ranks">
          <thead>
            <tr>
              <th>ویژگی</th>
              <th>مقدار</th>
              <th>جایگاه بین نمادها</th>
            </tr>
          </thead>
          <tbody>
            {b.ranks.map((r) => (
              <tr key={r.key}>
                <td>
                  <Link href="/glossary/book_imbalance">{r.label}</Link>
                </td>
                <td>
                  <Num
                    value={r.value}
                    term="book_imbalance"
                    digits={r.key === "last_close_gap" ? 3 : 2}
                    signed
                  />
                </td>
                <td>
                  <Position p={r.percentile} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto">
        <table className="tbl min-w-[30rem]" data-testid="book-days">
          <caption className="pb-1 text-start text-xs text-muted">
            ۱۰ روز اخیر (مثبت = خریدارها پررنگ‌ترند)
          </caption>
          <thead>
            <tr>
              <th>روز</th>
              <th>عدم‌تعادل میانگین</th>
              <th>عدم‌تعادل پایان</th>
              <th>زمان در صف خرید</th>
              <th>زمان در صف فروش</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date}>
                <td>{jalali(d.date, "short")}</td>
                <td>
                  <Num value={d.tw_imbalance} term="book_imbalance" digits={2} signed />
                </td>
                <td>
                  <Num value={d.close_imbalance} term="book_imbalance" digits={2} signed />
                </td>
                <td>{d.frac_buy_queue == null ? "—" : faPercent(d.frac_buy_queue, 0)}</td>
                <td>{d.frac_sell_queue == null ? "—" : faPercent(d.frac_sell_queue, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="well text-sm">
        <summary className="cursor-pointer font-semibold">
          این عددها چه می‌گویند و چقدر معتبرند؟
        </summary>
        <div className="mt-2 space-y-2 leading-7">
          <p>
            <b>عدم‌تعادل تابلو</b> یعنی (حجم صف خرید − حجم صف فروش) ÷ مجموع، روی پنج سطح برتر تابلو.
            «میانگین» یعنی در کل جلسهٔ پیوسته (۹:۰۰ تا ۱۲:۳۰) با وزن مدت ماندن هر حالت؛ «پایان» فقط
            تابلوی لحظهٔ بسته‌شدن بازار است. «زمان در صف» سهمی از جلسه است که یک سمت تابلو کاملاً
            خالی بوده.
          </p>
          <p>
            در آزمون روی ۲۵۵ روز و ۱۰۰ نمادِ پرمعامله، همین پنج ویژگی توان رتبه‌بندی بازدهٔ{" "}
            <b>۱ تا ۵ روز بعد</b> را در هر دو نیمهٔ بازه بالا بردند. برای ۲۰ روز و بیشتر چیز پایداری
            پیدا نشد؛ پس این کارت برای افق بلندمدت دلیل نیست و در امتیاز اصلی مدل نیامده است.
          </p>
          <p>
            محدودیت‌ها: سفارش بدون هزینه ثبت و لغو می‌شود و تابلو ممکن است فریبنده باشد؛ بازهٔ آزمون
            کوتاه و تقریباً یک‌سره صعودی بود؛ و برتری پس از کارمزد و صف در بخش «تابلو و صف» صفحهٔ{" "}
            <Link href="/model#book" className="underline">
              اعتبار مدل
            </Link>{" "}
            توضیح داده شده است. ما مشاور سرمایه‌گذاری دارای مجوز نیستیم.
          </p>
        </div>
      </details>
    </section>
  );
}
