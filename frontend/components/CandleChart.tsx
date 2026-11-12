"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import type { Candle } from "@/lib/api";
import { faNumber, faPercent, faPrice, jalali } from "@/lib/format";
import { heikinAshi, measure, sma, type Bar, type Point } from "@/lib/indicators";

export type Level = { price: number; title: string; color: string };

function iso(t: Time): string {
  if (typeof t === "string") return t;
  if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
  const mm = String(t.month).padStart(2, "0");
  const dd = String(t.day).padStart(2, "0");
  return `${t.year}-${mm}-${dd}`;
}

const NO_LEVELS: Level[] = [];

const SPANS: [number, string][] = [
  [22, "۱ ماه"],
  [66, "۳ ماه"],
  [132, "۶ ماه"],
  [250, "۱ سال"],
  [0, "همه"],
];

/** `#rrggbb` + alpha for the volume bars; any other colour string is used as is. */
const faded = (hex: string) => (/^#[0-9a-f]{6}$/i.test(hex) ? `${hex}99` : hex);

type Geom = { x1: number; y1: number; x2: number; y2: number; w: number };

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
  const [vol, setVol] = useState(true);
  const [span, setSpan] = useState(0);
  const [hover, setHover] = useState<Bar | null>(null);
  // percent ruler: click a start point, move, click the end point; a third click starts over
  const [ruler, setRuler] = useState(false);
  const [a, setA] = useState<Point | null>(null);
  const [b, setB] = useState<Point | null>(null);
  const [live, setLive] = useState<Point | null>(null);
  const [geom, setGeom] = useState<Geom | null>(null);
  const rulerOn = useRef(false);
  const aRef = useRef<Point | null>(null);
  const bRef = useRef<Point | null>(null);
  const chartApi = useRef<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null>(null);
  const box = useRef<HTMLDivElement>(null);

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

  const volumes = useMemo(() => new Map(candles.map((c) => [c.date, c.volume])), [candles]);
  const times = useMemo(() => real.map((x) => x.time), [real]);

  useEffect(() => {
    rulerOn.current = ruler;
    aRef.current = a;
    bRef.current = b;
  }, [ruler, a, b]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setA(null);
      setB(null);
      setLive(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      if (vol) {
        series.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
        const hist = chart.addSeries(lc.HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "vol",
          priceLineVisible: false,
          lastValueVisible: false,
        });
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
        hist.setData(
          real.flatMap((x) => {
            const v = volumes.get(x.time);
            return v == null
              ? []
              : [{ time: x.time as Time, value: v, color: faded(x.close >= x.open ? up : down) }];
          }),
        );
      }
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
        if (rulerOn.current && aRef.current && !bRef.current && p.time && p.point) {
          const price = series.coordinateToPrice(p.point.y);
          setLive(price == null ? null : { time: iso(p.time), price });
        }
      });
      chart.subscribeClick((p) => {
        if (!rulerOn.current || !p.time || !p.point) return;
        const price = series.coordinateToPrice(p.point.y);
        if (price == null) return;
        const pt = { time: iso(p.time), price };
        if (!aRef.current || bRef.current) {
          setA(pt);
          setB(null);
          setLive(null);
        } else {
          setB(pt);
          setLive(null);
        }
      });
      chartApi.current = { chart, series };
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
      if (span > 0 && real.length > span) {
        chart.timeScale().setVisibleLogicalRange({ from: real.length - span, to: real.length + 1 });
      } else {
        chart.timeScale().fitContent();
      }
      dispose = () => {
        chartApi.current = null;
        chart.remove();
      };
    })();
    return () => {
      cancelled = true;
      dispose();
    };
  }, [real, levels, ha, ma20, ma50, vol, span, volumes]);

  // the ruler is drawn over the chart, so it must follow every zoom, pan and resize
  const end = b ?? live;
  useEffect(() => {
    if (!a || !end) return;
    let frame = 0;
    const tick = () => {
      const api = chartApi.current;
      if (api) {
        const x1 = api.chart.timeScale().timeToCoordinate(a.time as Time);
        const x2 = api.chart.timeScale().timeToCoordinate(end.time as Time);
        const y1 = api.series.priceToCoordinate(a.price);
        const y2 = api.series.priceToCoordinate(end.price);
        const next =
          x1 == null || x2 == null || y1 == null || y2 == null
            ? null
            : { x1, y1, x2, y2, w: box.current?.clientWidth ?? 600 };
        setGeom((cur) =>
          cur &&
          next &&
          Object.entries(next).every(([k, v]) => Math.abs(cur[k as keyof Geom] - v) < 0.5)
            ? cur
            : next,
        );
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [a, end]);

  const m = a && end ? measure(a, end, times) : null;

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
        <button type="button" aria-pressed={vol} onClick={() => setVol(!vol)} className={btn(vol)}>
          حجم
        </button>
        <button
          type="button"
          aria-pressed={ruler}
          onClick={() => {
            setRuler(!ruler);
            setLive(null);
          }}
          className={btn(ruler)}
          title="روی نمودار دو نقطه را انتخاب کنید تا درصد تغییر بین آن‌ها نشان داده شود"
        >
          خط‌کش درصدی
        </button>
        {(a || b) && (
          <button
            type="button"
            onClick={() => {
              setA(null);
              setB(null);
              setLive(null);
            }}
            className={btn(false)}
          >
            پاک کردن خط‌کش
          </button>
        )}
        <span className="ms-auto flex gap-1" role="group" aria-label="بازهٔ زمانی">
          {SPANS.map(([n, label]) => (
            <button
              key={n}
              type="button"
              aria-pressed={span === n}
              onClick={() => setSpan(n)}
              className={btn(span === n)}
            >
              {label}
            </button>
          ))}
        </span>
      </div>
      {bar && (
        <p className="text-sm text-muted" data-testid="chart-legend">
          قیمت واقعی {jalali(bar.time, "short")}: باز {faPrice(bar.open)} · بالا {faPrice(bar.high)}{" "}
          · پایین {faPrice(bar.low)} · بسته {faPrice(bar.close)}
          {volumes.get(bar.time) != null && ` · حجم ${faNumber(volumes.get(bar.time) as number)}`}
        </p>
      )}
      <div ref={box} className="relative" dir="ltr">
        <div
          ref={ref}
          role="img"
          aria-label={ha ? "نمودار شمعی هایکن‌آشی قیمت تعدیل‌شده" : "نمودار شمعی قیمت تعدیل‌شده"}
          className={`h-72 w-full sm:h-96 ${ruler ? "cursor-crosshair" : ""}`}
        />
        {a && end && geom && m && (
          <>
            <svg aria-hidden className="pointer-events-none absolute inset-0 size-full">
              <line
                x1={geom.x1}
                y1={geom.y1}
                x2={geom.x2}
                y2={geom.y2}
                stroke={m.pct >= 0 ? "var(--up)" : "var(--down)"}
                strokeWidth={2}
                strokeDasharray={b ? undefined : "5 4"}
              />
              <circle cx={geom.x1} cy={geom.y1} r={4} fill="var(--ink)" />
              <circle cx={geom.x2} cy={geom.y2} r={4} fill="var(--ink)" />
            </svg>
            <div
              dir="rtl"
              data-testid="ruler-label"
              className={`pointer-events-none absolute z-10 flex -translate-x-1/2 items-baseline whitespace-nowrap rounded-lg border bg-surface px-2 py-1 text-sm font-bold shadow ${
                m.pct >= 0 ? "border-up text-up" : "border-down text-down"
              }`}
              style={{
                left: Math.min(Math.max((geom.x1 + geom.x2) / 2, 70), geom.w - 70),
                top: Math.max(4, Math.min(geom.y1, geom.y2) - 44),
              }}
            >
              <bdi dir="ltr">{faPercent(m.pct, 2, true)}</bdi>
              <span className="ms-3 text-xs font-normal text-muted">
                {faPrice(Math.abs(m.delta))} ریال · {faNumber(Math.abs(m.bars))} کندل ·{" "}
                {faNumber(Math.abs(m.days))} روز
              </span>
            </div>
          </>
        )}
      </div>
      {ruler && (
        <p className="text-xs text-muted" role="status">
          {!a
            ? "خط‌کش روشن است: نقطهٔ شروع را روی نمودار بزنید."
            : !b
              ? "حالا نقطهٔ پایان را بزنید. با Esc پاک می‌شود."
              : "برای اندازهٔ تازه دوباره روی نمودار بزنید. درصد روی مقیاس همین نمودار است."}
        </p>
      )}
      <p className="text-xs text-muted">
        {ha
          ? "هایکن‌آشی هر شمع را با شمع قبلی نرم می‌کند تا روند روشن‌تر دیده شود؛ قیمت‌های بالا همان قیمت واقعی همان روزند، نه مقدار شمع نرم‌شده. "
          : ""}
        نمودار: TradingView Lightweight Charts.
      </p>
    </div>
  );
}
