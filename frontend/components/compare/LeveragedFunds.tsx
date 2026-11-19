import Link from "next/link";
import type { FundType, LeveragedFund, LeveragedFunds } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

/** A fund of 14 months is not a fund of 4 years, so every row says how long it stands on. */
function span(days: number): string {
  const months = Math.round(days / 21);
  return months >= 24 ? `${faNumber(Math.round(months / 12))} سال` : `${faNumber(months)} ماه`;
}

function Row({ f }: { f: LeveragedFund }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="px-2 py-1.5 whitespace-nowrap">
        <Link href={`/instruments/${f.instrument_id}`} className="font-medium">
          {f.symbol}
        </Link>
        <div className="text-xs text-muted">
          {span(f.days)}، از {jalali(f.since)}
        </div>
      </td>
      <td className="px-2 py-1.5">
        <Num value={f.beta} term="beta" digits={2} />
      </td>
      <td className="px-2 py-1.5">
        <Num value={f.compound_month} kind="percent" term="nominal_return" digits={1} signed />
      </td>
      <td className="px-2 py-1.5">{faPercent(f.share_ge_target, 0)}</td>
      <td className="px-2 py-1.5">{faPercent(f.share_below_zero, 0)}</td>
      <td className="px-2 py-1.5">
        <Num value={f.worst_month} kind="percent" term="nominal_return" digits={0} />
      </td>
      <td className="px-2 py-1.5">
        <Num value={f.max_drawdown} kind="percent" term="max_drawdown" digits={0} />
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        {f.last_month == null ? (
          "—"
        ) : (
          <Num value={f.last_month} kind="percent" term="nominal_return" digits={0} signed />
        )}
        <div className="text-xs text-muted">
          شاخص کل <bdi dir="ltr">{faPercent(f.last_month_index, 1, true)}</bdi>
        </div>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        {f.price_over_nav == null ? (
          "—"
        ) : (
          <Num value={f.price_over_nav} term="fund_nav" digits={2} />
        )}
        {f.nav_date && <div className="text-xs text-muted">NAV {jalali(f.nav_date)}</div>}
      </td>
    </tr>
  );
}

function TypeRow({ t }: { t: FundType }) {
  return (
    <tr
      className={`border-b border-line last:border-0 ${t.type === "etf_leveraged" ? "font-bold" : ""}`}
    >
      <td className="px-2 py-1.5">
        {t.label} <span className="text-xs font-normal text-muted">({faNumber(t.funds)})</span>
      </td>
      <td className="px-2 py-1.5">
        <Num value={t.compound_month} kind="percent" term="nominal_return" digits={1} signed />
      </td>
      <td className="px-2 py-1.5">{faPercent(t.share_ge_target, 0)}</td>
      <td className="px-2 py-1.5">{faPercent(t.share_below_zero, 0)}</td>
      <td className="px-2 py-1.5">
        <Num value={t.worst_month} kind="percent" term="nominal_return" digits={0} />
      </td>
      <td className="px-2 py-1.5">
        <Num value={t.max_drawdown} kind="percent" term="max_drawdown" digits={0} />
      </td>
    </tr>
  );
}

/** The leveraged funds against the market, and the fund types side by side (docs/06-funds.md). */
export function LeveragedFundsSection({ data }: { data: LeveragedFunds }) {
  const target = faPercent(data.target, 0);
  if (data.funds.length === 0) {
    return <p className="text-sm text-muted">هنوز تحلیلی برای صندوق‌های اهرمی ساخته نشده است.</p>;
  }
  return (
    <div className="space-y-4" data-testid="leveraged-funds">
      <div className="space-y-1 text-sm text-muted">
        <p>
          صندوق اهرمی حرکت بازار را حدود <b>۱٫۸ برابر</b> می‌کند؛ ستون بتا همین را نشان می‌دهد. در
          بازار صعودی چند سال گذشته خوب دیده شدند، ولی ماهی {target} پایدار در تاریخ بیشترشان نبوده
          است. در افت‌ها هم همان‌قدر بزرگ‌تر پایین می‌آیند.
        </p>
        <p>
          <b>بازده ماهانهٔ مرکب</b>: اگر از روز اول نگه داشته بودید، هر ماه به‌طور میانگین چقدر. «ماه
          ≥ {target}» و «ماه زیر صفر» سهم پنجره‌های ۲۱ جلسه‌ای است که این‌طور تمام شدند. «بدترین
          ماه» بدترین ۲۱ جلسه است. «قیمت ÷ NAV» قیمت بازار تقسیم بر NAV کل صندوق است؛ برای اهرمی NAV
          واحد معامله‌شونده را نداریم، پس این عدد حباب نیست.
        </p>
        <p>
          صندوق‌های کم‌سابقه فقط در همان صعود بزرگ بوده‌اند؛ عدد آن‌ها را با صندوق‌های چندساله یکی
          نبینید. این جدول توصیه نیست.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="tbl min-w-[52rem]" data-testid="leveraged-table">
          <caption className="sr-only">صندوق‌های اهرمی در برابر بازار</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col">صندوق</th>
              <th scope="col">بتا</th>
              <th scope="col">بازده ماهانهٔ مرکب</th>
              <th scope="col">ماه ≥ {target}</th>
              <th scope="col">ماه زیر صفر</th>
              <th scope="col">بدترین ماه</th>
              <th scope="col">بیشترین افت</th>
              <th scope="col">۲۱ جلسهٔ آخر</th>
              <th scope="col">قیمت ÷ NAV</th>
            </tr>
          </thead>
          <tbody>
            {data.funds.map((f) => (
              <Row key={f.instrument_id} f={f} />
            ))}
          </tbody>
        </table>
      </div>
      {data.types.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-bold">انواع صندوق در {faNumber(data.type_years)} سال گذشته</h3>
          <p className="text-sm text-muted">
            سبد هم‌وزن از صندوق‌هایی که روزی دست‌کم یک میلیارد تومان معامله می‌شوند. درآمد ثابت
            معیار کم‌ریسک است.
          </p>
          <div className="overflow-x-auto">
            <table className="tbl min-w-[36rem]" data-testid="fund-types-table">
              <caption className="sr-only">انواع صندوق در چند سال گذشته</caption>
              <thead>
                <tr className="border-b border-line">
                  <th scope="col">نوع</th>
                  <th scope="col">بازده ماهانهٔ مرکب</th>
                  <th scope="col">ماه ≥ {target}</th>
                  <th scope="col">ماه زیر صفر</th>
                  <th scope="col">بدترین ماه</th>
                  <th scope="col">بیشترین افت</th>
                </tr>
              </thead>
              <tbody>
                {data.types.map((t) => (
                  <TypeRow key={t.type} t={t} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="text-xs text-muted">
        تا {jalali(data.as_of)}. روش و نتیجهٔ کامل: گزارش <code>leveraged-funds-2026-11</code> در
        پوشهٔ <code>docs/reports</code>.
      </p>
    </div>
  );
}
