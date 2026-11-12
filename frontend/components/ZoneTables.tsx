import Link from "next/link";
import type { Ranking, RankingRow } from "@/lib/api";
import { faNumber, faPercent, faPrice } from "@/lib/format";
import { Num } from "@/components/Num";
import { signTone } from "@/lib/ui";

const ZONES = [
  ["buy", "ناحیهٔ خرید مدل", "بالاترین ۱۰٪ امتیاز"],
  ["hold", "ناحیهٔ نگهداری", "امتیاز بین ۷۰٪ و ۹۰٪ بالا"],
  ["avoid", "ناحیهٔ پرهیز", "امتیاز در ۷۰٪ پایین"],
] as const;

const QUEUE: Record<string, string> = {
  buy_queue: "صف خرید: عملاً نمی‌شود خرید",
  sell_queue: "صف فروش",
};

const SIGNALS: Record<string, string> = {
  ind_buy_power: "قدرت خریدار",
  rv_20: "نوسان کم",
  dist_high_52w: "نزدیکی به سقف",
  mom_12_1: "مومنتوم",
};

/** The three zones as full tables with each signal's score; the home page shows them compactly. */
export function ZoneTables({ d }: { d: Ranking }) {
  const by = (z: string) => d.rows.filter((r) => r.zone === z);
  const other = d.rows.filter((r) => r.zone === "no_data" || r.zone === "excluded");
  return (
    <>
      {ZONES.map(([z, title, rule]) => (
        <Zone key={z} zone={z} title={title} rule={rule} rows={by(z)} />
      ))}
      {other.length > 0 && (
        <Zone
          zone="other"
          title="بدون امتیاز"
          rule="امتیاز کل برای این نمادها محاسبه نشد چون دست‌کم یکی از چهار سیگنال (خانهٔ «—») سابقهٔ کافی ندارد یا نماد در صف فروش است؛ پس نه خرید و نه پرهیز برایشان گفته نمی‌شود"
          rows={other}
        />
      )}
    </>
  );
}

function Zone({
  zone,
  title,
  rule,
  rows,
}: {
  zone: string;
  title: string;
  rule: string;
  rows: RankingRow[];
}) {
  return (
    <section className="space-y-2" data-testid={`zone-${zone}`}>
      <h2 className="text-lg font-bold">
        {title} ({faNumber(rows.length)} نماد)
      </h2>
      <p className="text-xs text-muted">{rule}. امتیاز رتبه‌بندی بین ۰ و ۱ است.</p>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">امروز نمادی در این ناحیه نیست.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="tbl min-w-[38rem]">
            <thead>
              <tr className="text-right">
                <th>#</th>
                <th>نماد</th>
                <th>پایانی</th>
                <th>امروز</th>
                <th>امتیاز</th>
                {Object.values(SIGNALS).map((l) => (
                  <th key={l}>{l}</th>
                ))}
                <th>وضعیت صف</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} className="border-t border-line">
                  <td className="py-1">{faNumber(r.rank)}</td>
                  <td>
                    {r.instrument_id == null ? (
                      <span className="font-semibold">{r.symbol}</span>
                    ) : (
                      <Link
                        href={`/instruments/${r.instrument_id}`}
                        className="font-bold text-accent hover:underline"
                      >
                        {r.symbol}
                      </Link>
                    )}
                    <span className="mr-1 text-xs text-muted">{r.name}</span>
                    {r.name?.startsWith("صندوق") && (
                      <span className="mr-1 rounded border border-line px-1 text-xs">صندوق</span>
                    )}
                  </td>
                  <td>{r.close == null ? "—" : faPrice(r.close)}</td>
                  <td className={`font-semibold ${signTone(r.change_pct)}`}>
                    {r.change_pct == null ? "—" : faPercent(r.change_pct, 1, true)}
                  </td>
                  <td>
                    <Num value={r.score} term="rank_score" digits={2} />
                  </td>
                  {Object.keys(SIGNALS).map((k) => (
                    <td key={k}>
                      <Num value={r.signals[k]} term="rank_score" digits={2} />
                    </td>
                  ))}
                  <td className="text-xs">{QUEUE[r.queue_state ?? ""] ?? "عادی"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {zone === "buy" && rows.some((r) => r.queue_state === "buy_queue") && (
        <p className="text-xs text-muted">
          نمادهای در صف خرید را معمولاً نمی‌شود به قیمت آخر خرید؛ مدل خرید آن‌ها را در آزمون لغو
          می‌کند.
        </p>
      )}
    </section>
  );
}
