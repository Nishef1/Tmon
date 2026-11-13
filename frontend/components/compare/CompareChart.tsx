"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Time } from "lightweight-charts";
import { faNumber, faPercent, jalali } from "@/lib/format";

export type Line = { id: number; symbol: string; closes: { date: string; close: number }[] };

import { COLORS } from "./colors";
const SPANS: [string, number | null][] = [
  ["۳ ماه", 63],
  ["۶ ماه", 126],
  ["۱ سال", 250],
  ["۳ سال", 750],
  ["همه", null],
];

/** The symbols' adjusted closes rebased to 100 on the first day all of them traded in the span,
 *  so a reader sees who gained more from the same starting day. */
export function CompareChart({ lines }: { lines: Line[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [span, setSpan] = useState<number | null>(250);
  const [hover, setHover] = useState<{ date: string; v: (number | null)[] } | null>(null);

  const data = useMemo(() => {
    // days every symbol traded on, oldest first, cut to the span
    const sets = lines.map((l) => new Map(l.closes.map((c) => [c.date, c.close])));
    const days = [...(sets[0]?.keys() ?? [])].filter((d) => sets.every((m) => m.has(d))).sort();
    const cut = span == null ? days : days.slice(-span);
    return {
      days: cut,
      series: sets.map((m) => {
        const first = cut.length ? m.get(cut[0])! : 1;
        return cut.map((d) => ({ time: d, value: (100 * m.get(d)!) / first }));
      }),
    };
  }, [lines, span]);

  useEffect(() => {
    let cancelled = false;
    let dispose = () => {};
    (async () => {
      const lc = await import("lightweight-charts");
      const el = ref.current;
      if (cancelled || !el || data.days.length < 2) return;
      const css = getComputedStyle(document.documentElement);
      const tok = (c: string) => {
        const m = /^var\((--[\w-]+)\)$/.exec(c);
        return m ? css.getPropertyValue(m[1]).trim() : c;
      };
      const chart = lc.createChart(el, {
        autoSize: true,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: tok("var(--muted)"),
          fontFamily: "Vazirmatn, sans-serif",
          fontSize: 11,
          attributionLogo: false,
        },
        grid: { vertLines: { visible: false }, horzLines: { color: tok("var(--line-soft)") } },
        rightPriceScale: { borderVisible: false, mode: lc.PriceScaleMode.Normal },
        timeScale: { borderVisible: false },
        crosshair: { mode: lc.CrosshairMode.Normal },
      });
      const made = data.series.map((pts, i) => {
        const s = chart.addSeries(lc.LineSeries, {
          color: tok(COLORS[i % COLORS.length]),
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: lines[i].symbol,
        });
        s.setData(pts.map((p) => ({ time: p.time as Time, value: p.value })));
        return s;
      });
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((p) => {
        if (!p.time) return setHover(null);
        setHover({
          date: String(p.time),
          v: made.map((s) => {
            const x = p.seriesData.get(s) as { value?: number } | undefined;
            return x?.value ?? null;
          }),
        });
      });
      dispose = () => chart.remove();
    })();
    return () => {
      cancelled = true;
      dispose();
    };
  }, [data, lines]);

  const last = data.series.map((s) => (s.length ? s[s.length - 1].value : null));
  const shown = hover?.v ?? last;
  return (
    <div className="space-y-2" data-testid="compare-chart">
      <div className="chart-bar" role="toolbar" aria-label="بازهٔ نمودار مقایسه">
        <div className="seg" role="group" aria-label="بازه">
          {SPANS.map(([t, n]) => (
            <button key={t} type="button" aria-pressed={span === n} onClick={() => setSpan(n)}>
              {t}
            </button>
          ))}
        </div>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm" data-testid="compare-legend">
        {lines.map((l, i) => (
          <li key={l.id} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: COLORS[i % COLORS.length] }}
              aria-hidden
            />
            <b>{l.symbol}</b>
            <span className={(shown[i] ?? 100) >= 100 ? "text-up" : "text-down"}>
              {shown[i] == null ? "—" : faPercent(shown[i]! / 100 - 1, 1, true)}
            </span>
          </li>
        ))}
        {data.days.length > 0 && (
          <li className="text-xs text-muted">
            از {jalali(data.days[0], "short")} · {faNumber(data.days.length)} روز معاملهٔ مشترک
          </li>
        )}
      </ul>
      {data.days.length < 2 ? (
        <p className="text-sm text-muted">این نمادها روز معاملهٔ مشترک کافی ندارند.</p>
      ) : (
        <div ref={ref} className="h-80 w-full" dir="ltr" />
      )}
    </div>
  );
}
