import type { InstrumentDashboard } from "@/lib/api";
import type { Level, Mark, Path } from "@/components/CandleChart";

export type Ride = NonNullable<NonNullable<InstrumentDashboard["turning"]>["ride"]>;

/** Buy and sell days of every ride the rule made on this symbol, and the past lows and highs
 *  that only hindsight shows (a move of the trail's size followed them), for the price chart.
 *  Days before the first candle on the chart are left off. */
export function rideMarks(r: Ride, from?: string): Mark[] {
  const out: Mark[] = [];
  const shown = (d: string) => !from || d >= from;
  for (const q of r.rides) {
    if (shown(q.entry_date))
      out.push({ time: q.entry_date, text: "روند خرید", color: "var(--up)" });
    if (q.exit_date && shown(q.exit_date))
      out.push({ time: q.exit_date, text: "روند فروش", color: "var(--down)", above: true });
  }
  for (const s of r.swings ?? []) {
    if (!shown(s.date)) continue;
    const low = s.kind === "low";
    out.push({
      time: s.date,
      text: low ? "کف" : "سقف",
      color: "var(--muted)",
      above: !low,
      shape: "circle",
    });
  }
  return out;
}

type Pt = Ride["sell_line"][number];
const points = (xs: Pt[], k = 1) =>
  xs.map((p) => ({ time: p.date, value: p.value == null ? null : p.value * k }));

/** The rule's lines on every past day, as steps on the day whose close was compared with them:
 *  the sell line while a ride was held and the entry price on free days it was near, each with
 *  the edge of its warning band (dotted). Tomorrow's values are the levels of `rideLevels`. */
export function ridePaths(r: Ride): Path[] {
  const w = r.warn_band;
  const out: Path[] = [];
  if (r.sell_line.length > 0) {
    out.push({ points: points(r.sell_line), color: "var(--down)", title: "خط فروش" });
    if (w) out.push({ points: points(r.sell_line, 1 + w), color: "var(--down)", dotted: true });
  }
  if (r.buy_line.length > 0) {
    out.push({ points: points(r.buy_line), color: "var(--up)", title: "قیمت ورود" });
    if (w) out.push({ points: points(r.buy_line, 1 / (1 + w)), color: "var(--up)", dotted: true });
  }
  return out;
}

/** Tomorrow's sell line or entry price, as a level across the chart. An entry price one day
 *  cannot reach (past the largest one-day rise of the last year) is left off. */
export function rideLevels(r: Ride): Level[] {
  if (r.status === "open" && r.stop != null)
    return [{ price: r.stop, title: "خط فروش فردا", color: "var(--down)" }];
  const x = r.buy_trigger;
  if (r.status === "closed" && x != null) {
    const rise = x / r.last_close - 1;
    if (r.day_rise_max == null || rise <= r.day_rise_max)
      return [{ price: x, title: "قیمت ورود فردا", color: "var(--up)" }];
  }
  return [];
}

/** How close the next close is to crossing the rule's line, when it is inside the warning band:
 *  how far the close is from it, as in the study (the rise to the entry price, the height above
 *  the sell line). The chart draws the same bands. */
export function rideWarning(r: Ride): { side: "buy" | "sell"; move: number } | null {
  const w = r.warn_band;
  if (!w) return null;
  if (r.status === "open" && r.stop != null) {
    const move = r.last_close / r.stop - 1;
    return move <= w ? { side: "sell", move } : null;
  }
  if (r.status === "closed" && r.buy_trigger != null) {
    const move = r.buy_trigger / r.last_close - 1;
    return move <= w ? { side: "buy", move } : null;
  }
  return null;
}
