import type { ReactNode } from "react";
import type { InstrumentBook, InstrumentDashboard, InstrumentDetail } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import { PortfolioBadge } from "@/components/stock/PortfolioBadge";
import { Sparkline } from "@/components/stock/Sparkline";
import { TradeBadge } from "@/components/TradeBadge";

const QUEUE: Record<string, { text: string; cls: string }> = {
  buy_queue: { text: "صف خرید", cls: "bg-up-soft text-up" },
  sell_queue: { text: "صف فروش", cls: "bg-down-soft text-down" },
};

/** Share counts and volumes in short Persian units. */
function qty(n: number | null | undefined): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${faNumber(n / 1e12, 1)} همت`;
  if (a >= 1e9) return `${faNumber(n / 1e9, 1)} میلیارد`;
  if (a >= 1e6) return `${faNumber(n / 1e6, 1)} میلیون`;
  if (a >= 1e3) return `${faNumber(n / 1e3, 0)} هزار`;
  return faNumber(n);
}

/** Rial -> toman, very short. */
function toman(rial: number | null | undefined): string {
  if (rial == null) return "—";
  const t = Math.abs(rial) / 10;
  const s = rial < 0 ? "−" : "";
  if (t >= 1e12) return `${s}${faNumber(t / 1e12, 1)} همت`;
  if (t >= 1e9) return `${s}${faNumber(t / 1e9, 1)} میلیارد ت`;
  if (t >= 1e6) return `${s}${faNumber(t / 1e6, 1)} میلیون ت`;
  return `${s}${faNumber(t)} ت`;
}

function Tile({
  k,
  children,
  sub,
  tone,
  hint,
}: {
  k: string;
  children: ReactNode;
  sub?: ReactNode;
  tone?: string;
  /** One plain sentence saying what the figure is; shown on hover or long press. */
  hint?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-surface-2 px-3 py-2" title={hint}>
      <dt className="truncate text-xs text-muted">{k}</dt>
      <dd className={`truncate text-base font-bold ${tone ?? ""}`}>{children}</dd>
      {sub != null && <div className="truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

/** A secondary figure: a label and its value on one line. */
function Mini({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-muted">{k}</dt>
      <dd className="font-semibold">{children}</dd>
    </div>
  );
}

/** Where `v` sits between `lo` and `hi`, 0-100 (right edge = low, as the page is RTL). */
function at(v: number | null, lo: number | null, hi: number | null): number | null {
  if (v == null || lo == null || hi == null || hi <= lo) return null;
  return Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
}

function Range({ lo, hi, v }: { lo: number | null; hi: number | null; v: number | null }) {
  const p = at(v, lo, hi);
  if (p == null || lo == null || hi == null) return <>—</>;
  return (
    <span className="block">
      <span className="relative block h-1.5 rounded bg-line">
        <span
          className="absolute top-[-2px] h-2.5 w-2.5 rounded-full bg-accent"
          style={{ right: `calc(${p}% - 5px)` }}
        />
      </span>
      <span className="mt-1 flex justify-between text-xs font-normal text-muted">
        <span>{faNumber(hi)}</span>
        <span>{faNumber(lo)}</span>
      </span>
    </span>
  );
}

/** Everything a visitor needs in the first seconds: the stock, its price and move, today's range,
 *  volume, real-money flow, buyer power and valuation, in one dense block. No dates unless the
 *  data is not from the latest day. */
export function StockHeader({
  d,
  dash,
  book,
}: {
  d: InstrumentDetail;
  dash: InstrumentDashboard | null;
  book: InstrumentBook | null;
}) {
  const p = dash?.price ?? null;
  const f = dash?.flow ?? null;
  const q = dash?.decision.queue_state ? QUEUE[dash.decision.queue_state] : null;
  const fu = dash?.fundamental ?? null;
  const days = [p?.date, f?.date, book?.available ? book.as_of : null]
    .filter((x): x is string => !!x)
    .map((x) => x.slice(0, 10));
  const mixed = new Set(days).size > 1;
  const chips = [dash?.sector_name, dash?.board].filter(Boolean);
  const buyTot =
    f && f.buy_volume_i != null && f.buy_volume_n != null ? f.buy_volume_i + f.buy_volume_n : null;
  const dir = (p?.close_change ?? 0) > 0 ? "up" : (p?.close_change ?? 0) < 0 ? "down" : "flat";
  const realShare = f && buyTot ? (f.buy_volume_i ?? 0) / buyTot : null;
  return (
    <header data-testid="stock-header" data-dir={dir} className="card hero space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="text-2xl font-extrabold">{d.instrument.symbol}</h1>
        {d.instrument.name && (
          <span className="min-w-0 truncate text-sm text-muted">{d.instrument.name}</span>
        )}
        {chips.map((c) => (
          <span key={c} className="chip max-w-48 truncate">
            {c}
          </span>
        ))}
        {dash && (dash.trade_state === "idle" || dash.trade_state === "halted") && (
          <TradeBadge
            state={dash.trade_state}
            idleDays={dash.idle_days}
            lastTrade={dash.last_trade_date ?? undefined}
            long
          />
        )}
        {q && (
          <span className={`chip ${q.cls}`} data-testid="header-queue">
            {q.text}
          </span>
        )}
        <span className="flex flex-wrap gap-1 text-xs sm:ms-auto">
          <PortfolioBadge instrumentId={d.instrument.id} />
        </span>
      </div>

      {p?.close != null && (
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span
              className="text-4xl font-extrabold tracking-tight sm:text-5xl"
              data-testid="header-close"
            >
              {faNumber(p.close)}
            </span>
            {p.close_change != null && (
              <span className={`text-xl font-bold ${signTone(p.close_change)}`}>
                {faPercent(p.close_change, 2, true)}
              </span>
            )}
            <span className="text-xs text-muted">ریال</span>
            {mixed && p.date && (
              <span className="text-xs text-warn" data-testid="header-close-date">
                قیمت پایانی {jalali(p.date, "short")}
              </span>
            )}
          </div>
          <Sparkline candles={d.candles} />
        </div>
      )}

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="stock-stats">
        {p?.low != null && p.high != null && p.high > p.low && (
          <Tile k="بازهٔ امروز">
            <Range lo={p.low ?? null} hi={p.high ?? null} v={p.close ?? null} />
          </Tile>
        )}
        {p && (
          <Tile
            k="حجم معاملات (سهم)"
            sub={
              p.volume_ratio_30 == null ? undefined : `${faNumber(p.volume_ratio_30, 1)}× میانگین`
            }
            tone={p.volume_ratio_30 != null && p.volume_ratio_30 >= 1.5 ? "text-up" : ""}
          >
            {qty(p.volume)}
          </Tile>
        )}
        {f && (
          <Tile
            k="ورود پول حقیقی"
            hint="ارزش خرید حقیقی‌ها منهای ارزش فروش حقیقی‌ها در امروز؛ مثبت یعنی پول حقیقی وارد سهم شده است"
            tone={(f.net_real_value ?? f.net_real_volume ?? 0) >= 0 ? "text-up" : "text-down"}
            sub={realShare == null ? undefined : `${faPercent(realShare, 0)} خرید حقیقی`}
          >
            {f.net_real_value == null && f.net_real_volume != null
              ? `${f.net_real_volume < 0 ? "−" : ""}${qty(Math.abs(f.net_real_volume))} سهم`
              : toman(f.net_real_value)}
          </Tile>
        )}
        {f && (
          <Tile
            k="قدرت خریدار"
            hint="سرانهٔ خرید حقیقی‌ها تقسیم بر سرانهٔ فروش آن‌ها؛ بالای ۱ یعنی هر خریدار به‌طور متوسط بیشتر از هر فروشنده معامله کرده است"
            tone={f.power != null ? (f.power >= 1 ? "text-up" : "text-down") : ""}
            sub={f.avg10_power == null ? undefined : `میانگین ۱۰ روز ${faNumber(f.avg10_power, 2)}`}
          >
            {f.power == null ? "—" : faNumber(f.power, 2)}
          </Tile>
        )}
      </dl>

      <dl
        className="flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-2 text-sm"
        data-testid="stock-stats-more"
      >
        {p && (
          <Mini k="ارزش معاملات">
            {toman(p.value)}
            {p.trades != null && <span className="text-muted"> · {faNumber(p.trades)} تراکنش</span>}
          </Mini>
        )}
        {fu?.pe != null && (
          <Mini k="P/E">
            {faNumber(fu.pe, 1)}
            {fu.sector_pe != null && (
              <span className="text-muted"> · گروه {faNumber(fu.sector_pe, 1)}</span>
            )}
          </Mini>
        )}
        {dash?.market_cap != null && <Mini k="ارزش بازار">{toman(dash.market_cap)}</Mini>}
      </dl>
    </header>
  );
}
