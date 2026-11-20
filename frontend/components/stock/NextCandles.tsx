"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Candle, DashEntry, SymbolForecast } from "@/lib/api";
import { faDigits, faNumber, faPrice, jalali } from "@/lib/format";
import { signedPct } from "@/lib/ui";
import { PERIOD_KEYS, PERIOD_SHORT } from "@/components/stock/outlook";

/** One forecast candle: it opens at today's price and closes at the median, its wicks reach the
 *  low and high of the range 8 in 10 past outcomes fell in. Fractions of today's price. */
type Row = {
  key: string;
  label: string;
  low: number;
  mid: number;
  high: number;
  /** the plain direction count: paths with a gain, or past days that closed higher */
  dir: string;
  /** how the range was tested, or that it was not */
  tested: string;
  reliable: boolean;
  href?: string;
};

type Source = "sim" | "own";

const per100 = (x: number) => faNumber(Math.round(x * 100));
const per10 = (x: number) => faNumber(Math.round(x * 10));
const afterCandles = (h: number) => (h === 1 ? "کندل بعد" : `${faNumber(h)} کندل بعد`);

function simRows(f: SymbolForecast, hrefs: Record<string, string>): Row[] {
  return PERIOD_KEYS.flatMap((k) => {
    const x = f.horizons.find((h) => h.key === k);
    if (!x) return [];
    return [
      {
        key: k,
        label: PERIOD_SHORT[k] ?? x.label,
        low: x.low,
        mid: x.mid,
        high: x.high,
        dir: `${per100(x.p_gain_net)} مسیر از ۱۰۰ با سود بعد از کارمزد`,
        tested: x.reliable
          ? `روی ${faNumber(x.windows)} دورهٔ جدا آزموده شد${
              x.coverage80 != null ? `؛ بازهٔ خام ${per100(x.coverage80)} از ۱۰۰ را پوشاند` : ""
            }${x.calibrated ? " و اصلاح شد" : ""}`
          : `آزموده نیست (فقط ${faNumber(x.windows)} دورهٔ جدا)`,
        reliable: x.reliable,
        href: hrefs[k],
      },
    ];
  });
}

function ownRows(w: DashEntry["windows"][number]): Row[] {
  return w.odds.flatMap((x) =>
    x.q10 == null || x.q50 == null || x.q90 == null
      ? []
      : [
          {
            key: `h${x.h}`,
            label: afterCandles(x.h),
            low: x.q10,
            mid: x.q50,
            high: x.q90,
            dir: `${per10(x.up)} بار از ۱۰ بالاتر بسته شد${
              x.up_all != null ? ` (همهٔ سهم‌ها در همان روزها ${per10(x.up_all)} از ۱۰)` : ""
            }`,
            tested: `${faNumber(x.n)} روز، ${faNumber(x.eff || x.n)} آزمون جدا`,
            reliable: (x.eff || x.n) >= 30,
          },
        ],
  );
}

