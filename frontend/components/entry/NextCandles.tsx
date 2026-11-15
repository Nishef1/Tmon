"use client";

import { useState } from "react";
import type { DashEntry } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

type Own = DashEntry["own"][number];

const when = (h: number) => (h === 1 ? "کندل بعد" : `${faNumber(h)} کندل بعد`);

/** Price cone: from today's close, where 8 in 10 of the past outcomes ended after each candle
 *  count (band) and the middle outcome (line). Time runs left to right like the price chart. */
function Cone({ own, close }: { own: Own[]; close: number }) {
  const pts = own.filter((x) => x.q10 != null && x.q90 != null && x.q50 != null);
  if (pts.length < 2) return null;
  const W = 520;
  const H = 150;
  const P = { l: 8, r: 70, t: 10, b: 22 };
  const maxH = Math.max(...pts.map((x) => x.h));
  const lo = Math.min(0, ...pts.map((x) => x.q10!));
  const hi = Math.max(0, ...pts.map((x) => x.q90!));
  const X = (h: number) => P.l + ((W - P.l - P.r) * h) / maxH;
  const Y = (q: number) => P.t + ((H - P.t - P.b) * (hi - q)) / (hi - lo || 1);
  const top = [`${X(0)},${Y(0)}`, ...pts.map((x) => `${X(x.h)},${Y(x.q90!)}`)];
  const bot = [...pts].reverse().map((x) => `${X(x.h)},${Y(x.q10!)}`);
  const mid = [`${X(0)},${Y(0)}`, ...pts.map((x) => `${X(x.h)},${Y(x.q50!)}`)].join(" ");
  const last = pts[pts.length - 1];
  const price = (q: number) => faNumber(Math.round(close * (1 + q)));
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full"
      style={{ direction: "ltr" }}
      role="img"
      aria-label="بازهٔ قیمت در کندل‌های بعد بر پایهٔ سابقهٔ همین سهم"
    >
      <line
        x1={P.l}
        x2={W - P.r}
        y1={Y(0)}
        y2={Y(0)}
        className="stroke-faint"
        strokeDasharray="3 3"
      />
      <polygon points={[...top, ...bot].join(" ")} className="fill-accent/20" />
      <polyline points={mid} fill="none" className="stroke-accent" strokeWidth={2} />
      {pts.map((x) => (
        <g key={x.h}>
          <line
            x1={X(x.h)}
            x2={X(x.h)}
            y1={Y(x.q90!)}
            y2={Y(x.q10!)}
            className="stroke-accent/50"
          />
          <text x={X(x.h)} y={H - 6} textAnchor="middle" className="fill-muted text-[10px]">
            {faNumber(x.h)}
          </text>
        </g>
      ))}
      <text x={X(last.h) + 6} y={Y(last.q90!) + 4} className="fill-up text-[11px]">
        {price(last.q90!)}
      </text>
      <text x={X(last.h) + 6} y={Y(last.q50!) + 4} className="fill-ink text-[11px]">
        {price(last.q50!)}
      </text>
      <text x={X(last.h) + 6} y={Y(last.q10!) + 4} className="fill-down text-[11px]">
        {price(last.q10!)}
      </text>
      <text x={X(0)} y={Y(0) - 4} className="fill-muted text-[10px]">
        {faNumber(Math.round(close))}
      </text>
    </svg>
  );
}

/** The plain answer to "what will the next candles do": for each candle count, the price band
 *  8 in 10 past outcomes fell in and the most likely price, from this symbol's own record.
 *  One percentage per line, nothing compared with anything. */
export function NextCandles({ e }: { e: DashEntry }) {
  const pick = e.windows.find((x) => x.key === "year") ?? e.windows[0];
  const [key, setKey] = useState(pick?.key ?? "");
  const w = e.windows.find((x) => x.key === key) ?? e.windows[0];
  if (!w || w.odds.length === 0) return null;
  const close = e.own_close;
  const own = w.odds.filter((x) => x.q10 != null && x.q90 != null);
  if (close == null || own.length === 0) return null;
  const at = (q: number) => faNumber(Math.round(close * (1 + q)));
  return (
    <div className="space-y-3" data-testid="next-candles" data-window={w.key}>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="بازهٔ سابقه">
        <span className="text-xs text-muted">سابقهٔ کدام بازه؟</span>
        {e.windows.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => setKey(x.key)}
            aria-pressed={x.key === w.key}
            className="tab tab-pill text-xs"
          >
            {x.label}
          </button>
        ))}
      </div>
      <p className="text-sm">
        قیمت امروز <b>{faNumber(Math.round(close))}</b> ریال است. در ۸ مورد از هر ۱۰ مورد گذشته،
        قیمت در این بازه‌ها ماند:
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[22rem] text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="py-1 text-start font-normal">چه زمانی</th>
              <th className="py-1 text-start font-normal">۸ از ۱۰ بار بین</th>
              <th className="py-1 text-start font-normal">مقدار میانه (وسط همهٔ موارد)</th>
            </tr>
          </thead>
          <tbody>
            {own.map((x) => (
              <tr key={x.h} className="border-b border-line last:border-0" data-h={x.h}>
                <td className="py-1.5">{when(x.h)}</td>
                <td className="py-1.5">
                  <b className="text-down">{at(x.q10!)}</b> تا{" "}
                  <b className="text-up">{at(x.q90!)}</b>
                  <span className="ms-2 text-xs text-muted">
                    ({faPercent(x.q10!, 0, true)} تا {faPercent(x.q90!, 0, true)})
                  </span>
                </td>
                <td className="py-1.5">
                  {x.q50 != null ? (
                    <>
                      {at(x.q50)}{" "}
                      <span className="text-xs text-muted">({faPercent(x.q50, 0, true)})</span>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Cone own={own} close={close} />
      <p className="text-xs text-muted">
        بر پایهٔ سابقهٔ همین سهم از {jalali(w.since)} تا امروز: از هر ۱۰ بار، ۸ بار قیمت در این بازه
        مانده است، ۱ بار پایین‌تر رفته و ۱ بار بالاتر. این آمار گذشته است، نه تضمین و نه توصیه.
      </p>
    </div>
  );
}
