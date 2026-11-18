import type { MarketOverview } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

/** Rial -> toman, in a short unit. */
function tomanShort(rial: number): string {
  const t = rial / 10;
  return t >= 1e12
    ? `${faNumber(t / 1e12, 1)} هزار میلیارد تومان`
    : `${faNumber(t / 1e9, 0)} میلیارد تومان`;
}

/** One plain sentence on how broad the day was; description only. */
function mood(upShare: number): string {
  if (upShare >= 0.6) return "بیشتر سهم‌ها مثبت بستند";
  if (upShare <= 0.4) return "بیشتر سهم‌ها منفی بستند";
  return "بازار دوطرفه بود";
}

/** The first thing a visitor wants: did the market go up or down today, and how broadly. */
export function MarketStrip({ m }: { m: MarketOverview }) {
  const n = m.up + m.down + m.flat;
  if (n === 0) return null;
  const pct = (x: number) => `${(x / n) * 100}%`;
  const med = m.median_change;
  const tone = med == null ? "" : med >= 0 ? "text-up" : "text-down";
  return (
    <section className="ms card" data-testid="market-strip">
      <div className="ms-glow" aria-hidden />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <p className="eyebrow">بازار امروز · {jalali(m.price_date)}</p>
          <h2 className="text-xl font-black">{mood(m.up / n)}</h2>
        </div>
        <div className="text-end">
          <p className="text-xs text-muted">میانهٔ تغییر قیمت</p>
          <p className={`ms-big ${tone}`}>{med == null ? "—" : faPercent(med, 1, true)}</p>
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs font-semibold">
          <span className="text-up">{faNumber(m.up)} مثبت</span>
          {m.flat > 0 && <span className="text-muted">{faNumber(m.flat)} بدون تغییر</span>}
          <span className="text-down">{faNumber(m.down)} منفی</span>
        </div>
        <div
          className="ms-bar"
          role="img"
          aria-label={`${faNumber(m.up)} سهم مثبت، ${faNumber(m.down)} منفی، ${faNumber(m.flat)} بدون تغییر`}
        >
          <span className="bg-up" style={{ width: pct(m.up) }} />
          <span className="bg-line" style={{ width: pct(m.flat) }} />
          <span className="bg-down" style={{ width: pct(m.down) }} />
        </div>
      </div>
      <dl className="ms-stats">
        <div>
          <dt>در سقف قیمت</dt>
          <dd className="text-up">{faNumber(m.at_limit_up)}</dd>
        </div>
        <div>
          <dt>در کف قیمت</dt>
          <dd className="text-down">{faNumber(m.at_limit_down)}</dd>
        </div>
        <div>
          <dt>ارزش معاملات</dt>
          <dd>{tomanShort(m.total_value)}</dd>
        </div>
      </dl>
    </section>
  );
}
