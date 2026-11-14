import Link from "next/link";
import type { Ranking } from "@/lib/api";
import { faNumber } from "@/lib/format";

/** Rial per day -> short toman text. */
function tomanDay(rial: number | null | undefined): string {
  if (rial == null) return "—";
  const t = rial / 10;
  if (t >= 1e9) return `${faNumber(t / 1e9, 1)} میلیارد تومان`;
  return `${faNumber(t / 1e6, 0)} میلیون تومان`;
}

/** Stocks scored higher than some listed ones but outside the 100-stock liquid basket. The list
 * above shows only the basket, so the rest are named here with the reason instead of vanishing. */
export function OutsideBasket({ d }: { d: Ranking }) {
  if (d.outside.length === 0) return null;
  const cut = d.rows.find((r) => r.zone === "buy");
  return (
    <section className="card" data-testid="outside-basket">
      <h2 className="font-bold">امتیاز بالا، ولی بیرون از سبد توصیه</h2>
      <p className="mt-1 text-sm text-muted">
        مدل {d.universe_size != null ? `${faNumber(d.universe_size)} نماد` : "همهٔ نمادها"} را
        امتیاز می‌دهد، ولی فقط {faNumber(d.basket_size ?? 0)} نماد پرمعامله را فهرست می‌کند: مدل و
        آزمون‌هایش روی همین سبد ساخته شده و سفارش در آن‌ها بدون جابه‌جایی قیمت پر می‌شود. نمادهای
        زیر امتیاز بالایی دارند اما خارج از سبدند؛ نقدشوندگی کم یعنی خرید و فروش گران‌تر و گاهی
        ناممکن است و نتیجهٔ مدل برایشان آزموده نشده. پیشنهاد خرید نیستند.
        {cut && <> (بالاترین نمادِ سبد: {cut.symbol})</>}
      </p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {d.outside.map((r) => (
          <li key={r.instrument_id} className="tile">
            <Link href={`/instruments/${r.instrument_id}`} className="font-bold hover:text-accent">
              {r.symbol}
            </Link>{" "}
            <span className="text-sm text-muted">امتیاز {faNumber(Math.round(r.score * 100))}</span>
            <div className="truncate text-xs text-muted" title={r.name ?? ""}>
              {r.name}
            </div>
            <div className="text-xs">معاملهٔ روزانه: {tomanDay(r.median_value)}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
