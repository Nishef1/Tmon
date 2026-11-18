import type { InstrumentDashboard } from "@/lib/api";
import type { Mark } from "@/components/CandleChart";

export type Ride = NonNullable<NonNullable<InstrumentDashboard["turning"]>["ride"]>;

/** Buy and sell days of the latest trend ride, for the price chart. */
export function rideMarks(r: Ride): Mark[] {
  const out: Mark[] = [];
  if (r.entry_date) out.push({ time: r.entry_date, text: "خرید روند", color: "var(--up)" });
  if (r.exit_date)
    out.push({ time: r.exit_date, text: "فروش روند", color: "var(--down)", above: true });
  return out;
}
