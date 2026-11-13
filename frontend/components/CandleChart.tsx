"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi, ISeriesApi, LogicalRange, SeriesType, Time } from "lightweight-charts";
import type { Candle } from "@/lib/api";
import { faNumber, faPercent, faPrice, jalali } from "@/lib/format";
import Link from "next/link";
import {
  adx,
  atrPct,
  bollinger,
  ema,
  heikinAshi,
  ichimoku,
  levels as taLevels,
  macd,
  measure,
  mfi,
  obv,
  obvCapped,
  fvgZones,
  elliottLabels,
  regime,
  rsi,
  sma,
  stochastic,
  vwap,
  type Bar,
  type Point,
  type Series,
  type VBar,
} from "@/lib/indicators";

export type Level = { price: number; title: string; color: string };
/** A candle to point at under or over the price, e.g. a day an entry rule fired. */
export type Mark = {
  time: string;
  text: string;
  color: string;
  above?: boolean;
  shape?: "circle" | "arrowUp" | "arrowDown";
};

type Kind = "candle" | "ha" | "bar" | "line";
type Pane = "none" | "rsi" | "macd" | "stoch" | "mfi" | "adx" | "atr" | "obv";
type Overlay = "ma1" | "ma2" | "ma3" | "ema" | "bb" | "ichi" | "vwap" | "lv" | "reg" | "fvg" | "ew";

/** Every user setting of the chart; kept in this browser only. */
type Cfg = {
  kind: Kind;
  log: boolean;
  vol: boolean;
  magnet: boolean;
  on: Overlay[];
  pane: Pane;
  ma1: number;
  ma2: number;
  ma3: number;
  emaF: number;
  emaS: number;
  bbN: number;
  bbK: number;
  vwapN: number;
  rsiN: number;
  macdF: number;
  macdS: number;
  macdG: number;
  stochN: number;
  stochD: number;
  mfiN: number;
  adxN: number;
  atrN: number;
};

const DEFAULT: Cfg = {
  kind: "ha",
  log: false,
  vol: true,
  magnet: true,
  on: ["ma1", "reg"],
  pane: "none",
  ma1: 20,
  ma2: 50,
  ma3: 200,
  emaF: 12,
  emaS: 26,
  bbN: 20,
  bbK: 2,
  vwapN: 20,
  rsiN: 14,
  macdF: 12,
  macdS: 26,
  macdG: 9,
  stochN: 14,
  stochD: 3,
  mfiN: 14,
  adxN: 14,
  atrN: 14,
};
const STORE = "tmon.chart.v2";

/** Bounds of every number field: [min, max, step]. */
const BOUNDS: Partial<Record<keyof Cfg, [number, number, number]>> = {
  ma1: [2, 400, 1],
  ma2: [2, 400, 1],
  ma3: [2, 400, 1],
  emaF: [2, 200, 1],
  emaS: [2, 200, 1],
  bbN: [5, 200, 1],
  bbK: [0.5, 4, 0.5],
  vwapN: [2, 200, 1],
  rsiN: [2, 100, 1],
  macdF: [2, 100, 1],
  macdS: [3, 200, 1],
  macdG: [2, 50, 1],
  stochN: [3, 100, 1],
  stochD: [1, 20, 1],
  mfiN: [2, 100, 1],
  adxN: [2, 100, 1],
  atrN: [2, 100, 1],
};

function loadCfg(): Cfg {
  try {
    const raw = window.localStorage.getItem(STORE);
    if (!raw) return DEFAULT;
    const v = JSON.parse(raw) as Partial<Cfg>;
    const out: Cfg = { ...DEFAULT };
    for (const [k, b] of Object.entries(BOUNDS) as [keyof Cfg, [number, number, number]][]) {
      const x = v[k];
      if (typeof x === "number" && x >= b[0] && x <= b[1]) (out[k] as number) = x;
    }
    if (v.kind && KINDS.some(([k]) => k === v.kind)) out.kind = v.kind;
    if (v.pane && PANES.some(([k]) => k === v.pane)) out.pane = v.pane;
    if (Array.isArray(v.on)) out.on = v.on.filter((k) => OVER_KEYS.includes(k));
    for (const k of FLAGS) if (typeof v[k] === "boolean") out[k] = v[k];
    return out;
  } catch {
    return DEFAULT;
  }
}

function saveCfg(c: Cfg) {
  try {
    window.localStorage.setItem(STORE, JSON.stringify(c));
  } catch {
    // private mode or storage blocked: the settings just do not survive a reload
  }
}

const fa = (n: number) => faNumber(n);

