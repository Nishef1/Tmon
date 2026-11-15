import type { InstrumentDashboard } from "@/lib/api";
import { NextCandles } from "@/components/entry/NextCandles";

type D = InstrumentDashboard;

/** One word for how far the past evidence can be trusted (t is the statistical strength). */
export function trustWord(t: number | null | undefined): string | null {
  if (t == null) return null;
  return t >= 3 ? "زیاد" : t >= 2 ? "متوسط" : "کم";
}

/** The stock's own price history replayed forward. It is a separate card, open by default: it
 *  comes from a different source than the verdict (the stock's own past moves, not the model),
 *  so putting it beside the verdict made the two look like they disagreed. */
export function PriceRange({ d }: { d: D }) {
  if (!d.entry || d.entry.own.length === 0) return null;
  return (
    <details className="card" data-testid="price-range" open>
      <summary className="cursor-pointer select-none">
        <span className="font-bold">اگر قیمت مثل گذشتهٔ خودش حرکت کند، کجا می‌رسد؟</span>
        <span className="ms-2 text-sm text-muted">فقط آمار گذشتهٔ همین سهم؛ سیگنال نیست</span>
      </summary>
      <p className="mt-3 rounded-lg bg-warn-soft p-2 text-sm" data-testid="candles-vs-verdict">
        این جدول فقط حرکت‌های گذشتهٔ خودِ همین سهم را تکرار می‌کند و از حکم «چه کنم؟» مستقل است. بعد
        از هر صعود، قیمت‌های بالاتر در این جدول تقریباً همیشه محتمل‌تر دیده می‌شوند؛ پس آن را نشانهٔ
        خرید نگیرید.
      </p>
      <div className="mt-3">
        <NextCandles e={d.entry} />
      </div>
    </details>
  );
}
