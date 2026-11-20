"use client";

import { useState } from "react";
import { CandleChart, type Level, type Mark, type Path } from "@/components/CandleChart";
import type { Ride } from "@/components/stock/rideMarks";
import { faPercent, faPrice, jalali } from "@/lib/format";
import type { components } from "@/lib/api-schema";

type Candle = components["schemas"]["Candle"];
type Scale = components["schemas"]["TrendScale"];

const COLOR = "var(--series-3)";

/** The zigzag through the confirmed swings, then the running extreme of the leg the price is in
 *  and the last close, so the line ends where the price is now. */
export function zigzag(s: Scale, last: Candle | undefined): Path {
  const pts = s.swings.map((w) => ({ time: w.date, value: w.close as number | null }));
  if (s.extreme) pts.push({ time: s.extreme.date, value: s.extreme.close });
  if (last?.close != null && (pts.at(-1)?.time ?? "") < last.date)
    pts.push({ time: last.date, value: last.close });
  return { points: pts, color: COLOR, title: `روند ${s.label}`, straight: true };
}

/** One sentence on the leg the price is in: where it began, how far it went, and the close that
 *  would confirm the turn. Past facts only; it is not an entry or exit signal. */
export function legText(s: Scale): string | null {
  if (!s.direction || !s.since || !s.extreme || s.from_since == null || s.from_extreme == null)
    return null;
  const pct = faPercent(s.size, 0);
  if (s.direction === "up") {
    const turn = s.extreme.close * (1 - s.size);
    return `روند ${s.label} صعودی است: از کفِ ${jalali(s.since.date, "monthDay")} (${faPrice(s.since.close)}) تا الان ${faPercent(s.from_since, 0, true)}. بالاترین نقطهٔ این صعود ${faPrice(s.extreme.close)} بوده (${jalali(s.extreme.date, "monthDay")}) و قیمت الان ${faPercent(s.from_extreme, 1, true)} نسبت به آن است. اگر قیمت پایانی زیر ${faPrice(turn)} بیاید (${pct} برگشت از سقف)، این صعود تمام‌شده حساب می‌شود.`;
  }
  const turn = s.extreme.close * (1 + s.size);
  return `روند ${s.label} نزولی است: از سقفِ ${jalali(s.since.date, "monthDay")} (${faPrice(s.since.close)}) تا الان ${faPercent(s.from_since, 0, true)}. پایین‌ترین نقطهٔ این ریزش ${faPrice(s.extreme.close)} بوده (${jalali(s.extreme.date, "monthDay")}) و قیمت الان ${faPercent(s.from_extreme, 1, true)} نسبت به آن است. اگر قیمت پایانی بالای ${faPrice(turn)} برود (${pct} برگشت از کف)، این ریزش تمام‌شده حساب می‌شود.`;
}

/** What the entry and exit rule says today, in one plain line. */
export function ruleLine(r: Ride): string {
  switch (r.status) {
    case "buy_next":
      return "قاعدهٔ ورود و خروج روند: امروز نشانهٔ ورود داد؛ خرید در قیمت پایانی روز بعد حساب می‌شود.";
    case "open":
      return `قاعدهٔ ورود و خروج روند: الان در روند است (از ${jalali(r.entry_date, "monthDay")})؛ خط فروش ${r.stop != null ? faPrice(r.stop) : "—"}.`;
    case "sell_next":
      return "قاعدهٔ ورود و خروج روند: خط فروش شکست؛ فروش در قیمت پایانی روز بعد حساب می‌شود.";
    default:
      return r.buy_trigger != null
        ? `قاعدهٔ ورود و خروج روند: الان ورود نیست. نشانهٔ ورود وقتی می‌آید که قیمت پایانی از ${faPrice(r.buy_trigger)} بالاتر برود.`
        : "قاعدهٔ ورود و خروج روند: الان ورود نیست.";
  }
}

export function PriceChartTrends({
  candles,
  marks,
  paths,
  levels,
  scales,
  ride,
}: {
  candles: Candle[];
  marks: Mark[];
  paths?: Path[];
  levels?: Level[];
  scales: Scale[];
  ride: Ride | null;
}) {
  const [pick, setPick] = useState<number>(scales.length > 1 ? 1 : 0);
  const s = pick >= 0 ? scales[pick] : undefined;
  const all = s ? [...(paths ?? []), zigzag(s, candles.at(-1))] : paths;
  const text = s ? legText(s) : null;

  return (
    <>
      {scales.length > 0 && (
        <div
          className="mb-2 flex flex-wrap items-center gap-1.5 text-sm"
          role="group"
          aria-label="اندازهٔ روند"
        >
          <span className="text-muted">روندها:</span>
          {[
            { label: "هیچ", i: -1 },
            ...scales.map((x, i) => ({ label: `${x.label} (${faPercent(x.size, 0)})`, i })),
          ].map((o) => (
            <button
              key={o.i}
              type="button"
              aria-pressed={pick === o.i}
              onClick={() => setPick(o.i)}
              className="rounded-full border border-line px-3 py-1 font-semibold text-muted transition-colors hover:bg-surface-2 aria-[pressed=true]:border-accent aria-[pressed=true]:bg-accent aria-[pressed=true]:text-white"
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      <CandleChart candles={candles} marks={marks} paths={all} levels={levels} />
      {(text || ride) && (
        <div className="mt-2 space-y-1 text-sm" data-testid="trend-now">
          {text && <p>{text}</p>}
          {ride && <p className="font-semibold">{ruleLine(ride)}</p>}
          <p className="text-xs text-muted">
            خط روند فقط گذشته را توصیف می‌کند و توصیهٔ خرید یا فروش نیست؛ هر کف و سقف بعد از برگشت به
            اندازهٔ همان درصد معلوم می‌شود. اندازه‌ها انتخاب نمایشی‌اند و آزمون نشده‌اند.
          </p>
        </div>
      )}
    </>
  );
}
