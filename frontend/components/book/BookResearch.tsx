import Link from "next/link";
import type { BookFeatureRow, BookPoint, OrderbookResearch } from "@/lib/api";
import { faNumber, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

const UNIVERSE = { all: "همهٔ نمادها", liquid100: "۱۰۰ نماد پرنقد" } as const;

/** Rial portfolio sizes of the capacity test, as toman, the unit people think in. */
function tomanLabel(rial: number): string {
  const toman = rial / 10;
  if (toman >= 1e9) return `${faNumber(toman / 1e9)} میلیارد تومان`;
  return `${faNumber(toman / 1e6)} میلیون تومان`;
}

function Excess({ p }: { p: BookPoint }) {
  return (
    <span className="whitespace-nowrap">
      <Num value={p.excess} kind="percent" digits={0} signed term="net_excess" />{" "}
      <span className="text-xs text-muted">
        (t=
        <Num value={p.t} digits={1} term="t_stat" />)
      </span>
    </span>
  );
}

function Delta({ v, t }: { v: number; t: number }) {
  return (
    <>
      <Num value={v} digits={4} signed term="ic" />{" "}
      <span className="text-xs text-muted">
        (t=
        <Num value={t} digits={1} term="t_stat" />)
      </span>
    </>
  );
}

const STATUS: Record<BookFeatureRow["status"], { label: string; cls: string }> = {
  kept: { label: "نگه داشته شد", cls: "border-up text-up" },
  redundant: { label: "هم‌پوشان", cls: "border-line text-muted" },
  dropped: { label: "حذف شد", cls: "border-down text-down" },
};

function StatusChip({ s }: { s: BookFeatureRow["status"] }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-bold ${STATUS[s].cls}`}
      data-status={s}
    >
      {STATUS[s].label}
    </span>
  );
}

/** The order-book and queue study: what a realistic portfolio keeps, which book features add to
 *  the score and which do not, with the corrections to the earlier numbers stated up front. */
export function BookResearch({ d }: { d: OrderbookResearch }) {
  const a = d.assumptions;
  const first = d.ladder.find((r) => r.universe === "all" && r.review === 5);
  const liquid = d.ladder.find((r) => r.universe === "liquid100" && r.review === 5);
  const sel = d.selection;
  const kept = d.features.filter((f) => f.status === "kept");
  return (
    <section id="book" className="scroll-mt-20 space-y-6" data-testid="book-research">
      <div className="space-y-2">
        <h2 className="text-xl font-extrabold">تابلو و صف: سبد واقع‌گرایانه و ویژگی‌های تابلو</h2>
        <p className="text-sm leading-7">
          دو پرسش: (۱) اگر صف خرید و فروش، سقف حجم قابل‌معامله و کارمزد را جدی بگیریم، قاعدهٔ مدل در
          گذشته واقعاً چقدر می‌ماند؟ (۲) آیا تابلوی سفارش‌ها (پنج سطح خرید و فروش) و صف به امتیاز
          چیزی اضافه می‌کند؟ تاریخچهٔ تابلو برای {faNumber(d.book_days ?? 0)} روز معاملاتی و ۱۰۰
          نمادِ پرمعامله ({faNumber(d.book_rows ?? 0)} روز-نماد) از سرویس بورس گرفته و به یک ردیف
          برای هر نماد-روز خلاصه شده است. همهٔ اعداد زیر نتیجهٔ آزمون روی گذشته‌اند، نه پیش‌بینی و
          نه توصیه؛ ما مشاور سرمایه‌گذاری دارای مجوز نیستیم.
        </p>
      </div>

      <section className="alert-warn alert-lg space-y-2 text-ink" data-testid="book-retraction">
        <h3 className="text-lg font-bold">اصلاح: عدد «۵۵٪ در سال» پس گرفته شد</h3>
        <p className="text-sm leading-7">
          گزارش قبلی بدون در نظر گرفتن صف خرید و فروش و سقف حجم، حدود ۵۵٪ در سال نشان می‌داد. این
          عدد خوش‌بینانه بود: سهمی که در صف خرید بسته می‌شود برای خریدار تازه‌وارد قابل‌خرید نبود، و
          سفارش بزرگ در یک سهم کم‌معامله نمی‌گنجد. با همان قاعده، ولی با صف و کارمزد و سقف ۱۰٪ ارزش
          معاملهٔ روز، برای بازبینی ۵ روزه روی همهٔ نمادها{" "}
          {first && (
            <b>
              حدود <Num value={first.locks.excess} kind="percent" digits={0} term="net_excess" /> در
              سال (t=
              <Num value={first.locks.t} digits={1} term="t_stat" />)
            </b>
          )}{" "}
          می‌ماند. روی ۱۰۰ نماد پرنقد کمتر هم هست
          {liquid && (
            <>
              {" "}
              (<Num value={liquid.locks.excess} kind="percent" digits={0} term="net_excess" />، t=
              <Num value={liquid.locks.t} digits={1} term="t_stat" />)
            </>
          )}
          . این عدد «مازاد نسبت به نمادِ میانهٔ بازار» است، پس از کارمزد.
        </p>
      </section>

      <section className="space-y-2" data-testid="book-ladder">
        <h3 className="text-lg font-bold">قاعدهٔ مدل با صف و حجم چقدر می‌ماند؟</h3>
        <p className="text-sm leading-7 text-muted">
          «ایده‌آل» یعنی هر سهم انتخاب‌شده در همان روز بدون مشکل خریدنی یا فروختنی بوده.{" "}
          <Link href="/glossary/queue_lock">«با صف»</Link> یعنی خرید در صف خرید تا{" "}
          {faNumber(a?.max_wait_buy ?? 3)} روز و فروش در صف فروش تا{" "}
          {faNumber(a?.max_wait_sell ?? 10)} روز منتظر می‌ماند، هر موقعیت حداکثر{" "}
          {faNumber(Math.round(100 * (a?.participation ?? 0.1)))}٪ ارزش معاملهٔ روز را می‌گیرد، و
          کارمزد در هر طرف {faNumber(100 * (a?.cost_per_side ?? 0), 2)}٪ است.
        </p>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[40rem]">
            <thead>
              <tr>
                <th>مجموعه</th>
                <th>بازبینی</th>
                <th>ایده‌آل (بدون صف)</th>
                <th>با صف</th>
                <th>نیمهٔ اول ← دوم (با صف)</th>
              </tr>
            </thead>
            <tbody>
              {d.ladder.map((r) => (
                <tr key={`${r.universe}${r.review}`}>
                  <td>{UNIVERSE[r.universe]}</td>
                  <td>هر {faNumber(r.review)} روز</td>
                  <td>
                    <Excess p={r.ideal} />
                  </td>
                  <td>
                    <Excess p={r.locks} />
                  </td>
                  <td>
                    <Num value={r.locks.early} kind="percent" digits={0} signed term="net_excess" />{" "}
                    ←{" "}
                    <Num value={r.locks.late} kind="percent" digits={0} signed term="net_excess" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm leading-7">
          <b>افت نیمهٔ دوم از بین رفت.</b> بدون صف به‌نظر می‌رسید برتری کوتاه‌مدت در نیمهٔ دوم بازه
          نصف می‌شود. با صف، دو نیمه تقریباً برابرند (ستون آخر): آنچه «افت» به نظر می‌آمد، سودِ
          غیرقابل‌خریدِ ماه‌های صف خرید بلند در نیمهٔ اول بود، نه از بین رفتن الگو.
        </p>
      </section>

      <section className="space-y-2" data-testid="book-capacity">
        <h3 className="text-lg font-bold">با چه سرمایه‌ای هنوز کار می‌کند؟</h3>
        <p className="text-sm leading-7 text-muted">
          همان قاعده با سقف ۱۰٪ ارزش معاملهٔ روز برای هر موقعیت، در اندازه‌های مختلف کل سبد: هرچه
          سبد بزرگ‌تر، بخش بیشتری از سفارش‌ها در ظرفیت معاملهٔ روز نمی‌گنجد و نقد می‌ماند.
        </p>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[36rem]">
            <thead>
              <tr>
                <th>اندازهٔ سبد</th>
                <th>همه، ۵ روز</th>
                <th>همه، ۲۰ روز</th>
                <th>۱۰۰ پرنقد، ۵ روز</th>
                <th>۱۰۰ پرنقد، ۲۰ روز</th>
              </tr>
            </thead>
            <tbody>
              {d.capacity.map((r) => (
                <tr key={r.notional_rial}>
                  <td>{tomanLabel(r.notional_rial)}</td>
                  {["all_R5", "all_R20", "liquid100_R5", "liquid100_R20"].map((k) => (
                    <td key={k}>{r.cells[k] ? <Excess p={r.cells[k]} /> : "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {d.random && (
        <section className="well space-y-1 text-sm leading-7" data-testid="book-random">
          <h3 className="font-bold">کنترل: اگر امتیاز تصادفی بود؟</h3>
          <p>
            همین شبیه‌ساز با امتیازِ تصادفی و بدون کارمزد برای ۵ روز{" "}
            <Num value={d.random.r5_zero_cost} kind="percent" digits={0} signed term="net_excess" />{" "}
            و برای ۲۰ روز{" "}
            <Num
              value={d.random.r20_zero_cost}
              kind="percent"
              digits={0}
              signed
              term="net_excess"
            />{" "}
            می‌دهد؛ یعنی مقایسه با نمادِ میانه سوگیری خوش‌بینانه ندارد. با کارمزد، امتیاز تصادفی{" "}
            <Num value={d.random.r5_with_cost} kind="percent" digits={0} signed term="net_excess" />{" "}
            (۵ روز) می‌شود، چون هر بازبینی حدود {faNumber(Math.round(100 * d.random.turnover))}٪ سبد
            عوض می‌شود: کارمزد گردش، بدون برتری واقعی، سبد را می‌خورد.
          </p>
        </section>
      )}

      <section className="space-y-2" data-testid="book-features">
        <h3 className="text-lg font-bold">کدام ویژگی‌های تابلو به امتیاز چیزی اضافه می‌کنند؟</h3>
        <p className="text-sm leading-7 text-muted">
          {faNumber(d.features.length)} ویژگی از تابلو، صف و تابلوخوانی هر کدام با وزن کوچک به
          امتیاز چهارسیگنالهٔ تولید افزوده شد. پایهٔ مقایسه ضریب اطلاعاتی (
          <Link href="/glossary/ic">IC</Link>) روی همین بازه است: ۱ روز{" "}
          <Num value={d.base_ic["1"]?.ic} digits={3} term="ic" />، ۵ روز{" "}
          <Num value={d.base_ic["5"]?.ic} digits={3} term="ic" />، ۲۰ روز{" "}
          <Num value={d.base_ic["20"]?.ic} digits={3} term="ic" />. جدول، تغییر IC با افزودن هر
          ویژگی را نشان می‌دهد؛ «نگه داشته شد» یعنی در هر دو نیمهٔ بازه مثبت و معنادار بود،
          «هم‌پوشان» یعنی تنها مفید بود ولی پس از افزودن ویژگی‌های بهتر چیزی اضافه نکرد، و «حذف شد»
          یعنی در هیچ افقی سودی نداشت یا فقط در یک نیمه داشت.
        </p>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[44rem]">
            <thead>
              <tr>
                <th>ویژگی</th>
                <th>وضعیت</th>
                <th>ΔIC ۱ روز</th>
                <th>ΔIC ۵ روز</th>
                <th>ΔIC ۲۰ روز</th>
                <th>نیمهٔ اول / دوم (۵ روز)</th>
              </tr>
            </thead>
            <tbody>
              {d.features.map((f) => (
                <tr key={f.key} data-feature={f.key}>
                  <td>
                    <b className="block">{f.label}</b>
                    <span className="block max-w-[22rem] text-xs leading-5 text-muted">
                      {f.meaning}
                    </span>
                  </td>
                  <td>
                    <StatusChip s={f.status} />
                  </td>
                  <td>
                    <Delta v={f.d1} t={f.t1} />
                  </td>
                  <td>
                    <Delta v={f.d5} t={f.t5} />
                  </td>
                  <td>
                    <Delta v={f.d20} t={f.t20} />
                  </td>
                  <td>
                    <Num value={f.early5} digits={4} signed term="ic" /> /{" "}
                    <Num value={f.late5} digits={4} signed term="ic" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm leading-7">
          <b>برای ۱ تا ۵ روز، {faNumber(kept.length)} ویژگی ماندند</b> (به ترتیب انتخاب: عدم‌تعادل
          میانگین تابلو، عدم‌تعادل پایان، نسبت اندازهٔ سفارش‌ها، عدم‌تعادل شروع، فاصلهٔ آخرین معامله
          تا پایانی). <b>برای ۲۰ روز و بیشتر چیز پایداری نبود</b>؛ فقط عدم‌تعادل میانگین حاشیه‌ای
          است و ناپایدار. مدل بلندمدتِ محصول تغییر نکرده است و این امتیاز کوتاه‌مدت به هیچ توصیه‌ای
          وصل نیست.
        </p>
      </section>

      {sel.pick_early_test_late && sel.pick_late_test_early && (
        <section className="well space-y-1 text-sm leading-7" data-testid="book-selection">
          <h3 className="font-bold">آیا انتخاب ویژگی‌ها خودش به داده «بیش‌برازش» شده؟</h3>
          <p>
            ویژگی‌ها را فقط با نیمهٔ اول بازه (تا {jalali(d.split)}) انتخاب کردیم و روی نیمهٔ دوم
            سنجیدیم: IC پنج‌روزه{" "}
            <Num value={sel.pick_early_test_late.d5} digits={3} signed term="ic" /> (t=
            <Num value={sel.pick_early_test_late.t5} digits={1} term="t_stat" />) بالاتر رفت. برعکس
            (انتخاب با نیمهٔ دوم، سنجش در اول):{" "}
            <Num value={sel.pick_late_test_early.d5} digits={3} signed term="ic" /> (t=
            <Num value={sel.pick_late_test_early.t5} digits={1} term="t_stat" />
            ). در هر دو جهت مثبت است، پس تصادفی بودنش بعید است. در ۲۰ روز: فقط{" "}
            <Num value={sel.pick_early_test_late.d20} digits={3} signed term="ic" /> (t=
            <Num value={sel.pick_early_test_late.t20} digits={1} term="t_stat" />
            )، حاشیه‌ای.
          </p>
        </section>
      )}

      <section className="space-y-2" data-testid="book-score-sim">
        <h3 className="text-lg font-bold">آیا امتیاز تابلو پس از کارمزد سود بیشتری می‌سازد؟</h3>
        <p className="text-sm leading-7 text-muted">
          امتیاز کوتاه‌مدت (پنج ویژگی) را در همان شبیه‌ساز واقع‌گرا روی ۱۰۰ نماد (۱۰ نام) گذاشتیم.
          مازاد سالانه پس از کارمزد نسبت به نمادِ میانه:
        </p>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[30rem]">
            <thead>
              <tr>
                <th>حالت</th>
                <th>امتیاز پایه</th>
                <th>پایه + تابلو</th>
                <th>گردش (پایه ← تابلو)</th>
              </tr>
            </thead>
            <tbody>
              {d.score_sim.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td>
                    <Excess p={r.base} />
                  </td>
                  <td>
                    <Excess p={r.book} />
                  </td>
                  <td>
                    <Num value={r.base.turnover} kind="percent" digits={0} term="net_excess" /> ←{" "}
                    <Num value={r.book.turnover} kind="percent" digits={0} term="net_excess" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm leading-7">
          <b>نتیجه: جهت را بهتر پیش‌بینی می‌کند ولی سود خالص بیشتر هنوز ثابت نشده.</b> تفاضل پس از
          کارمزد مثبت است اما معنادار نیست، چون سود ناخالص بیشتر می‌شود و گردش هم تقریباً دو برابر.
          دورهٔ آزمون کوتاه است و بازار در آن بسیار صعودی بود (بازدهٔ سالانهٔ نمادِ میانه بیش از
          ۲۰۰٪).
        </p>
      </section>

      <section className="card space-y-2 text-sm" data-testid="book-limits">
        <h3 className="text-lg font-bold">محدودیت‌ها، پیش از اتکا به این بخش</h3>
        <ul className="list-inside list-disc space-y-1 leading-7">
          {d.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p className="text-xs text-muted">
          داده از {d.generated ? jalali(d.generated) : "—"} است و با هر بار اجرای مطالعه به‌روز
          می‌شود. {d.disclaimer}.
        </p>
      </section>
    </section>
  );
}
