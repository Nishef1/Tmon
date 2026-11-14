import Link from "next/link";
import type { InstrumentBook, InstrumentDashboard, InstrumentDetail } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import { PortfolioBadge } from "@/components/stock/PortfolioBadge";

const QUEUE: Record<string, { text: string; cls: string }> = {
  buy_queue: { text: "صف خرید", cls: "bg-up-soft text-up" },
  sell_queue: { text: "صف فروش", cls: "bg-down-soft text-down" },
};

/** Symbol, last close and its change, today's queue, whether you hold it, and the day each
 *  data source is from (with a warning when they are not the same day). */
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
  const q = dash?.decision.queue_state ? QUEUE[dash.decision.queue_state] : null;
  const dates = [
    { k: "قیمت", v: p?.date ?? null },
    { k: "حقیقی/حقوقی", v: dash?.flow?.date ?? null },
    { k: "رفتار خریداران", v: book?.available ? (book.as_of ?? null) : null },
  ].filter((x): x is { k: string; v: string } => x.v != null);
  const mixed = new Set(dates.map((x) => x.v.slice(0, 10))).size > 1;
  return (
    <header data-testid="stock-header">
      <Link href="/" className="text-sm text-accent">
        ← توصیه‌های امروز
      </Link>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="text-2xl font-extrabold">{d.instrument.symbol}</h1>
        {d.instrument.name && <span className="text-muted">{d.instrument.name}</span>}
        {p?.close != null && (
          <span className="text-lg font-bold" data-testid="header-close">
            {faNumber(p.close)}
            {p.close_change != null && (
              <span className={`ms-2 text-base ${signTone(p.close_change)}`}>
                {faPercent(p.close_change, 2, true)}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        {q && (
          <span className={`chip ${q.cls}`} data-testid="header-queue">
            {q.text}
          </span>
        )}
        <PortfolioBadge instrumentId={d.instrument.id} />
      </div>
      {dates.length > 0 && (
        <p
          className={`mt-2 text-xs ${mixed ? "text-warn" : "text-muted"}`}
          data-testid="data-dates"
        >
          {dates.map((x) => `${x.k}: ${jalali(x.v, "short")}`).join(" · ")}
          {mixed && " — داده‌ها از یک روز نیستند؛ عددهای هر بخش مال روز خودشان است."}
        </p>
      )}
    </header>
  );
}
