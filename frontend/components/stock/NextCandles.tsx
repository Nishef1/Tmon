"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Candle, DashEntry, SymbolForecast } from "@/lib/api";
import { faDigits, faNumber, faPrice, jalali } from "@/lib/format";
import { signedPct } from "@/lib/ui";
import { PERIOD_KEYS, PERIOD_SHORT } from "@/components/stock/outlook";

/** One forecast point: the median close ``days`` trading days after today and the low and high of
 *  the range 8 in 10 past outcomes fell in. Fractions of today's price. */
type Row = {
  key: string;
  label: string;
  /** the short label under the time axis */
  axis: string;
  days: number;
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

/** Trading days the fan shows unless a longer period is chosen. */
const SPAN = 20;

const per100 = (x: number) => faNumber(Math.round(x * 100));
const per10 = (x: number) => faNumber(Math.round(x * 10));
const afterCandles = (h: number) => (h === 1 ? "کندل بعد" : `${faNumber(h)} کندل بعد`);
const pctText = (x: number) => faDigits(`${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}٪`);

function simRows(f: SymbolForecast, hrefs: Record<string, string>): Row[] {
  return PERIOD_KEYS.flatMap((k) => {
    const x = f.horizons.find((h) => h.key === k);
    if (!x) return [];
    return [
      {
        key: k,
        label: PERIOD_SHORT[k] ?? x.label,
        axis: PERIOD_SHORT[k] ?? x.label,
        days: x.days,
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
            axis: `${faNumber(x.h)} روز`,
            days: x.h,
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

/** Rounded so the server and the browser draw the same coordinates. */
const r2 = (v: number) => Math.round(v * 100) / 100;

/** The last real closes as a line, then from today a fan out to ``span`` trading days: the median
 *  line and the band 8 in 10 past outcomes fell in. Longer periods stay in the chips above. */
function Plot({
  rows,
  price,
  recent,
  span,
  active,
  onPick,
  onHover,
}: {
  rows: Row[];
  price: number;
  recent: Candle[];
  span: number;
  active: number;
  onPick: (i: number) => void;
  onHover: (i: number | null) => void;
}) {
  const W = 820;
  const H = 320;
  const P = { t: 18, b: 58, l: 10, r: 76 };
  const past = recent.filter((c) => c.close != null).map((c) => c.close as number);
  const xToday = P.l + (W - P.l - P.r) * (past.length > 1 ? 0.4 : 0.04);
  const xEnd = W - P.r - 14;
  const X = (d: number) =>
    r2(
      d <= 0
        ? xToday + (d * (xToday - P.l - 4)) / Math.max(past.length - 1, 1)
        : xToday + (d * (xEnd - xToday)) / span,
    );
  const shown = rows.map((r, i) => ({ ...r, i })).filter((r) => r.days <= span);
  const prices = [
    ...past,
    ...shown.flatMap((r) => [price * (1 + r.low), price * (1 + r.high)]),
    price,
  ];
  // a log axis: a rise and a fall of the same size look the same
  const lo = Math.min(...prices) * 0.985;
  const hi = Math.max(...prices) * 1.015;
  const L = (v: number) => Math.log(Math.max(v, 1e-9));
  const Y = (v: number) => r2(P.t + ((H - P.t - P.b) * (L(hi) - L(v))) / (L(hi) - L(lo) || 1));
  const at = (q: number) => Y(price * (1 + q));
  const yToday = Y(price);
  const pts = [{ key: "today", days: 0, low: 0, mid: 0, high: 0, reliable: true }, ...shown];
  const segs = pts.slice(1).map((b, k) => ({ a: pts[k], b }));
  const pastPath = past
    .map((v, i) => `${i === 0 ? "M" : "L"}${X(i - (past.length - 1))},${Y(v)}`)
    .join("");
  const sel = shown.find((r) => r.i === active);
  // a period label that would touch the one before it (or «امروز») is left out
  const labelled = new Set<number>();
  let lastX = xToday;
  for (const r of shown) {
    if (X(r.days) - lastX >= 40) {
      labelled.add(r.i);
      lastX = X(r.days);
    }
  }
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full select-none"
      style={{ direction: "ltr" }}
      role="img"
      aria-label="قیمت روزهای گذشته و از امروز به بعد خط میانه و بازهٔ پیش‌بینی"
      onMouseLeave={() => onHover(null)}
    >
      <defs>
        <linearGradient id="nc-past" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--ink)" stopOpacity="0.09" />
          <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
        </linearGradient>
        <linearGradient
          id="nc-band"
          gradientUnits="userSpaceOnUse"
          x1={xToday}
          x2={xEnd}
          y1="0"
          y2="0"
        >
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.32" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0.14" />
        </linearGradient>
      </defs>
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
      {past.length > 1 && (
        <>
          <path
            d={`${pastPath}L${X(0)},${H - P.b}L${X(1 - past.length)},${H - P.b}Z`}
            fill="url(#nc-past)"
          />
          <path
            d={pastPath}
            fill="none"
            stroke="var(--ink)"
            strokeOpacity="0.75"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <text
            x={(P.l + xToday) / 2}
            y={H - P.b + 18}
            fontSize="11"
            textAnchor="middle"
            fill="var(--muted)"
            style={{ direction: "rtl" }}
          >
            {`${faNumber(past.length)} روز گذشته`}
          </text>
        </>
      )}
      {/* today's price carried forward: a median above it gains, one below it loses */}
      <line
        x1={xToday}
        x2={W - P.r}
        y1={yToday}
        y2={yToday}
        stroke="var(--ink)"
        strokeOpacity="0.35"
        strokeDasharray="4 4"
      />
      <path
        d={`${pts.map((p, k) => `${k === 0 ? "M" : "L"}${X(p.days)},${at(p.high)}`).join("")}${[
          ...pts,
        ]
          .reverse()
          .map((p) => `L${X(p.days)},${at(p.low)}`)
          .join("")}Z`}
        fill="url(#nc-band)"
      />
      {(["high", "low"] as const).map((edge) => (
        <path
          key={edge}
          d={pts.map((p, k) => `${k === 0 ? "M" : "L"}${X(p.days)},${at(p[edge])}`).join("")}
          fill="none"
          stroke="var(--accent)"
          strokeOpacity="0.45"
          strokeWidth="1"
          strokeLinejoin="round"
        />
      ))}
      {segs.map(({ a, b }) => (
        <line
          key={`mid-${b.key}`}
          x1={X(a.days)}
          y1={at(a.mid)}
          x2={X(b.days)}
          y2={at(b.mid)}
          stroke="var(--accent)"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeDasharray={b.reliable ? undefined : "5 4"}
        />
      ))}
      <line
        x1={xToday}
        x2={xToday}
        y1={P.t - 8}
        y2={H - P.b + 4}
        stroke="var(--line-strong)"
        strokeDasharray="2 4"
      />
      <text
        x={xToday}
        y={H - P.b + 18}
        fontSize="11"
        fontWeight="700"
        textAnchor="middle"
        fill="var(--ink)"
      >
        امروز
      </text>
      <circle cx={xToday} cy={yToday} r="4" fill="var(--ink)" />
      {sel && (
        <g pointerEvents="none">
          <line
            x1={X(sel.days)}
            x2={X(sel.days)}
            y1={at(sel.high)}
            y2={at(sel.low)}
            stroke="var(--accent)"
            strokeWidth="1.5"
          />
          {(
            [
              ["high", -4, "var(--up)"],
              ["mid", 4, "var(--ink)"],
              ["low", 13, "var(--down)"],
            ] as const
          ).map(([q, dy, fill]) => {
            const right = X(sel.days) < xEnd - 80;
            return (
              <text
                key={q}
                x={X(sel.days) + (right ? 10 : -10)}
                y={Math.min(H - P.b - 4, Math.max(P.t + 2, at(sel[q]) + dy))}
                fontSize="11"
                fontWeight={q === "mid" ? 800 : 600}
                textAnchor={right ? "start" : "end"}
                fill={fill}
                paintOrder="stroke"
                stroke="var(--surface)"
                strokeWidth="4"
                strokeLinejoin="round"
              >
                {faPrice(price * (1 + sel[q]))}
              </text>
            );
          })}
        </g>
      )}
      {shown.map((r, k) => {
        const up = r.mid >= 0;
        const col = up ? "var(--up)" : "var(--down)";
        const x = X(r.days);
        const prev = k === 0 ? xToday : X(shown[k - 1].days);
        const next = k === shown.length - 1 ? W - P.r : X(shown[k + 1].days);
        const isSel = r.i === active;
        return (
          <g
            key={r.key}
            className="cursor-pointer"
            onClick={() => onPick(r.i)}
            onMouseEnter={() => onHover(r.i)}
            data-testid={`nc-point-${r.key}`}
            data-up={up ? "1" : "0"}
          >
            <title>
              {`${r.label}: ${faPrice(price * (1 + r.low))} تا ${faPrice(price * (1 + r.high))}، میانه ${faPrice(price * (1 + r.mid))}`}
            </title>
            <rect
              x={(prev + x) / 2}
              y={P.t - 8}
              width={(next - prev) / 2}
              height={H - P.t + 8}
              fill="transparent"
            />
            <circle
              cx={x}
              cy={at(r.mid)}
              r={isSel ? 6 : 4.5}
              fill={isSel ? col : "var(--surface)"}
              stroke={col}
              strokeWidth="2.2"
            />
            {labelled.has(r.i) && (
              <>
                <text
                  x={x}
                  y={H - P.b + 18}
                  fontSize="11.5"
                  fontWeight={isSel ? 800 : 600}
                  textAnchor="middle"
                  fill={isSel ? "var(--accent)" : "var(--ink)"}
                  style={{ direction: "rtl" }}
                >
                  {r.axis}
                </text>
                <text
                  x={x}
                  y={H - P.b + 34}
                  fontSize="11.5"
                  fontWeight="700"
                  textAnchor="middle"
                  fill={col}
                  style={{ direction: "ltr", unicodeBidi: "plaintext" }}
                >
                  {pctText(r.mid)}
                </text>
              </>
            )}
          </g>
        );
      })}
      <rect x={W - P.r + 2} y={yToday - 10} width={P.r - 4} height="20" rx="6" fill="var(--ink)" />
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
    </svg>
  );
}

/** «کندل‌های بعد»: where the price may close after each period, drawn as a fan of median and range
 *  that continues the real closes. Two sources: the tested simulation of the portfolio forecast (1 day to 6 months) and
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
  // the fan stops at SPAN days; picking a longer period stretches it to that period
  const [long, setLong] = useState(false);
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
  const span = long ? Math.max(SPAN, rows[chosen]?.days ?? SPAN) : SPAN;
  const at = (q: number) => faPrice(price * (1 + q));

  const pick = (i: number) => {
    setLong(rows[i].days > SPAN);
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
            خط تیره قیمت پایانی روزهای گذشته است. از امروز به بعد، خط پررنگ میانه است و نوار دورش
            بازه‌ای که ۸ بار از ۱۰ قیمت پایانی داخلش ماند. نقطهٔ سبز یعنی میانه بالاتر از امروز است.
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

      <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="بازهٔ پیش‌بینی">
        {rows.map((r, i) => (
          <button
            key={r.key}
            type="button"
            onClick={() => pick(i)}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            aria-pressed={i === chosen}
            className="tab tab-pill tab-sm gap-1.5"
            data-testid={`nc-chip-${r.key}`}
          >
            {r.label}
            <span
              className={`text-[11px] font-bold tabular-nums ${i === chosen ? "opacity-90" : r.mid >= 0 ? "text-up" : "text-down"}`}
              dir="ltr"
            >
              {pctText(r.mid)}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-2">
        <Plot
          rows={rows}
          price={price}
          recent={recent}
          span={span}
          active={chosen}
          onPick={pick}
          onHover={setHover}
        />
        {rows.some((r) => !r.reliable) && (
          <p className="mt-1 text-[11px] text-muted">
            {sim
              ? "خط‌چین: این بازه روی دوره‌های جدای کافی آزموده نیست."
              : "خط‌چین: کمتر از ۳۰ آزمون جدا دارد، پس آزموده نیست."}
          </p>
        )}
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
