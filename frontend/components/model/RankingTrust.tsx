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
  G6: "بازمانده‌سوگیری",
};

/** Why the v2 ranking is or is not a recommendation: gate verdicts and its past evidence per horizon. */
export function RankingTrust({ d }: { d: Ranking }) {
  return (
    <section id="v2" className="scroll-mt-20 space-y-5">
      <h2 className="text-xl font-extrabold">رتبه‌بندی خرید، نگهداری و فروش: چقدر قابل اتکاست؟</h2>
      <section className="alert-warn alert-lg space-y-2 text-ink" data-testid="ranking-status">
        <h2 className="text-lg font-bold">
          {d.recommendation_allowed
            ? "همهٔ دروازه‌های آزمون گذشته‌اند"
            : "این فهرست رتبه‌بندی مدل است، توصیهٔ خرید نیست"}
        </h2>
        <p>
          تاریخ داده: {jalali(d.as_of)}. طبق قاعدهٔ ثبت‌شدهٔ پروژه، تا وقتی همهٔ دروازه‌های آزمون
          (G1 تا G6) نگذرند، خروجی v2 نباید توصیه نامیده شود. وضعیت آزمون روی داده‌های واقعی:
        </p>
        <ul className="list-inside list-disc space-y-1">
          {d.gates.map((c) => (
            <li key={c.candidate}>
              <strong>{c.candidate === "v2" ? "v2 کامل" : "انتخاب سهام تنها"}</strong> (
              {jalali(c.first)} تا {jalali(c.last)}، {faNumber(c.days)} روز): بازده سالانه{" "}
              <Num value={c.annual} kind="percent" term="realized_return" digits={1} /> در برابر
              شاخص سبد{" "}
              <Num value={c.annual_bench} kind="percent" term="realized_return" digits={1} /> ·
              حداکثر افت{" "}
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
        <p className="text-muted">
          معنی‌اش: هیچ‌یک از این نمادها «پیشنهاد خرید» نیست. اگر مالک تصمیم بگیرد با همین شرایط آن
          را توصیه حساب کند، آن تصمیم جداگانه و صریح است.
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
                <th>۱۰٪ بالا نسبت به بازار</th>
                <th>۱۰٪ پایین نسبت به بازار</th>
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
          افق روزانه (۱ روز) و سالانه (۲۵۲ روز) سنجیده نشده‌اند و برای آن‌ها هیچ ادعایی نمی‌شود.
          اعداد جدول پیش از هزینهٔ معامله‌اند؛ کارمزد و مالیات یک خرید و فروش روی هم حدود ۱٫۷۵٪ است
          و نتیجهٔ پس از هزینه در بخش دروازه‌ها بالا آمده است.
          {d.book && (
            <>
              {" "}
              سبد آزمون: {faNumber(d.book.n_buys)} خرید، {faNumber(d.book.cancelled_buys)} خرید
              لغوشده به دلیل صف، {faNumber(d.book.postponed_sells)} فروش عقب‌افتاده، میانگین{" "}
              {faNumber(d.book.avg_held, 1)} نماد در سبد.
            </>
          )}{" "}
          بخش بزرگی از برتری سبد ما بر شاخص سبد، کمتر معامله‌کردن است نه پیش‌بینی بهتر.
        </p>
      </section>
    </section>
  );
}
