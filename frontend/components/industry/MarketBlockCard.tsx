import type { MarketBlock } from "@/lib/columns";
import { faNumber, faPercent, faToman } from "@/lib/format";

/** Dollars in short form: ``۱۰۱.۷ میلیارد دلار``. */
function usd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return `${faNumber(v / 1e9, 1)} میلیارد دلار`;
  if (Math.abs(v) >= 1e6) return `${faNumber(v / 1e6, 1)} میلیون دلار`;
  return `${faNumber(v, 0)} دلار`;
}

function Tile({ k, v, note }: { k: string; v: string; note?: string }) {
  return (
    <div className="rounded-xl border border-line/70 bg-surface-2/40 px-4 py-3">
      <p className="text-xs text-muted">{k}</p>
      <p className="mt-0.5 text-lg font-black tabular-nums">{v}</p>
      {note && <p className="mt-0.5 text-xs text-muted">{note}</p>}
    </div>
  );
}

/** The exchange in rial and in dollars: how big it is, and what a year of the index looks like
 *  once the free-market dollar is taken out of it. */
export function MarketBlockCard({ m }: { m: MarketBlock }) {
  if (m.mcap == null) return null;
  return (
    <section className="card space-y-3" data-testid="market-block">
      <div className="space-y-0.5">
        <h2 className="text-lg font-black">اندازهٔ بازار به ریال و دلار</h2>
        <p className="text-xs leading-6 text-muted">
          جمع ارزش بازار سهامی که آخرین روز معامله شده‌اند، با نرخ دلار آزاد همان روز. دلار آزاد از
          سری ذخیره‌شدهٔ خودمان می‌آید و نرخ رسمی بورس نیست.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile k="ارزش بازار (تومان)" v={faToman(m.mcap)} />
        <Tile
          k="ارزش بازار به دلار"
          v={usd(m.mcap_usd)}
          note={m.usd ? `دلار آزاد ${faToman(m.usd)}` : undefined}
        />
        <Tile k="شاخص کل به دلار" v={m.index_usd == null ? "—" : faNumber(m.index_usd, 2)} />
        <Tile
          k="شاخص یک‌ساله به ریال"
          v={m.index_year_rial == null ? "—" : faPercent(m.index_year_rial, 0, true)}
          note={
            m.index_year_usd == null ? undefined : `به دلار ${faPercent(m.index_year_usd, 0, true)}`
          }
        />
      </div>
    </section>
  );
}
