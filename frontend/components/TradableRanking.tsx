import Link from "next/link";
import type { Ranking, RankingRow } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Num } from "@/components/Num";

const isFund = (r: RankingRow) => (r.name ?? "").startsWith("صندوق");
const inQueue = (r: RankingRow) => r.queue_state === "buy_queue" || r.queue_state === "sell_queue";

type Col = {
  zone: "buy" | "hold" | "avoid";
  title: string;
  badge: string;
  tone: string;
  why: string;
};

/** Today's three possible decisions over the liquid basket: buy, hold, sell. Only stocks an
 * ordinary buyer can place an order for today appear (no funds, none in a limit queue); what was
 * left out is counted and named. The ranking is only advice once the validation gates pass. */
export function TradableRanking({ d }: { d: Ranking }) {
  const tradable = d.rows.filter((r) => !isFund(r) && !inQueue(r));
  const left = d.rows.filter((r) => isFund(r) || inQueue(r));
  const funds = left.filter(isFund);
  const queued = left.filter((r) => !isFund(r));
  const cols: Col[] = [
    {
      zone: "buy",
      title: "خرید",
      badge: "bg-good text-white",
      tone: "border-up/40 bg-up/10",
      why: `بالاترین ${d.buy_top_frac == null ? "بخش" : faPercent(d.buy_top_frac, 0)} رتبه‌بندی ترکیبی قدرت خریدار، آرام‌بودن نوسان، نزدیکی به سقف یک‌ساله و روند ۱۲ ماهه.`,
    },
    {
      zone: "hold",
      title: "نگهداری",
      badge: "bg-hold text-white",
      tone: "border-warn/40 bg-warn-soft",
      why: `تا ${d.hold_top_frac == null ? "ناحیهٔ بعدی" : `${faPercent(d.hold_top_frac, 0)} برتر`} رتبه‌بندی؛ اگر دارید نگه دارید، خرید تازه توصیه نمی‌شود.`,
    },
    {
      zone: "avoid",
      title: "فروش",
      badge: "bg-bad text-white",
      tone: "border-down/40 bg-down/10",
      why: "پایین‌تر از ناحیهٔ نگهداری؛ خرید نکنید و اگر دارید فروش را بسنجید.",
    },
  ];
  return (
    <section
      className="space-y-3 rounded-2xl border border-line bg-surface p-5"
      data-testid="tradable-ranking"
    >
      <h2 className="text-lg font-bold">تصمیم امروز: خرید، نگهداری یا فروش (توصیه نیست)</h2>
      <p className="text-sm text-muted">
        هر سهم فقط یکی از این سه حالت را دارد؛ اغلب روزها ناحیهٔ خرید تهی است یا آزمون‌های اعتبار
        مدل نگذشته‌اند و آن‌وقت این فهرست فقط رتبه‌بندی است. داده تا {jalali(d.as_of)}، از{" "}
        {d.basket_size == null ? "نمادهای" : `${faNumber(d.basket_size)} نمادِ`} پرمعامله.{" "}
        <Link href="/ranking" className="text-accent underline">
          اعداد دروازه‌ها و همهٔ نمادها
        </Link>
      </p>
      {!d.recommendation_allowed && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn" data-testid="gate-note">
          هنوز دروازه‌های اعتبار مدل کامل نگذشته‌اند؛ پس هیچ‌کدام از این سه ناحیه توصیهٔ مطمئن نیست.
          دلیل هر نماد در صفحهٔ خودش آمده است.
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        {cols.map((c) => (
          <Column key={c.zone} c={c} rows={tradable.filter((r) => r.zone === c.zone)} />
        ))}
      </div>
      <p className="text-xs text-muted">
        کنار گذاشته‌شده: {faNumber(queued.length)} سهم در صف
        {queued.length > 0 && ` (${queued.map((r) => r.symbol).join("، ")})`} و{" "}
        {faNumber(funds.length)} صندوق
        {funds.length > 0 && ` (${funds.map((r) => r.symbol).join("، ")})`}.
      </p>
    </section>
  );
}

function Column({ c, rows }: { c: Col; rows: RankingRow[] }) {
  const shown = c.zone === "avoid" ? rows.slice().reverse() : rows; // weakest first for sell
  const head = shown.slice(0, 12);
  const rest = shown.slice(12);
  return (
    <div className={`rounded-xl border p-3 ${c.tone}`} data-testid={`decision-${c.zone}`}>
      <div className="flex items-center gap-2">
        <span className={`rounded-full px-3 py-0.5 font-extrabold ${c.badge}`}>{c.title}</span>
        <span className="text-sm font-semibold">{faNumber(rows.length)} سهم</span>
      </div>
      <p className="mt-2 text-xs text-muted">{c.why}</p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm">امروز سهم عادیِ بدون صف در این ناحیه نیست.</p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-1.5 text-sm">
          {head.map((r) => (
            <Chip key={r.symbol} r={r} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-muted">{faNumber(rest.length)} نماد دیگر</summary>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {rest.map((r) => (
              <Chip key={r.symbol} r={r} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Chip({ r }: { r: RankingRow }) {
  return (
    <li className="rounded-lg border border-line bg-surface px-2 py-0.5">
      <span className="font-semibold">{r.symbol}</span>{" "}
      <Num value={r.score} term="rank_score" digits={2} />
      {r.name && <div className="max-w-48 truncate text-xs text-muted">{r.name}</div>}
    </li>
  );
}
