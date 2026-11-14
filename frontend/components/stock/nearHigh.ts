import type { InstrumentDashboard } from "@/lib/api";

type T = NonNullable<InstrumentDashboard["turning"]>;

/** Within this of the 52-week high counts as "near the high" everywhere on the page. */
export const NEAR_HIGH = -0.05;

/** The state's record in words when it has no edge both halves agree on beyond the cost: still
 *  say which way both halves leaned, so "no stable record" never sits next to clearly negative
 *  numbers. Null for the up/down states, which keep their own label. */
export function toneWord(s: T["state"]): string | null {
  if (s.tone !== "none") return null;
  const [a, b] = s.halves_excess_120;
  if (a != null && b != null && a < 0 && b < 0) return "معمولاً ضعیف‌تر از بازار، ولی نه قطعی";
  if (a != null && b != null && a > 0 && b > 0) return "معمولاً بهتر از بازار، ولی نه قطعی";
  return "سابقهٔ پایداری ندارد";
}

/** One sentence that reconciles the places that mention the 52-week high, or null when the
 *  stock is not near it. Each place measures a different thing: the ranking signal (closeness
 *  to the high, tested on one month), the state the stock is in (how it got there, tested on
 *  six months) and a bare new-high crossing (tested alone). */
export function nearHighNote(t: T): string | null {
  if (t.dd == null || t.dd < NEAR_HIGH) return null;
  const general =
    "نزدیک سقف یک‌ساله بودن به‌خودی‌خود نشانهٔ خوبی است: در امتیاز یک‌ماهه مثبت حساب می‌شود و سهم‌هایی که با «روند صعودی، نزدیک سقف» به آن رسیده‌اند، در گذشته از بازار جلو زده‌اند.";
  const k = t.state.key;
  if (k === "uptrend_high") return `${general} این سهم هم در همین حالت است.`;
  if (k.startsWith("hot")) {
    return `${general} ولی این سهم با «${t.state.title}» به سقف رسیده (بیش از دو برابر در سه ماه)؛ سابقهٔ این حالت: ${t.state.tone === "down" ? "بدتر از بازار" : (toneWord(t.state) ?? "")}. برای همین «نزدیک سقف» در امتیاز سبز است، ولی حالت سهم ${t.state.tone === "down" ? "قرمز" : "بی‌رنگ"} است.`;
  }
  return `${general} حالت فعلی این سهم «${t.state.title}» است و رنگ آن سابقهٔ همین حالت را نشان می‌دهد، نه فقط نزدیکی به سقف را.`;
}
