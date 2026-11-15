import type { MarketOverview } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

/** Rial -> toman, in a short unit. */
function tomanShort(rial: number): string {
  const t = rial / 10;
  return t >= 1e12
    ? `${faNumber(t / 1e12, 1)} هزار میلیارد تومان`
    : `${faNumber(t / 1e9, 0)} میلیارد تومان`;
}

/** The first thing a visitor wants: did the market go up or down today, and how broadly. */
export function MarketStrip({ m }: { m: MarketOverview }) {
  const n = m.up + m.down + m.flat;
  if (n === 0) return null;
  const pct = (x: number) => `${(x / n) * 100}%`;
  const med = m.median_change;
  return (
    <section className="card space-y-3" data-testid="market-strip">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">بازار امروز</h2>
        <span className="text-xs text-muted">{jalali(m.price_date)}</span>
      </div>
      <div
        className="flex h-3 overflow-hidden rounded-full bg-surface-2"
        role="img"
        aria-label={`${faNumber(m.up)} سهم مثبت، ${faNumber(m.down)} منفی، ${faNumber(m.flat)} بدون تغییر`}
      >
        <span className="bg-up" style={{ width: pct(m.up) }} />
        <span className="bg-line" style={{ width: pct(m.flat) }} />
        <span className="bg-down" style={{ width: pct(m.down) }} />
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
        <Stat label="مثبت" value={faNumber(m.up)} tone="text-up" />
        <Stat label="منفی" value={faNumber(m.down)} tone="text-down" />
        <Stat
          label="میانهٔ تغییر"
          value={med == null ? "—" : faPercent(med, 1, true)}
          tone={med == null ? "" : med >= 0 ? "text-up" : "text-down"}
        />
        <Stat
          label="سقف / کف قیمت"
          value={`${faNumber(m.at_limit_up)} / ${faNumber(m.at_limit_down)}`}
          tone=""
        />
        <Stat label="ارزش معاملات" value={tomanShort(m.total_value)} tone="" />
      </dl>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-base font-bold ${tone}`}>{value}</dd>
    </div>
  );
}