/** Lines drawn on the price: key, label, colour token, glossary term. */
const overlays = (c: Cfg): [Overlay, string, string, string][] => [
  ["ma1", `میانگین ${fa(c.ma1)}`, "var(--series-1)", "sma"],
  ["ma2", `میانگین ${fa(c.ma2)}`, "var(--series-2)", "sma"],
  ["ma3", `میانگین ${fa(c.ma3)}`, "var(--series-3)", "sma"],
  ["ema", `EMA ${fa(c.emaF)} و ${fa(c.emaS)}`, "var(--series-4)", "ema"],
  ["bb", "باند بولینگر", "var(--muted)", "bollinger"],
  ["ichi", "ایچیموکو", "var(--series-3)", "ichimoku"],
  ["vwap", `VWAP ${fa(c.vwapN)} روزه`, "var(--accent)", "vwap"],
  ["lv", "حمایت، مقاومت، پیوت و فیبو", "var(--ref)", "support_resistance"],
  ["fvg", "FVG و iFVG", "var(--series-4)", "fvg"],
  ["ew", "امواج الیوت", "var(--series-3)", "elliott"],
  ["reg", "رنگ روند (صعودی، نزولی، خنثی)", "var(--hold)", "sma"],
];
const OVER_KEYS: Overlay[] = [
  "ma1",
  "ma2",
  "ma3",
  "ema",
  "bb",
  "ichi",
  "vwap",
  "lv",
  "reg",
  "fvg",
  "ew",
];

/** One indicator at a time in a pane under the price. */
const PANES: [Pane, string, string][] = [
  ["none", "بدون", ""],
  ["rsi", "RSI", "rsi"],
  ["macd", "MACD", "macd"],
  ["stoch", "استوکاستیک", "stochastic"],
  ["mfi", "MFI", "mfi"],
  ["adx", "ADX", "adx"],
  ["atr", "ATR٪", "atr"],
  ["obv", "OBV", "obv"],
];

const paneNote = (c: Cfg): Record<Pane, string> => ({
  none: "",
  rsi: `RSI ${fa(c.rsiN)} روزه. خط‌چین‌ها ۳۰ و ۷۰اند: زیر ۳۰ را «اشباع فروش» و بالای ۷۰ را «اشباع خرید» می‌خوانند.`,
  macd: `خط مکدی (EMA${fa(c.macdF)} − EMA${fa(c.macdS)})، خط سیگنال (EMA${fa(c.macdG)} مکدی) و ستون‌ها فاصلهٔ آن دو.`,
  stoch: `%K ${fa(c.stochN)} روزه و %D (میانگین ${fa(c.stochD)} روزهٔ آن)؛ زیر ۲۰ اشباع فروش و بالای ۸۰ اشباع خرید.`,
  mfi: `MFI ${fa(c.mfiN)} روزه، RSI با وزن حجم؛ زیر ۲۰ اشباع فروش و بالای ۸۰ اشباع خرید.`,
  adx: `ADX ${fa(c.adxN)} روزه قدرت روند است (بالای ۲۵ روند دار)؛ +DI و −DI جهت آن را نشان می‌دهند.`,
  atr: `میانگین دامنهٔ واقعی ${fa(c.atrN)} روزه به درصد قیمت: اندازهٔ نوسان عادی یک روز.`,
  obv: "حجم روزهای مثبت جمع و روزهای منفی کم می‌شود؛ جهت خط مهم است نه عدد آن.",
});

// the on/off switches kept in the saved settings
const FLAGS = "log magnet vol".split(" ") as ("log" | "magnet" | "vol")[];

const KINDS: [Kind, string][] = [
  ["candle", "شمع ژاپنی"],
  ["ha", "شمع هایکن‌آشی"],
  ["bar", "میله‌ای"],
  ["line", "خطی"],
];

function iso(t: Time): string {
  if (typeof t === "string") return t;
  if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
  const mm = String(t.month).padStart(2, "0");
  const dd = String(t.day).padStart(2, "0");
  return `${t.year}-${mm}-${dd}`;
}

const NO_LEVELS: Level[] = [];
const NO_MARKS: Mark[] = [];

const SPANS: [number, string][] = [
  [22, "۱ ماه"],
  [66, "۳ ماه"],
  [132, "۶ ماه"],
  [250, "۱ سال"],
  [0, "همه"],
];

