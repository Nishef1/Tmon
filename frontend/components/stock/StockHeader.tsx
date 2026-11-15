import type { ReactNode } from "react";
import type { InstrumentBook, InstrumentDashboard, InstrumentDetail } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import { PortfolioBadge } from "@/components/stock/PortfolioBadge";

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
}: {
  k: string;
  children: ReactNode;
  sub?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-surface-2 px-3 py-2">
      <dt className="truncate text-xs text-muted">{k}</dt>
      <dd className={`truncate text-base font-bold ${tone ?? ""}`}>{children}</dd>
      {sub != null && <div className="truncate text-xs text-muted">{sub}</div>}
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
  const realShare = f && buyTot ? (f.buy_volume_i ?? 0) / buyTot : null;
  return (
    <header data-testid="stock-header" className="card space-y-3">
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
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-3xl font-extrabold" data-testid="header-close">
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
      )}

      <dl
        className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7"
        data-testid="stock-stats"
      >
        {p?.low != null && p.high != null && p.high > p.low && (
          <Tile k="بازهٔ امروز">
            <Range lo={p.low ?? null} hi={p.high ?? null} v={p.close ?? null} />
          </Tile>
        )}
        {p && (
          <Tile
            k="حجم"
            sub={
              p.volume_ratio_30 == null ? undefined : `${faNumber(p.volume_ratio_30, 1)}× میانگین`
            }
            tone={p.volume_ratio_30 != null && p.volume_ratio_30 >= 1.5 ? "text-up" : ""}
          >
            {qty(p.volume)}
          </Tile>
        )}
        {p && (
          <Tile
            k="ارزش معاملات"
            sub={p.trades == null ? undefined : `${faNumber(p.trades)} معامله`}
          >
            {toman(p.value)}
          </Tile>
        )}
        {f && (
          <Tile
            k="ورود پول حقیقی"
            tone={(f.net_real_value ?? 0) >= 0 ? "text-up" : "text-down"}
            sub={realShare == null ? undefined : `${faPercent(realShare, 0)} خرید حقیقی`}
          >
            {toman(f.net_real_value)}
          </Tile>
        )}
        {f && (
          <Tile
            k="قدرت خریدار"
            tone={f.power != null ? (f.power >= 1 ? "text-up" : "text-down") : ""}
            sub={f.avg10_power == null ? undefined : `میانگین ۱۰ روز ${faNumber(f.avg10_power, 2)}`}
          >
            {f.power == null ? "—" : faNumber(f.power, 2)}
          </Tile>
        )}
        {fu?.pe != null && (
          <Tile
            k="P/E"
            sub={fu.sector_pe == null ? undefined : `گروه ${faNumber(fu.sector_pe, 1)}`}
          >
            {faNumber(fu.pe, 1)}
          </Tile>
        )}
        {dash?.market_cap != null && <Tile k="ارزش بازار">{toman(dash.market_cap)}</Tile>}
      </dl>
    </header>
  );
}
