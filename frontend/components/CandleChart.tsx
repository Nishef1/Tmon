"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Time } from "lightweight-charts";
import type { Candle } from "@/lib/api";
import { faPrice, jalali } from "@/lib/format";
import { heikinAshi, sma, type Bar } from "@/lib/indicators";

export type Level = { price: number; title: string; color: string };

function iso(t: Time): string {
  if (typeof t === "string") return t;
  if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
  const mm = String(t.month).padStart(2, "0");
  const dd = String(t.day).padStart(2, "0");
  return `${t.year}-${mm}-${dd}`;
}

const NO_LEVELS: Level[] = [];

export function CandleChart({
  candles,
  levels = NO_LEVELS,
}: {
  candles: Candle[];
  levels?: Level[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [ha, setHa] = useState(true);
  const [ma20, setMa20] = useState(true);
  const [ma50, setMa50] = useState(false);
  const [hover, setHover] = useState<Bar | null>(null);

  const real = useMemo<Bar[]>(
    () =>
      candles
        .filter((c) => c.open !== null && c.high !== null && c.low !== null && c.close !== null)
        .map((c) => ({
          time: c.date,
          open: c.open as number,
          high: c.high as number,
          low: c.low as number,
          close: c.close as number,
        })),
    [candles],
  );

  useEffect(() => {
    let cancelled = false;
    let dispose = () => {};
    (async () => {
      const lc = await import("lightweight-charts");
      const el = ref.current;
      if (cancelled || !el) return;
      const css = getComputedStyle(document.documentElement);
      const muted = css.getPropertyValue("--muted").trim() || "#625e55";
      const line = css.getPropertyValue("--line").trim() || "#e3ded1";
      const up = css.getPropertyValue("--up").trim() || "#1d6a43";
      const down = css.getPropertyValue("--down").trim() || "#a32d2d";

      const chart = lc.createChart(el, {
        autoSize: true,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: muted,
          fontFamily: "Vazirmatn, sans-serif",
          attributionLogo: false,
        },
        grid: { vertLines: { color: line }, horzLines: { color: line } },
        rightPriceScale: { borderColor: line },
        timeScale: {
          borderColor: line,
          tickMarkFormatter: (t: Time) => jalali(iso(t), "monthDay"),
        },
        localization: {
          timeFormatter: (t: Time) => jalali(iso(t), "short"),
          priceFormatter: (p: number) => faPrice(p),
        },
      });
      const series = chart.addSeries(lc.CandlestickSeries, {
        upColor: up,
        downColor: down,
        wickUpColor: up,
        wickDownColor: down,
        borderVisible: false,
      });
      const shown = ha ? heikinAshi(real) : real;
      series.setData(shown.map((b) => ({ ...b, time: b.time as Time })));
      for (const [on, n, color] of [
        [ma20, 20, "#c98a12"],
        [ma50, 50, "#3f6fb5"],
      ] as const) {
        if (!on) continue;
        const ls = chart.addSeries(lc.LineSeries, {
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        ls.setData(sma(real, n).map((p) => ({ ...p, time: p.time as Time })));
      }
      const byTime = new Map(real.map((b) => [b.time, b]));
      chart.subscribeCrosshairMove((p) => {
        setHover(p.time ? (byTime.get(iso(p.time)) ?? null) : null);
      });
      for (const l of levels) {
        series.createPriceLine({
          price: l.price,
          color: l.color,
          lineWidth: 1,
          lineStyle: lc.LineStyle.Dashed,
          axisLabelVisible: true,
          title: l.title,
        });
      }
      chart.timeScale().fitContent();
      dispose = () => chart.remove();
    })();
    return () => {
      cancelled = true;
      dispose();
    };
  }, [real, levels, ha, ma20, ma50]);

  const last = real[real.length - 1];
  const bar = hover ?? last;
  const btn = (on: boolean) =>
    `rounded-full border px-3 py-1 text-sm ${on ? "border-accent bg-accent-soft font-semibold" : "border-line text-muted"}`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="تنظیم نمودار">
        <button type="button" aria-pressed={ha} onClick={() => setHa(!ha)} className={btn(ha)}>
          شمع هایکن‌آشی
        </button>
        <button
          type="button"
          aria-pressed={ma20}
          onClick={() => setMa20(!ma20)}
          className={btn(ma20)}
        >
          میانگین ۲۰ روزه
        </button>
        <button
          type="button"
          aria-pressed={ma50}
          onClick={() => setMa50(!ma50)}
          className={btn(ma50)}
        >
          میانگین ۵۰ روزه
        </button>
      </div>
      {bar && (
        <p className="text-sm text-muted" data-testid="chart-legend">
          قیمت واقعی {jalali(bar.time, "short")}: باز {faPrice(bar.open)} · بالا {faPrice(bar.high)}{" "}
          · پایین {faPrice(bar.low)} · بسته {faPrice(bar.close)}
        </p>
      )}
      <div
        ref={ref}
        dir="ltr"
        role="img"
        aria-label={ha ? "نمودار شمعی هایکن‌آشی قیمت تعدیل‌شده" : "نمودار شمعی قیمت تعدیل‌شده"}
        className="h-72 w-full sm:h-96"
      />
      <p className="text-xs text-muted">
        {ha
          ? "هایکن‌آشی هر شمع را با شمع قبلی نرم می‌کند تا روند روشن‌تر دیده شود؛ قیمت‌های بالا همان قیمت واقعی همان روزند، نه مقدار شمع نرم‌شده. "
          : ""}
        نمودار: TradingView Lightweight Charts.
      </p>
    </div>
  );
}
