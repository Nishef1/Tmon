"use client";

import { useEffect, useRef } from "react";
import type { Time } from "lightweight-charts";
import type { Candle } from "@/lib/api";
import { faPrice, jalali } from "@/lib/format";

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
      series.setData(
        candles
          .filter((c) => c.open !== null && c.high !== null && c.low !== null && c.close !== null)
          .map((c) => ({
            time: c.date as Time,
            open: c.open as number,
            high: c.high as number,
            low: c.low as number,
            close: c.close as number,
          })),
      );
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
  }, [candles, levels]);

  return (
    <div
      ref={ref}
      dir="ltr"
      role="img"
      aria-label="نمودار شمعی قیمت تعدیل‌شده"
      className="h-72 w-full sm:h-96"
    />
  );
}
