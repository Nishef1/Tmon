"use client";

import { useMemo, useState } from "react";
import type { BreadthDay, IndexSeries, MarketIndex } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import { CandleChart } from "@/components/CandleChart";

const arrow = (x: number | null | undefined) => (x == null || x === 0 ? "" : x > 0 ? "▲" : "▼");

function Stat({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: string }) {
  return (
    <div className="ix-stat">
      <dt>{k}</dt>
      <dd className={tone}>{v}</dd>
      {sub && <small>{sub}</small>}
    </div>
  );
}

/** The day's range as a track: low on one end, high on the other, the close marked, the previous
 *  close as a tick. */
function DayRange({ s }: { s: IndexSeries }) {
  if (s.high == null || s.low == null || s.high <= s.low) return null;
  const at = (v: number) =>
    `${Math.min(100, Math.max(0, ((v - s.low!) / (s.high! - s.low!)) * 100))}%`;
  const tone = (s.change ?? 0) >= 0 ? "var(--up)" : "var(--down)";
  return (
    <div className="ix-range" data-testid="index-range">
      <div className="flex justify-between text-xs text-muted">
        <span>کمترین امروز {faNumber(s.low)}</span>
        <span>بیشترین امروز {faNumber(s.high)}</span>
      </div>
      <div className="ix-track" role="img" aria-label="جای پایانی در دامنهٔ امروز">
        <span
          className="ix-fill"
          style={{ insetInlineStart: 0, width: at(s.close), background: tone }}
        />
        {s.prev_close != null && s.prev_close >= s.low && s.prev_close <= s.high && (
          <span
            className="ix-tick"
            style={{ insetInlineStart: at(s.prev_close) }}
            title="پایانی دیروز"
          />
        )}
        <span className="ix-dot" style={{ insetInlineStart: at(s.close), background: tone }} />
      </div>
    </div>
  );
}

/** Up / flat / down counts of each of the last days, newest on the left. */
function BreadthHistory({ days }: { days: BreadthDay[] }) {
  if (days.length < 2) return null;
  return (
    <div className="space-y-1.5" data-testid="breadth-history">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-extrabold">پهنای بازار در {faNumber(days.length)} روز اخیر</h3>
        <span className="text-xs text-muted">هر ستون یک روز؛ سبز مثبت، قرمز منفی</span>
      </div>
      <div className="ix-hist" dir="ltr">
        {days.map((d) => {
          const n = d.up + d.down + d.flat || 1;
          return (
            <div
              key={d.date}
              className="ix-hcol"
              title={`${jalali(d.date, "short")}: ${faNumber(d.up)} مثبت، ${faNumber(d.down)} منفی، ${faNumber(d.flat)} بدون تغییر`}
            >
              <span className="bg-up" style={{ height: `${(d.up / n) * 100}%` }} />
              <span className="bg-line" style={{ height: `${(d.flat / n) * 100}%` }} />
              <span className="bg-down" style={{ height: `${(d.down / n) * 100}%` }} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The first thing on the home page: the market index with the whole day's detail. */
export function IndexHero({ m }: { m: MarketIndex }) {
  const [key, setKey] = useState(m.series[0]?.key ?? "tedpix");
  const s = m.series.find((x) => x.key === key) ?? m.series[0];
  // the volume bars are the day's traded value; in toman it fits the chart's number range
  const candles = useMemo(
    () =>
      (s?.candles ?? []).map((c) => ({ ...c, volume: c.volume == null ? null : c.volume / 10 })),
    [s],
  );
  if (!s) return null;
  const pts = s.prev_close != null ? s.close - s.prev_close : null;
  const tone = signTone(s.change);
  const last = m.days[m.days.length - 1];
  return (
    <section className="card ix" data-testid="index-hero">
      <div className="ix-glow" aria-hidden />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-0.5">
          <p className="eyebrow">شاخص بازار · {jalali(s.date, "weekday")}</p>
          <h2 className="text-lg font-black">{s.name}</h2>
        </div>
        {m.series.length > 1 && (
          <div className="flex gap-1.5" role="group" aria-label="انتخاب شاخص">
            {m.series.map((x) => (
              <button
                key={x.key}
                type="button"
                className="tab tab-pill"
                aria-pressed={x.key === s.key}
                onClick={() => setKey(x.key)}
              >
                {x.key === "tedpix" ? "شاخص کل" : "هم‌وزن"}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-1">
        <p className="ix-level num" data-testid="index-close">
          {faNumber(s.close)}
        </p>
        <p className={`ix-change ${tone}`} data-testid="index-change">
          <span aria-hidden>{arrow(s.change)}</span>{" "}
          {s.change == null ? "—" : faPercent(s.change, 2, true)}
          {pts != null && <small className="ms-2"> {faNumber(pts, 0)} واحد</small>}
        </p>
      </div>

      <DayRange s={s} />

      <dl className="ix-stats">
        <Stat k="پایانی دیروز" v={s.prev_close == null ? "—" : faNumber(s.prev_close)} />
        <Stat
          k="دامنهٔ امروز"
          v={s.range_pct == null ? "—" : faPercent(s.range_pct, 2)}
          sub="بیشترین نسبت به کمترین"
        />
        <Stat
          k="بیشترین یک سال"
          v={s.year_high == null ? "—" : faNumber(s.year_high)}
          sub={
            s.from_year_high == null ? undefined : `${faPercent(s.from_year_high, 1)} با آن فاصله`
          }
          tone={s.from_year_high != null && s.from_year_high > -0.02 ? "text-up" : undefined}
        />
        <Stat
          k="کمترین یک سال"
          v={s.year_low == null ? "—" : faNumber(s.year_low)}
          sub={
            s.above_year_low == null ? undefined : `${faPercent(s.above_year_low, 0)} بالاتر از آن`
          }
        />
      </dl>

      <div className="ix-returns" data-testid="index-returns">
        {s.returns.map((r) => (
          <div key={r.label} className="ix-ret">
            <span className="text-xs text-muted">{r.label}</span>
            <b className={`num ${signTone(r.value)}`}>
              {r.value == null ? "—" : faPercent(r.value, 1, true)}
            </b>
          </div>
        ))}
        {last && (
          <div className="ix-ret">
            <span className="text-xs text-muted">میانهٔ سهم‌ها امروز</span>
            <b className={`num ${signTone(last.median_change)}`}>
              {last.median_change == null ? "—" : faPercent(last.median_change, 1, true)}
            </b>
          </div>
        )}
      </div>

      <div className="min-w-0">
        <CandleChart key={s.key} candles={candles} />
        <p className="mt-2 text-xs leading-6 text-muted">
          سرچشمهٔ شاخص، بورس است و قیمت بازگشایی ندارد؛ بازگشایی هر کندل را برابر پایانی روز پیش
          گذاشته‌ایم (در دامنهٔ همان روز). ستون‌های زیر کندل‌ها ارزش کل معاملات سهام آن روز است.
        </p>
      </div>

      <BreadthHistory days={m.days} />
    </section>
  );
}
