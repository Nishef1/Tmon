import Link from "next/link";
import type { Ranking, RankingRow } from "@/lib/api";
import { faNumber, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

const isFund = (r: RankingRow) => (r.name ?? "").startsWith("صندوق");
const inQueue = (r: RankingRow) => r.queue_state === "buy_queue" || r.queue_state === "sell_queue";

/** Names of the model's buy and hold zones that an ordinary stock buyer can actually place an
 * order for today: not a fund, not in a queue. Everything left out is counted and named. */
export function TradableRanking({ d }: { d: Ranking }) {
  const zones = d.rows.filter((r) => r.zone === "buy" || r.zone === "hold");
  const ok = zones.filter((r) => !isFund(r) && !inQueue(r));
  const funds = zones.filter(isFund);
  const queued = zones.filter((r) => !isFund(r) && inQueue(r));
  const buy = ok.filter((r) => r.zone === "buy");
  const hold = ok.filter((r) => r.zone === "hold");
  return (
    <section
      className="space-y-3 rounded-2xl border border-line bg-surface p-5"
      data-testid="tradable-ranking"
    >
      <h2 className="text-lg font-bold">رتبه‌بندی v2: سهم‌های خریدنی امروز (توصیه نیست)</h2>
      <p className="text-sm text-muted">
        از ۱۰۰ نمادِ پرنقدشونده، فقط سهم‌هایی که در ناحیهٔ خرید یا نگهداری مدل‌اند و امروز صف ندارند
        و صندوق نیستند. داده تا {jalali(d.as_of)}. تا گذشتن دروازه‌های G4 و G6 این فهرست رتبه‌بندی
        مدل است، نه پیشنهاد خرید؛{" "}
        <Link href="/ranking" className="text-accent underline">
          اعداد دروازه‌ها و همهٔ ۱۰۰ نماد
        </Link>
        .
      </p>
      <List title="ناحیهٔ خرید مدل" rows={buy} />
      <List title="ناحیهٔ نگهداری" rows={hold} />
      <p className="text-xs text-muted">
        کنار گذاشته‌شده: {faNumber(queued.length)} سهم در صف
        {queued.length > 0 && ` (${queued.map((r) => r.symbol).join("، ")})`} و{" "}
        {faNumber(funds.length)} صندوق
        {funds.length > 0 && ` (${funds.map((r) => r.symbol).join("، ")})`} از همین دو ناحیه.
      </p>
    </section>
  );
}

function List({ title, rows }: { title: string; rows: RankingRow[] }) {
  return (
    <div>
      <h3 className="text-sm font-bold">
        {title} ({faNumber(rows.length)})
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">امروز سهم عادیِ بدون صف در این ناحیه نیست.</p>
      ) : (
        <ul className="mt-1 flex flex-wrap gap-2 text-sm">
          {rows.map((r) => (
            <li key={r.symbol} className="rounded-lg border border-line px-2 py-1">
              {r.symbol} <Num value={r.score} term="rank_score" digits={2} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