/** `#rrggbb` + alpha for the volume bars; any other colour string is used as is. */
const faded = (hex: string, a = "99") => (/^#[0-9a-f]{6}$/i.test(hex) ? `${hex}${a}` : hex);

type Geom = { x1: number; y1: number; x2: number; y2: number; w: number };
/** A line in the hover legend: its name, colour and value at the hovered candle. */
type LegendItem = { label: string; color: string; value: number | null; pct?: boolean };
type Tracked = { label: string; color: string; series: ISeriesApi<SeriesType>; pct?: boolean };

export function CandleChart({
  candles,
  levels = NO_LEVELS,
  marks = NO_MARKS,
}: {
  candles: Candle[];
  levels?: Level[];
  marks?: Mark[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const [cfg, setCfgState] = useState<Cfg>(DEFAULT);
  const [span, setSpan] = useState(0);
  const [panel, setPanel] = useState(false);
  const [full, setFull] = useState(false);
  const [hover, setHover] = useState<Bar | null>(null);
  const [vals, setVals] = useState<LegendItem[]>([]);
  // percent ruler: click a start point, move, click the end point; a third click starts over
  const [ruler, setRuler] = useState(false);
  const [a, setA] = useState<Point | null>(null);
  const [b, setB] = useState<Point | null>(null);
  const [live, setLive] = useState<Point | null>(null);
  const [geom, setGeom] = useState<Geom | null>(null);
  const rulerOn = useRef(false);
  const aRef = useRef<Point | null>(null);
  const bRef = useRef<Point | null>(null);
  const chartApi = useRef<{ chart: IChartApi; series: ISeriesApi<SeriesType> } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  // the view survives a rebuild of the chart (a toggle or a new period), so a zoom is kept
  const view = useRef<{ range: LogicalRange | null; n: number; paneH: number | null }>({
    range: null,
    n: 0,
    paneH: null,
  });

  useEffect(() => {
    // read after mount so the server render and the first client render agree
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCfgState(loadCfg());
  }, []);

  const setCfg = useCallback((patch: Partial<Cfg>) => {
    setCfgState((c) => {
      const next = { ...c, ...patch };
      saveCfg(next);
      return next;
    });
  }, []);

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
  const vbars = useMemo<VBar[]>(
    () => real.map((x) => ({ ...x, volume: volumes.get(x.time) ?? null })),
    [real, volumes],
  );
  const prevClose = useMemo(
    () => new Map(real.map((x, i) => [x.time, i > 0 ? real[i - 1].close : null])),
    [real],
  );

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
    const onFs = () => setFull(document.fullscreenElement === shell.current);
    window.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onFs);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFs);
    };
  }, []);

  const applySpan = useCallback(
    (chart: IChartApi, n: number) => {
      if (n > 0 && real.length > n) {
        chart.timeScale().setVisibleLogicalRange({ from: real.length - n, to: real.length + 2 });
      } else {
        chart.timeScale().fitContent();
      }
    },
    [real.length],
  );

  useEffect(() => {
    let cancelled = false;
    let dispose = () => {};
    (async () => {
      const lc = await import("lightweight-charts");
      const el = ref.current;
      if (cancelled || !el) return;
      const css = getComputedStyle(document.documentElement);
      // every colour comes from the CSS tokens; "var(--x)" strings are resolved here
      const tok = (c: string) => {
        const m = /^var\((--[\w-]+)\)$/.exec(c);
        return m ? css.getPropertyValue(m[1]).trim() : c;
      };
      const muted = tok("var(--muted)");
      const line = tok("var(--line-soft)");
      const strong = tok("var(--line-strong)");
      const up = tok("var(--up)");
      const down = tok("var(--down)");
      const accent = tok("var(--accent)");
      const tracked: Tracked[] = [];

      const chart = lc.createChart(el, {
        autoSize: true,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: muted,
          fontFamily: "Vazirmatn, sans-serif",
          fontSize: 11,
          attributionLogo: false,
          panes: { separatorColor: strong, separatorHoverColor: faded(accent, "33") },
        },
        grid: { vertLines: { visible: false }, horzLines: { color: line } },
        crosshair: {
          mode: cfg.magnet ? lc.CrosshairMode.MagnetOHLC : lc.CrosshairMode.Normal,
          vertLine: { color: strong, labelBackgroundColor: accent, style: lc.LineStyle.Dashed },
          horzLine: { color: strong, labelBackgroundColor: accent, style: lc.LineStyle.Dashed },
        },
        rightPriceScale: {
          borderVisible: false,
          mode: cfg.log ? lc.PriceScaleMode.Logarithmic : lc.PriceScaleMode.Normal,
        },
        timeScale: {
          borderVisible: false,
          rightOffset: 4,
          tickMarkFormatter: (t: Time) => jalali(iso(t), "monthDay"),
        },
        localization: {
          timeFormatter: (t: Time) => jalali(iso(t), "short"),
          priceFormatter: (p: number) => faPrice(p),
        },
      });
      const shown = cfg.kind === "ha" ? heikinAshi(real) : real;
      const ohlc = shown.map((x) => ({ ...x, time: x.time as Time }));
      let series: ISeriesApi<SeriesType>;
      if (cfg.kind === "line") {
        series = chart.addSeries(lc.AreaSeries, {
          lineColor: accent,
          topColor: faded(accent, "33"),
          bottomColor: faded(accent, "00"),
          lineWidth: 2,
        });
        series.setData(real.map((x) => ({ time: x.time as Time, value: x.close })));
      } else if (cfg.kind === "bar") {
        series = chart.addSeries(lc.BarSeries, { upColor: up, downColor: down, thinBars: false });
        series.setData(ohlc);
      } else {
        series = chart.addSeries(lc.CandlestickSeries, {
          upColor: up,
          downColor: down,
          wickUpColor: up,
          wickDownColor: down,
          borderVisible: false,
        });
        series.setData(ohlc);
      }
      if (cfg.vol) {
        series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
        const hist = chart.addSeries(lc.HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "vol",
          priceLineVisible: false,
          lastValueVisible: false,
        });
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        hist.setData(
          real.flatMap((x) => {
            const v = volumes.get(x.time);
            return v == null
              ? []
              : [
                  {
                    time: x.time as Time,
                    value: v,
                    color: faded(x.close >= x.open ? up : down, "55"),
                  },
                ];
          }),
        );
      } else {
        series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.06 } });
      }
      const addLine = (
        data: Series,
        color: string,
        label: string | null,
        at = 0,
        style: number = lc.LineStyle.Solid,
        width: 1 | 2 = 1,
        pct = false,
      ) => {
        const s = chart.addSeries(
          lc.LineSeries,
          {
            color: tok(color),
            lineWidth: width,
            lineStyle: style,
            priceLineVisible: false,
            lastValueVisible: at > 0,
            crosshairMarkerVisible: false,
          },
          at,
        );
        s.setData(data.map((p) => ({ ...p, time: p.time as Time })));
        if (label) tracked.push({ label, color: tok(color), series: s, pct });
        return s;
      };
      const { Dashed, Dotted, Solid } = lc.LineStyle;
      const on = new Set(cfg.on);
      if (on.has("ma1"))
        addLine(sma(real, cfg.ma1), "var(--series-1)", `MA${fa(cfg.ma1)}`, 0, Solid, 2);
      if (on.has("ma2"))
        addLine(sma(real, cfg.ma2), "var(--series-2)", `MA${fa(cfg.ma2)}`, 0, Solid, 2);
      if (on.has("ma3"))
        addLine(sma(real, cfg.ma3), "var(--series-3)", `MA${fa(cfg.ma3)}`, 0, Solid, 2);
      if (on.has("ema")) {
        addLine(ema(real, cfg.emaF), "var(--series-4)", `EMA${fa(cfg.emaF)}`);
        addLine(ema(real, cfg.emaS), "var(--series-3)", `EMA${fa(cfg.emaS)}`, 0, Dashed);
      }
      if (on.has("bb")) {
        const bb = bollinger(real, cfg.bbN, cfg.bbK);
        addLine(bb.up, "var(--muted)", "BB↑", 0, Dashed);
        addLine(bb.mid, "var(--muted)", null, 0, Dotted);
        addLine(bb.dn, "var(--muted)", "BB↓", 0, Dashed);
      }
      if (on.has("ichi")) {
        const ic = ichimoku(real);
        addLine(ic.tenkan, "var(--series-4)", "تنکان");
        addLine(ic.kijun, "var(--series-3)", "کیجون");
        addLine(ic.spanA, "var(--up)", null, 0, Dotted);
        addLine(ic.spanB, "var(--down)", null, 0, Dotted);
      }
      if (on.has("vwap")) addLine(vwap(vbars, cfg.vwapN), "var(--accent)", "VWAP", 0, Solid, 2);
      if (on.has("reg")) {
        const bg = chart.addSeries(lc.HistogramSeries, {
          priceScaleId: "reg",
          priceLineVisible: false,
          lastValueVisible: false,
          base: 0,
        });
        chart.priceScale("reg").applyOptions({
          visible: false,
          scaleMargins: { top: 0, bottom: 0 },
        });
        bg.setData(
          regime(real).map((x) => ({
            time: x.time as Time,
            value: 1,
            color: faded(x.value > 0 ? up : x.value < 0 ? down : muted, "14"),
          })),
        );
      }
      if (on.has("fvg")) {
        for (const z of fvgZones(real)) {
          const c = tok(z.side === "bull" ? "var(--up)" : "var(--down)");
          const name = z.inverted
            ? z.side === "bull"
              ? "iFVG↓"
              : "iFVG↑"
            : z.side === "bull"
              ? "FVG↑"
              : "FVG↓";
          for (const price of [z.top, z.bot])
            series.createPriceLine({
              price,
              color: faded(c, "aa"),
              lineWidth: 1,
              lineStyle: z.inverted ? Dotted : lc.LineStyle.Dashed,
              axisLabelVisible: false,
              title: price === z.top ? name : "",
            });
        }
      }
      if (on.has("lv")) {
        for (const l of taLevels(real)) {
          series.createPriceLine({
            price: l.price,
            color: muted,
            lineWidth: 1,
            lineStyle: Dotted,
            axisLabelVisible: true,
            title: l.title,
          });
        }
      }
      // the lower pane, with the textbook reference lines
      const refs = (s: ISeriesApi<"Line">, at: number[]) => {
        for (const price of at) {
          s.createPriceLine({ price, color: muted, lineWidth: 1, lineStyle: Dashed, title: "" });
        }
      };
      const p = cfg.pane;
      if (p === "rsi")
        refs(addLine(rsi(real, cfg.rsiN), "var(--series-2)", "RSI", 1, Solid, 2), [30, 70]);
      if (p === "macd") {
        const m = macd(real, cfg.macdF, cfg.macdS, cfg.macdG);
        const h = chart.addSeries(
          lc.HistogramSeries,
          { priceLineVisible: false, lastValueVisible: false },
          1,
        );
        h.setData(
          m.hist.map((q) => ({
            ...q,
            time: q.time as Time,
            color: faded(q.value >= 0 ? up : down),
          })),
        );
        addLine(m.macd, "var(--series-2)", "MACD", 1, Solid, 2);
        addLine(m.signal, "var(--series-1)", "سیگنال", 1);
      }
      if (p === "stoch") {
        const s = stochastic(real, cfg.stochN, cfg.stochD);
        refs(addLine(s.k, "var(--series-2)", "%K", 1, Solid, 2), [20, 80]);
        addLine(s.d, "var(--series-1)", "%D", 1);
      }
      if (p === "mfi")
        refs(addLine(mfi(vbars, cfg.mfiN), "var(--series-2)", "MFI", 1, Solid, 2), [20, 80]);
      if (p === "adx") {
        const d = adx(real, cfg.adxN);
        refs(addLine(d.adx, "var(--ink)", "ADX", 1, Solid, 2), [25]);
        addLine(d.pdi, "var(--up)", "+DI", 1);
        addLine(d.mdi, "var(--down)", "−DI", 1);
      }
      if (p === "atr") {
        addLine(
          atrPct(real, cfg.atrN).map((q) => ({ ...q, value: 100 * q.value })),
          "var(--series-2)",
          "ATR٪",
          1,
          Solid,
          2,
        );
      }
      if (p === "obv") {
        addLine(obvCapped(vbars), "var(--series-2)", "OBV", 1, Solid, 2);
        addLine(obv(vbars), "var(--muted)", "OBV خام", 1, lc.LineStyle.Dotted, 1);
      }
      if (p !== "none") chart.panes()[1]?.setHeight(view.current.paneH ?? 140);

      // Elliott: a faint dot at the turn, and the wave number on the day the 10% turn made it
      // known (that is when it could have been used; drawn at the turn it looks too perfect)
      const waves: Mark[] = on.has("ew")
        ? elliottLabels(real).flatMap((w) => [
            {
              time: w.time,
              text: "",
              color: "var(--muted)",
              above: w.top,
              shape: "circle" as const,
            },
            {
              time: w.known,
              text: `${w.text} معلوم شد`,
              color: "var(--series-3)",
              above: !w.top,
              shape: "circle" as const,
            },
          ])
        : [];
      const allMarks = [...marks, ...waves];
      if (allMarks.length > 0) {
        const known = new Set(times);
        lc.createSeriesMarkers(
          series,
          allMarks
            .filter((m) => known.has(m.time))
            .sort((x, y) => (x.time < y.time ? -1 : 1))
            .map((m) => ({
              time: m.time as Time,
              position: m.above ? ("aboveBar" as const) : ("belowBar" as const),
              shape: m.shape ?? (m.above ? ("arrowDown" as const) : ("arrowUp" as const)),
              color: tok(m.color),
              text: m.text,
            })),
        );
      }

      const byTime = new Map(real.map((x) => [x.time, x]));
      const legendAt = (time: Time | undefined, data?: Map<unknown, unknown>) =>
        tracked.map((t) => {
          let v: number | null = null;
          if (time && data) {
            const d = data.get(t.series) as { value?: number } | undefined;
            v = d?.value ?? null;
          } else {
            const all = t.series.data();
            const lastPt = all[all.length - 1] as { value?: number } | undefined;
            v = lastPt?.value ?? null;
          }
          return { label: t.label, color: t.color, value: v, pct: t.pct };
        });
      setVals(legendAt(undefined));
      chart.subscribeCrosshairMove((q) => {
        setHover(q.time ? (byTime.get(iso(q.time)) ?? null) : null);
        setVals(legendAt(q.time, q.time ? (q.seriesData as Map<unknown, unknown>) : undefined));
        if (rulerOn.current && aRef.current && !bRef.current && q.time && q.point) {
          const price = series.coordinateToPrice(q.point.y);
          setLive(price == null ? null : { time: iso(q.time), price });
        }
      });
      chart.subscribeClick((q) => {
        if (!rulerOn.current || !q.time || !q.point) return;
        const price = series.coordinateToPrice(q.point.y);
        if (price == null) return;
        const pt = { time: iso(q.time), price };
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
          color: tok(l.color),
          lineWidth: 1,
          lineStyle: lc.LineStyle.Dashed,
          axisLabelVisible: true,
          title: l.title,
        });
      }
      const v = view.current;
      if (v.range && v.n === real.length) chart.timeScale().setVisibleLogicalRange(v.range);
      else applySpan(chart, span);
      v.n = real.length;
      const mark = (r: LogicalRange | null) => {
        view.current.range = r;
        // the visible span, for tests and for anyone inspecting the page
        if (box.current && r)
          box.current.dataset.view = `${Math.round(r.from)}:${Math.round(r.to)}`;
      };
      mark(chart.timeScale().getVisibleLogicalRange());
      chart.timeScale().subscribeVisibleLogicalRangeChange(mark);
      dispose = () => {
        view.current.range = chart.timeScale().getVisibleLogicalRange();
        const p1 = chart.panes()[1];
        if (p1) view.current.paneH = p1.getHeight();
        chartApi.current = null;
        chart.remove();
      };
    })();
    return () => {
      cancelled = true;
      dispose();
    };
    // `span` is applied by its own effect; a rebuild keeps the user's zoom instead
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, levels, marks, volumes, vbars, times, cfg, applySpan]);

  const pickSpan = (n: number) => {
    setSpan(n);
    const api = chartApi.current;
    if (api) applySpan(api.chart, n);
  };

  /** Move the price up or down by a tenth of the visible range (drag the price axis to zoom). */
  const nudge = (dir: 1 | -1) => {
    const api = chartApi.current;
    const r = api?.chart.priceScale("right").getVisibleRange();
    if (!api || !r) return;
    const d = ((r.to - r.from) / 10) * dir;
    api.chart.priceScale("right").setVisibleRange({ from: r.from + d, to: r.to + d });
  };

  const resetView = () => {
    const api = chartApi.current;
    if (!api) return;
    api.chart.priceScale("right").applyOptions({ autoScale: true });
    applySpan(api.chart, span);
  };

  const toggleFull = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await shell.current?.requestFullscreen();
    } catch {
      // fullscreen refused (iframe or browser policy): the chart stays in the page
    }
  };

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
  const pc = bar ? prevClose.get(bar.time) : null;
  const chg = bar && pc ? bar.close / pc - 1 : null;
  const OV = overlays(cfg);
  const on = new Set(cfg.on);
  const toggle = (k: Overlay) =>
    setCfg({ on: on.has(k) ? cfg.on.filter((x) => x !== k) : [...cfg.on, k] });
  const height = full
    ? "h-[calc(100dvh-11rem)]"
    : cfg.pane === "none"
      ? "h-80 sm:h-[28rem]"
      : "h-[28rem] sm:h-[34rem]";

  return (
    <div className="space-y-2">
      <div ref={shell} className="chart-shell" data-testid="chart-shell">
        <div className="chart-bar" role="group" aria-label="تنظیم نمودار">
          <span className="seg" role="group" aria-label="نوع نمودار">
            {KINDS.map(([k, label]) => (
              <button
                key={k}
                type="button"
                aria-pressed={cfg.kind === k}
                // the Heikin-Ashi button also switches back to real candles
                onClick={() => setCfg({ kind: k === "ha" && cfg.kind === "ha" ? "candle" : k })}
              >
                {label}
              </button>
            ))}
          </span>
          <span className="seg" role="group" aria-label="نمایش">
            <button type="button" aria-pressed={cfg.vol} onClick={() => setCfg({ vol: !cfg.vol })}>
              حجم
            </button>
            <button
              type="button"
              aria-pressed={cfg.log}
              onClick={() => setCfg({ log: !cfg.log })}
              title="مقیاس لگاریتمی: فاصلهٔ برابر یعنی درصد تغییر برابر"
            >
              لگاریتمی
            </button>
            <button
              type="button"
              aria-pressed={cfg.magnet}
              onClick={() => setCfg({ magnet: !cfg.magnet })}
              title="نشانگر به باز، بالا، پایین یا بستهٔ نزدیک‌ترین شمع می‌چسبد"
            >
              آهنربا
            </button>
            <button
              type="button"
              aria-pressed={ruler}
              onClick={() => {
                setRuler(!ruler);
                setLive(null);
              }}
              title="روی نمودار دو نقطه را انتخاب کنید تا درصد تغییر بین آن‌ها نشان داده شود"
            >
              خط‌کش درصدی
            </button>
          </span>
          {(a || b) && (
            <button
              type="button"
              onClick={() => {
                setA(null);
                setB(null);
                setLive(null);
              }}
              className="tab tab-sm"
            >
              پاک کردن خط‌کش
            </button>
          )}
          <span className="ms-auto flex flex-wrap items-center gap-2">
            <span className="seg" role="group" aria-label="بازهٔ زمانی">
              {SPANS.map(([n, label]) => (
                <button key={n} type="button" aria-pressed={span === n} onClick={() => pickSpan(n)}>
                  {label}
                </button>
              ))}
            </span>
            <span className="seg" role="group" aria-label="ابزار">
              <button type="button" onClick={resetView} title="بازگرداندن بزرگنمایی و مقیاس">
                بازنشانی نما
              </button>
              <button
                type="button"
                onClick={() => nudge(-1)}
                title="نمودار کمی بالاتر"
                aria-label="نمودار بالاتر"
              >
                ▲
              </button>
              <button
                type="button"
                onClick={() => nudge(1)}
                title="نمودار کمی پایین‌تر"
                aria-label="نمودار پایین‌تر"
              >
                ▼
              </button>
              <button type="button" aria-pressed={panel} onClick={() => setPanel(!panel)}>
                پارامترها
              </button>
              <button type="button" aria-pressed={full} onClick={toggleFull}>
                {full ? "خروج از تمام‌صفحه" : "تمام‌صفحه"}
              </button>
            </span>
          </span>
        </div>
        <div className="chart-bar" role="group" aria-label="خط‌های روی قیمت">
          <span className="text-xs text-muted">روی قیمت:</span>
          {OV.map(([k, label, color]) => (
            <button
              key={k}
              type="button"
              aria-pressed={on.has(k)}
              onClick={() => toggle(k)}
              className="ind"
              style={{ "--sw": color } as React.CSSProperties}
            >
              <span className="sw" aria-hidden />
              {label}
            </button>
          ))}
        </div>
        <div className="chart-bar" role="group" aria-label="اندیکاتور زیر نمودار">
          <span className="text-xs text-muted">زیر نمودار:</span>
          <span className="seg">
            {PANES.map(([k, label]) => (
              <button
                key={k}
                type="button"
                aria-pressed={cfg.pane === k}
                onClick={() => setCfg({ pane: k })}
              >
                {label}
              </button>
            ))}
          </span>
        </div>
        {panel && <Params cfg={cfg} set={setCfg} />}
        <div ref={box} className="relative" dir="ltr">
          {bar && (
            <div className="chart-legend" dir="rtl" data-testid="chart-legend">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-bold text-ink">{jalali(bar.time, "short")}</span>
                <span className="text-muted">قیمت واقعی</span>
                <span>باز {faPrice(bar.open)}</span>
                <span>بالا {faPrice(bar.high)}</span>
                <span>پایین {faPrice(bar.low)}</span>
                <span className="font-bold">بسته {faPrice(bar.close)}</span>
                {chg != null && (
                  <bdi dir="ltr" className={chg >= 0 ? "font-bold text-up" : "font-bold text-down"}>
                    {faPercent(chg, 2, true)}
                  </bdi>
                )}
                {volumes.get(bar.time) != null && (
                  <span className="text-muted">
                    حجم {faNumber(volumes.get(bar.time) as number)}
                  </span>
                )}
              </div>
              {vals.length > 0 && (
                <div className="flex flex-wrap gap-x-3" data-testid="chart-values">
                  {vals.map((v) => (
                    <span key={v.label} style={{ color: v.color }}>
                      {v.label}{" "}
                      <bdi dir="ltr">
                        {v.value == null
                          ? "—"
                          : Math.abs(v.value) >= 1000
                            ? faPrice(v.value)
                            : faNumber(Math.round(v.value * 100) / 100)}
                      </bdi>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
          <div
            ref={ref}
            role="img"
            aria-label={
              cfg.kind === "ha" ? "نمودار شمعی هایکن‌آشی قیمت تعدیل‌شده" : "نمودار قیمت تعدیل‌شده"
            }
            className={`w-full ${height} ${ruler ? "cursor-crosshair" : ""}`}
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
                className={`pointer-events-none absolute z-10 flex -translate-x-1/2 items-baseline whitespace-nowrap text-sm font-bold float-tag ${
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
      {(cfg.on.length > 0 || cfg.pane !== "none") && (
        <p className="text-xs text-muted" data-testid="chart-terms">
          {cfg.pane !== "none" && `${paneNote(cfg)[cfg.pane]} `}
          معنی و آزمون هر کدام در واژه‌نامه:{" "}
          {[
            ...OV.filter(([k]) => on.has(k)).map(([k, label, , term]) => [k, label, term] as const),
            ...PANES.filter(([k]) => k === cfg.pane && k !== "none"),
          ].map(([k, label, term], i) => (
            <span key={k}>
              {i > 0 && "، "}
              <Link href={`/glossary/${term}`} className="underline hover:text-accent">
                {label}
              </Link>
            </span>
          ))}
        </p>
      )}
      <p className="text-xs text-muted">
        {cfg.kind === "ha"
          ? "هایکن‌آشی هر شمع را با شمع قبلی نرم می‌کند تا روند روشن‌تر دیده شود؛ قیمت‌های بالای نمودار همان قیمت واقعی همان روزند، نه مقدار شمع نرم‌شده. "
          : ""}
        با چرخ موس یا دو انگشت بزرگنمایی کنید و با کشیدن جابه‌جا شوید؛ با روشن و خاموش کردن خط‌ها
        بزرگنمایی می‌ماند. تنظیم‌ها فقط در همین مرورگر نگه داشته می‌شوند. نمودار: TradingView
        Lightweight Charts.
      </p>
    </div>
  );
}

/** Number fields for every period of the chart, grouped by what they draw. */
function Params({ cfg, set }: { cfg: Cfg; set: (p: Partial<Cfg>) => void }) {
  const field = (k: keyof Cfg, label: string) => {
    const [lo, hi, step] = BOUNDS[k] ?? [1, 100, 1];
    return (
      <label className="flex items-center gap-1.5 text-xs text-muted">
        {label}
        <input
          type="number"
          inputMode="decimal"
          className="num-in"
          dir="ltr"
          min={lo}
          max={hi}
          step={step}
          value={cfg[k] as number}
          aria-label={label}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (Number.isFinite(v) && v >= lo && v <= hi) set({ [k]: v } as Partial<Cfg>);
          }}
        />
      </label>
    );
  };
  const group = (title: string, children: React.ReactNode) => (
    <fieldset className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <legend className="mb-1 text-xs font-bold">{title}</legend>
      {children}
    </fieldset>
  );
  return (
    <div
      className="grid gap-3 border-b border-line-soft bg-surface-2 px-3 py-3 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="chart-params"
    >
      {group(
        "میانگین‌ها",
        <>
          {field("ma1", "میانگین ۱")}
          {field("ma2", "میانگین ۲")}
          {field("ma3", "میانگین ۳")}
          {field("emaF", "EMA تند")}
          {field("emaS", "EMA کند")}
        </>,
      )}
      {group(
        "باند و VWAP",
        <>
          {field("bbN", "بولینگر روز")}
          {field("bbK", "ضریب انحراف")}
          {field("vwapN", "VWAP روز")}
        </>,
      )}
      {group(
        "نوسانگرها",
        <>
          {field("rsiN", "RSI")}
          {field("stochN", "استوکاستیک")}
          {field("stochD", "%D")}
          {field("mfiN", "MFI")}
        </>,
      )}
      {group(
        "MACD",
        <>
          {field("macdF", "تند")}
          {field("macdS", "کند")}
          {field("macdG", "سیگنال")}
        </>,
      )}
      {group(
        "روند و نوسان",
        <>
          {field("adxN", "ADX")}
          {field("atrN", "ATR")}
        </>,
      )}
      <div className="flex items-end">
        <button
          type="button"
          className="tab tab-sm"
          onClick={() => set({ ...DEFAULT, kind: cfg.kind, on: cfg.on, pane: cfg.pane })}
        >
          بازگشت به عددهای کتابی
        </button>
      </div>
    </div>
  );
}