/** Rounded steps for the price axis. */
function ticks(lo: number, hi: number, n = 5): number[] {
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

/** The last real candles, then one forecast candle per period, on one price axis. */
function Plot({
  rows,
  price,
  recent,
  active,
  onPick,
  onHover,
}: {
  rows: Row[];
  price: number;
  recent: Candle[];
  active: number;
  onPick: (i: number) => void;
  onHover: (i: number | null) => void;
}) {
  const W = 820;
  const H = 330;
  const P = { t: 16, b: 64, l: 10, r: 76 };
  const past = recent.filter(
    (c) => c.open != null && c.high != null && c.low != null && c.close != null,
  );
  const split = P.l + (W - P.l - P.r) * (past.length > 0 ? 0.36 : 0);
  const prices = [
    ...past.flatMap((c) => [c.high as number, c.low as number]),
    ...rows.flatMap((r) => [price * (1 + r.low), price * (1 + r.high)]),
    price,
  ];
  // a log axis: a rise and a fall of the same size look the same, and the long periods' wide
  // ranges do not flatten the recent candles
  const lo = Math.min(...prices) * 0.97;
  const hi = Math.max(...prices) * 1.03;
  const L = (v: number) => Math.log(Math.max(v, 1e-9));
  // rounded: Math.log may differ in the last digits between the server and the browser
  const Y = (v: number) =>
    Math.round((P.t + ((H - P.t - P.b) * (L(hi) - L(v))) / (L(hi) - L(lo) || 1)) * 100) / 100;
  const pw = past.length > 0 ? (split - P.l) / past.length : 0;
  const slot = (W - P.r - split - 8) / Math.max(rows.length, 1);
  const cx = (i: number) => split + 8 + slot * (i + 0.5);
  const bw = Math.min(34, slot * 0.38);
  const yToday = Y(price);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full select-none"
      style={{ direction: "ltr" }}
      role="img"
      aria-label="کندل‌های گذشته و کندل پیش‌بینی هر بازه"
      onMouseLeave={() => onHover(null)}
    >
      <defs>
        <linearGradient id="nc-future" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.07" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0.01" />
        </linearGradient>
      </defs>
      <rect
        x={split}
        y={P.t - 6}
        width={W - P.r - split}
        height={H - P.t - P.b + 12}
        rx="10"
        fill="url(#nc-future)"
      />
      {ticks(lo, hi, 6)
        .filter((v, i, all) => i === 0 || Y(all[i - 1]) - Y(v) > 22)
        .map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} stroke="var(--line-soft)" />
            <text x={W - P.r + 8} y={Y(v) + 4} fontSize="11" fill="var(--muted)">
              {faPrice(v)}
            </text>
          </g>
        ))}
      {past.map((c, i) => {
        const up = (c.close as number) >= (c.open as number);
        const col = up ? "var(--up)" : "var(--down)";
        const x = P.l + pw * (i + 0.5);
        const top = Y(Math.max(c.open as number, c.close as number));
        const bot = Y(Math.min(c.open as number, c.close as number));
        return (
          <g key={c.date} opacity="0.55">
            <line x1={x} x2={x} y1={Y(c.high as number)} y2={Y(c.low as number)} stroke={col} />
            <rect
              x={x - Math.max(1, pw * 0.32)}
              y={top}
              width={Math.max(2, pw * 0.64)}
              height={Math.max(1, bot - top)}
              fill={col}
            />
          </g>
        );
      })}
      {past.length > 0 && (
        <>
          <line
            x1={split}
            x2={split}
            y1={P.t - 6}
            y2={H - P.b + 6}
            stroke="var(--line-strong)"
            strokeDasharray="2 4"
          />
          <text
            x={(P.l + split) / 2}
            y={H - P.b + 20}
            fontSize="11"
            textAnchor="middle"
            fill="var(--muted)"
            style={{ direction: "rtl" }}
          >
            {`${faNumber(past.length)} روز گذشته`}
          </text>
        </>
      )}
      <line
        x1={split}
        x2={W - P.r}
        y1={yToday}
        y2={yToday}
        stroke="var(--ink)"
        strokeOpacity="0.45"
        strokeDasharray="5 4"
      />
      <g>
        <rect
          x={W - P.r + 2}
          y={yToday - 10}
          width={P.r - 4}
          height="20"
          rx="6"
          fill="var(--ink)"
        />
        <text
          x={W - P.r + P.r / 2}
          y={yToday + 4}
          fontSize="11"
          fontWeight="700"
          textAnchor="middle"
          fill="var(--surface)"
        >
          {faPrice(price)}
        </text>
      </g>
      {rows.map((r, i) => {
        const up = r.mid >= 0;
        const col = up ? "var(--up)" : "var(--down)";
        const soft = up ? "var(--up-soft)" : "var(--down-soft)";
        const x = cx(i);
        const close = Y(price * (1 + r.mid));
        const sel = i === active;
        return (
          <g
            key={r.key}
            className="cursor-pointer"
            onClick={() => onPick(i)}
            onMouseEnter={() => onHover(i)}
            data-testid={`nc-candle-${r.key}`}
            data-up={up ? "1" : "0"}
          >
            <title>
              {`${r.label}: ${faPrice(price * (1 + r.low))} تا ${faPrice(price * (1 + r.high))}، میانه ${faPrice(price * (1 + r.mid))}`}
            </title>
            <rect
              x={x - slot / 2 + 3}
              y={P.t - 6}
              width={slot - 6}
              height={H - P.t - 6}
              rx="10"
              fill={sel ? "var(--accent-soft)" : "transparent"}
              stroke={sel ? "var(--accent)" : "none"}
              strokeOpacity="0.35"
            />
            <line
              x1={x}
              x2={x}
              y1={Y(price * (1 + r.high))}
              y2={Y(price * (1 + r.low))}
              stroke={col}
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={r.reliable ? undefined : "4 3"}
            />
            {[r.high, r.low].map((q) => (
              <line
                key={q}
                x1={x - 6}
                x2={x + 6}
                y1={Y(price * (1 + q))}
                y2={Y(price * (1 + q))}
                stroke={col}
                strokeWidth="2"
                strokeLinecap="round"
              />
            ))}
            <rect
              x={x - bw / 2}
              y={Math.min(yToday, close)}
              width={bw}
              height={Math.max(3, Math.abs(close - yToday))}
              rx="3"
              fill={sel ? col : soft}
              stroke={col}
              strokeWidth="1.5"
              strokeDasharray={r.reliable ? undefined : "4 3"}
            />
            <text
              x={x}
              y={H - P.b + 20}
              fontSize="12"
              fontWeight="700"
              textAnchor="middle"
              fill="var(--ink)"
              style={{ direction: "rtl" }}
            >
              {r.label}
            </text>
            <text
              x={x}
              y={H - P.b + 38}
              fontSize="12"
              fontWeight="700"
              textAnchor="middle"
              fill={col}
              style={{ direction: "ltr", unicodeBidi: "plaintext" }}
            >
              {`${up ? "▲" : "▼"} ${faDigits(`${r.mid >= 0 ? "+" : "−"}${Math.abs(r.mid * 100).toFixed(1)}٪`)}`}
            </text>
            {!r.reliable && (
              <text
                x={x}
                y={H - P.b + 54}
                fontSize="10"
                textAnchor="middle"
                fill="var(--muted)"
                style={{ direction: "rtl" }}
              >
                آزموده نیست
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** «کندل‌های بعد»: where the price may close after each period, drawn as candles that continue the
 *  real ones. Two sources: the tested simulation of the portfolio forecast (1 day to 6 months) and
 *  the symbol's own record after any day of a chosen past window. Past statistics, not advice. */
export function NextCandles({
  f,
  entry,
  recent,
  period,
  hrefs,
}: {
  f: SymbolForecast | null;
  entry: DashEntry | null;
  recent: Candle[];
  /** the period chosen on the page (?p=), highlighted in the simulation */
  period?: string;
  hrefs: Record<string, string>;
}) {
  const router = useRouter();
  const windows = (entry?.windows ?? []).filter((w) => w.odds.some((x) => x.q50 != null));
  const [source, setSource] = useState<Source>(f?.price ? "sim" : "own");
  const [winKey, setWinKey] = useState(
    windows.find((w) => w.key === "year")?.key ?? windows[0]?.key ?? "",
  );
  const [hover, setHover] = useState<number | null>(null);
  const [ownPick, setOwnPick] = useState(0);
  const win = windows.find((w) => w.key === winKey) ?? windows[0];

  const sim = source === "sim" && f?.price != null;
  const price = sim ? (f?.price as number) : (entry?.own_close ?? null);
  const rows = sim && f ? simRows(f, hrefs) : win ? ownRows(win) : [];
  if (price == null || rows.length === 0) return null;
  const chosen = sim
    ? Math.max(
        0,
        rows.findIndex((r) => r.key === period),
      )
    : ownPick;
  const shown = rows[hover ?? chosen];
  const at = (q: number) => faPrice(price * (1 + q));

  const pick = (i: number) => {
    if (sim) {
      const h = rows[i].href;
      if (h) router.push(h, { scroll: false });
    } else setOwnPick(i);
  };

  return (
    <section
      className="card min-w-0 scroll-mt-28"
      id="forecast"
      data-testid="next-candles"
      data-source={source}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold">پیش‌بینی کندل‌های بعد</h2>
          <p className="mt-0.5 text-xs text-muted">
            هر کندل از قیمت امروز باز می‌شود و روی میانه بسته می‌شود؛ سایه‌ها کف و سقف بازه‌ای‌اند
            که ۸ بار از ۱۰ قیمت پایانی داخلش ماند. سبز یعنی میانه بالاتر از امروز است.
          </p>
        </div>
        {f?.price != null && windows.length > 0 && (
          <span className="seg" role="group" aria-label="منبع پیش‌بینی">
            <button
              type="button"
              aria-pressed={sim}
              onClick={() => setSource("sim")}
              data-testid="nc-sim"
            >
              شبیه‌سازی آزموده
            </button>
            <button
              type="button"
              aria-pressed={!sim}
              onClick={() => setSource("own")}
              data-testid="nc-own"
            >
              سابقهٔ خود سهم
            </button>
          </span>
        )}
      </div>

      {!sim && windows.length > 1 && (
        <div
          className="mt-3 flex flex-wrap items-center gap-2"
          role="group"
          aria-label="بازهٔ سابقه"
        >
          <span className="text-xs text-muted">سابقهٔ کدام بازه؟</span>
          {windows.map((w) => (
            <button
              key={w.key}
              type="button"
              onClick={() => {
                setWinKey(w.key);
                setOwnPick(0);
              }}
              aria-pressed={w.key === win?.key}
              className="tab tab-pill tab-sm"
            >
              {w.label}
            </button>
          ))}
        </div>
      )}

      {shown && (
        <div
          className="mt-3 grid gap-2 rounded-xl border border-line-soft bg-surface-2 p-3 text-sm sm:grid-cols-[auto_1fr] sm:items-center sm:gap-x-5"
          data-testid="nc-summary"
          aria-live="polite"
        >
          <div className="flex items-baseline gap-2">
            <span className="text-xs text-muted">{shown.label}</span>
            <b className={`text-xl tabular-nums ${shown.mid >= 0 ? "text-up" : "text-down"}`}>
              {at(shown.mid)}
            </b>
            <span className={`text-sm font-bold ${shown.mid >= 0 ? "text-up" : "text-down"}`}>
              {signedPct(shown.mid)}
            </span>
          </div>
          <div className="text-xs leading-6 text-muted">
            ۸ بار از ۱۰ بین <b className="text-down tabular-nums">{at(shown.low)}</b> و{" "}
            <b className="text-up tabular-nums">{at(shown.high)}</b> ریال · {shown.dir} ·{" "}
            {shown.tested}
          </div>
        </div>
      )}

      <div className="mt-2">
        <Plot
          rows={rows}
          price={price}
          recent={recent}
          active={chosen}
          onPick={pick}
          onHover={setHover}
        />
      </div>

      <details className="mt-2 text-sm">
        <summary className="cursor-pointer select-none text-xs font-semibold text-accent">
          جدول همهٔ بازه‌ها
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm" data-testid="nc-table">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-1 text-start font-normal">چه زمانی</th>
                <th className="py-1 text-start font-normal">۸ بار از ۱۰ بین</th>
                <th className="py-1 text-start font-normal">میانه</th>
                <th className="py-1 text-start font-normal">جهت</th>
                <th className="py-1 text-start font-normal">آزمون</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-line-soft last:border-0">
                  <td className="py-1.5 font-bold">{r.label}</td>
                  <td className="py-1.5 tabular-nums">
                    <span className="text-down">{at(r.low)}</span> تا{" "}
                    <span className="text-up">{at(r.high)}</span>
                  </td>
                  <td className={`py-1.5 tabular-nums ${r.mid >= 0 ? "text-up" : "text-down"}`}>
                    {at(r.mid)} ({signedPct(r.mid)})
                  </td>
                  <td className="py-1.5 text-xs">{r.dir}</td>
                  <td className="py-1.5 text-xs text-muted">{r.tested}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <p className="mt-2 text-xs leading-6 text-muted">
        {sim
          ? "شبیه‌سازی از حرکت‌های گذشتهٔ همین سهم با نوسان امروز ساخته شده و هر بازه روی دوره‌های جدای گذشته آزموده شده است؛ شمار مسیرهای سوددار خودش آزموده نیست."
          : `از ${win ? jalali(win.since) : ""} تا امروز، پس از هر روز معاملهٔ همین سهم.`}{" "}
        بازه فقط قیمت روز آخر را می‌گوید، نه کف و سقف میان راه. بیشتر دادهٔ بازار از یک دورهٔ صعودی
        است. این آمار گذشته است، نه تضمین و نه توصیه.
      </p>
    </section>
  );
}
