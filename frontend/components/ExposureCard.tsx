import Link from "next/link";
import type { Ranking } from "@/lib/api";
import { faDigits, faPercent, faToman, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

/** The market card (ADR 0004): how much of the capital the model keeps in equities today and why;
 *  when that share is positive, the most traded equity funds with their NAV premium. The funds
 *  get no verdict and no past test. */
export function ExposureCard({ d }: { d: Ranking }) {
  const card = d.market_card;
  if (!d.exposure || !card) return null;
  return (
    <section className="card space-y-3 text-sm" data-testid="market-card">
      <h2 className="font-bold">چند درصد سرمایه امروز در سهام باشد؟</h2>
      {card.positive ? (
        <p>
          مدل در {jalali(card.date ?? d.exposure_date)}{" "}
          <Num value={card.exposure} kind="percent" term="exposure_level" digits={1} /> از سرمایه را
          در سهام نگه می‌دارد و باقی را در اوراق با درآمد ثابت.
        </p>
      ) : (
        <p data-testid="market-zero">
          مدل در {jalali(card.date ?? d.exposure_date)} هیچ بخشی از سرمایه را در سهام نمی‌خواهد
          (مواجهه صفر است)؛ پس امروز هیچ سهمی «خرید» نیست و همهٔ سرمایه در اوراق با درآمد ثابت
          می‌ماند.
        </p>
      )}
      {card.reasons.length > 0 && (
        <ul className="list-inside list-disc space-y-1" data-testid="market-reasons">
          {card.reasons.map((r) => (
            <li key={r}>{faDigits(r)}</li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">
        عددها: روند <Num value={d.exposure.trend} term="exposure_level" digits={2} />، مومنتوم{" "}
        <Num value={d.exposure.abs_mom} term="exposure_level" digits={2} />، سقف نوسان{" "}
        <Num value={d.exposure.vol_cap} term="exposure_level" digits={2} />، فشار صف فروش{" "}
        <Num value={d.exposure.stress} term="exposure_level" digits={3} />.
      </p>
      {card.positive && card.funds.length > 0 && (
        <div data-testid="market-funds" className="space-y-2">
          <h3 className="font-semibold">
            صندوق‌های سهامی پرمعامله <span className="chip">آزموده نشده</span>
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-start">
              <thead>
                <tr className="text-muted">
                  <th className="py-1 text-start font-normal">صندوق</th>
                  <th className="py-1 text-start font-normal">ارزش معاملات امروز</th>
                  <th className="py-1 text-start font-normal">قیمت نسبت به NAV</th>
                </tr>
              </thead>
              <tbody>
                {card.funds.map((f) => (
                  <tr key={f.instrument_id}>
                    <td className="py-1">
                      <Link href={`/instruments/${f.instrument_id}`} className="text-accent">
                        {f.symbol}
                      </Link>
                    </td>
                    <td className="py-1">{faToman(f.value)}</td>
                    <td className="py-1">
                      {f.premium == null ? (
                        <span className="text-muted">NAV ثبت نشده</span>
                      ) : (
                        <span title={f.nav_date ? `NAV تا ${jalali(f.nav_date)}` : undefined}>
                          {faPercent(f.premium, 1, true)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs leading-6 text-muted">{faDigits(card.funds_note)}</p>
        </div>
      )}
    </section>
  );
}
