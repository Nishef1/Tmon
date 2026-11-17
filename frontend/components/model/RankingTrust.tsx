import Link from "next/link";
import type { Ranking } from "@/lib/api";
import { faDigits, faNumber, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

const GATE_NAMES: Record<string, string> = {
  G1: "بازده بهتر از شاخص",
  G2: "افت کمتر از شاخص",
  G3: "گردش ماهانه",
  G4: "معناداری آماری",
  G5: "پایداری",
  G6: "سوگیری بازمانده",
};

/** Why the v2 ranking is or is not a recommendation: gate verdicts and its past evidence per horizon. */
export function RankingTrust({ d }: { d: Ranking }) {
  return (
    <section id="v2" className="scroll-mt-20 space-y-5">
      <h2 className="text-xl font-extrabold">رتبه‌بندی خرید، نگهداری و فروش: چقدر قابل اتکاست؟</h2>
      <section className="alert-warn alert-lg space-y-2 text-ink" data-testid="ranking-status">
        <h2 className="text-lg font-bold">
          {d.recommendation_allowed
            ? "رتبه‌بندی از همهٔ آزمون‌های پذیرش آزمون گذشته است"
            : "این فهرست رتبه‌بندی مدل است و توصیهٔ خرید نیست"}
        </h2>
        <p>
          تاریخ داده: {jalali(d.as_of)}. «آزمون پذیرش» یعنی شرطی که رتبه‌بندی باید در آزمون روی
          داده‌های گذشته برآورده کند. طبق قاعدهٔ این پروژه، تا وقتی هر شش آزمون پذیرش (G1 تا G6)
          برقرار نشده‌اند، خروجی v2 توصیه نامیده نمی‌شود. نتیجهٔ آزمون روی داده‌های واقعی:
        </p>
        <p data-testid="ranking-weights">
          وزن چهار سیگنال در امتیاز:{" "}
          {d.weights_champion === "equal"
            ? "مساوی (میانگین ساده)؛ هیچ روش دیگری از آزمون ارتقای الگوریتم زنده نگذشته است."
            : `روش «${d.weights_champion}» که از آزمون ارتقا گذشته است؛ آزمون‌های پذیرش بالا روی همین امتیاز سنجیده شده‌اند.`}{" "}
          <Link href="/model#adapt">جزئیات</Link>
        </p>
        <ul className="list-inside list-disc space-y-1">
          {d.gates.map((c) => (
            <li key={c.candidate}>
              <strong>{c.candidate === "v2" ? "v2 کامل" : "انتخاب سهام تنها"}</strong> (
              {jalali(c.first)} تا {jalali(c.last)}، {faNumber(c.days)} روز): بازده سالانه{" "}
              <Num value={c.annual} kind="percent" term="realized_return" digits={1} /> در برابر
              شاخص سبد{" "}
              <Num value={c.annual_bench} kind="percent" term="realized_return" digits={1} /> (همان
              ۱۰۰ سهم با خرید و فروش مکرر و کارمزد). اگر همان ۱۰۰ سهم را بدون معامله مکرر نگه
              می‌داشتید{" "}
              <Num value={c.annual_buy_hold} kind="percent" term="realized_return" digits={1} /> و
              شاخص هم‌وزن رسمی{" "}
              <Num value={c.annual_official} kind="percent" term="realized_return" digits={1} />{" "}
              سالانه می‌شد
              {c.annual != null && c.annual_buy_hold != null && c.annual < c.annual_buy_hold && (
                <strong data-testid="below-buy-hold">
                  {" "}
                  ؛ یعنی این روش از نگه‌داشتن ساده عقب است
                </strong>
              )}{" "}
              · حداکثر افت{" "}
              <Num value={c.max_drawdown} kind="percent" term="max_drawdown" digits={1} /> در برابر{" "}
              <Num value={c.max_drawdown_bench} kind="percent" term="max_drawdown" digits={1} />.{" "}
              <span className="font-semibold">{faDigits(c.verdict)}</span>
              <ul className="mr-5 list-inside list-disc text-xs text-muted">
                {c.gates
                  .filter((g) => g.passed !== true)
                  .map((g) => (
                    <li key={g.key}>
                      {g.key} ({GATE_NAMES[g.key] ?? ""}): {faDigits(g.text)}
                    </li>
                  ))}
              </ul>
            </li>
          ))}
        </ul>
        {d.invested_reference && (
          <p data-testid="invested-reference">
            مرجع همین صفحه (گزارش {d.invested_reference.report}،{" "}
            {jalali(d.invested_reference.first)} تا {jalali(d.invested_reference.last)}): نگه‌داشتن
            سادهٔ همهٔ سهم‌های قابل‌معامله (S0){" "}
            <Num
              value={d.invested_reference.s0_annual}
              kind="percent"
              term="invested_reference"
              digits={1}
            />{" "}
            سالانه، شاخص هم‌وزن رسمی{" "}
            <Num
              value={d.invested_reference.official_annual}
              kind="percent"
              term="invested_reference"
              digits={1}
            />{" "}
            و اوراق خزانه{" "}
            <Num
              value={d.invested_reference.bill_annual}
              kind="percent"
              term="invested_reference"
              digits={1}
            />
            . هر بازدهٔ سالانهٔ بالا را با همین سه عدد بسنجید.
          </p>
        )}
        <p className="text-muted">
          یعنی هیچ‌یک از این نمادها «پیشنهاد خرید» نیست. فقط وقتی همهٔ آزمون‌های پذیرش برقرار شوند،
          یا صاحب پروژه صریحاً تصمیم بگیرد، فهرست توصیه شمرده می‌شود.
        </p>
      </section>

      <section className="space-y-2" data-testid="ranking-evidence">
        <h2 className="text-lg font-bold">این رتبه‌بندی در گذشته چقدر کار کرده؟</h2>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[34rem]">
            <thead>
              <tr className="text-right">
                <th>افق</th>
                <th>
                  <Link href="/glossary/ic">IC</Link>
                </th>
                <th>
                  <Link href="/glossary/t_stat">t</Link> (IC)
                </th>
                <th>۱۰٪ بالا نسبت به میانگین ۱۰۰ سهم پرنقد</th>
                <th>۱۰٪ پایین نسبت به میانگین ۱۰۰ سهم پرنقد</th>
                <th>روز</th>
              </tr>
            </thead>
            <tbody>
              {d.evidence.map((e) => (
                <tr key={e.horizon_days} className="border-t border-line">
                  <td className="py-1">{faNumber(e.horizon_days)} روز کاری</td>
                  <td>
                    <Num value={e.ic} term="ic" digits={3} signed />
                  </td>
                  <td>
                    <Num value={e.ic_t} term="t_stat" digits={1} />
                  </td>
                  <td>
                    <Num value={e.top_excess} kind="percent" term="ic" digits={2} signed />
                  </td>
                  <td>
                    <Num value={e.bottom_excess} kind="percent" term="ic" digits={2} signed />
                  </td>
                  <td>{faNumber(e.n_days)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">
          افق یک‌روزه و یک‌ساله (۲۵۲ روز کاری) سنجیده نشده‌اند و دربارهٔ آن‌ها هیچ ادعایی نمی‌شود.
          اعداد جدول پیش از کسر هزینهٔ معامله‌اند؛ کارمزد و مالیات یک خرید و فروش روی هم حدود ۱٫۷۵٪
          است و نتیجهٔ پس از کسر هزینه در بخش آزمون‌های پذیرش بالا آمده است.
          {d.book && (
            <>
              {" "}
              سبد آزمون: {faNumber(d.book.n_buys)} خرید انجام شد، {faNumber(d.book.cancelled_buys)}{" "}
              خرید به‌دلیل صف بودن سهم لغو شد، {faNumber(d.book.postponed_sells)} فروش به روز بعد
              افتاد و به‌طور میانگین {faNumber(d.book.avg_held, 1)} نماد در سبد بود.
            </>
          )}{" "}
          بخش بزرگی از برتری این سبد بر شاخص سبد از کمتر معامله کردن می‌آید، نه از پیش‌بینی بهتر.
        </p>
      </section>
    </section>
  );
}
