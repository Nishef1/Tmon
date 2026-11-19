import type { InstrumentDashboard } from "@/lib/api";
import type { Mark } from "@/components/CandleChart";

export type Ride = NonNullable<NonNullable<InstrumentDashboard["turning"]>["ride"]>;

/** Buy and sell days of every ride the rule made on this symbol, for the price chart. Days
 *  before the first candle on the chart are left off. */
export function rideMarks(r: Ride, from?: string): Mark[] {
  const out: Mark[] = [];
  const shown = (d: string) => !from || d >= from;
  for (const q of r.rides) {
    if (shown(q.entry_date))
      out.push({ time: q.entry_date, text: "روند خرید", color: "var(--up)" });
    if (q.exit_date && shown(q.exit_date))
      out.push({ time: q.exit_date, text: "روند فروش", color: "var(--down)", above: true });
  }
  return out;
}
