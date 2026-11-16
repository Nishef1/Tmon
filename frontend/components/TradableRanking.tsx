import { QueueBadge } from "@/components/QueueBadge";
import { rowVerdict, verdictPill, verdictTone } from "@/lib/ui";
import { TradeBadge } from "@/components/TradeBadge";
import Link from "next/link";
import type { Ranking, RankingRow } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

const isFund = (r: RankingRow) => (r.name ?? "").startsWith("صندوق");
// A buy queue is shown (tagged): the stock is strong, only a market order may not fill today.
const inQueue = (r: RankingRow) => r.queue_state === "sell_queue";

type Col = {
  zone: "buy" | "hold" | "avoid";
  title: string;
  why: string;
};

/** Today's three possible decisions over the liquid basket: buy, hold, sell. Only stocks an
 * ordinary buyer can place an order for today appear (no funds, none in a sell queue); what was
 * left out is counted and named. The ranking is only advice once the validation gates pass. */
const ZONE = { buy: "buy", hold: "hold", avoid: "sell" } as const;

export function TradableRanking({ d }: { d: Ranking }) {
  const tradable = d.rows.filter((r) => !isFund(r) && !inQueue(r));
  const left = d.rows.filter((r) => isFund(r) || inQueue(r));
  const funds = left.filter(isFund);
  const queued = left.filter((r) => !isFund(r));
  const extra = d.rows.filter((r) => r.in_basket === false).length;
  const cols: Col[] = [
    {
      zone: "buy",
      title: "خرید",
      why: `بالاترین ${d.buy_top_frac == null ? "بخش" : faPercent(d.buy_top_frac, 0)} رتبه‌بندی ترکیبی و آزمون یک‌ماههٔ پس از کارمزد هم تأییدش کرده است.`,
    },
    {
      zone: "hold",
      title: "صبر",
      why: `امتیاز تا ${d.hold_top_frac == null ? "محدودهٔ بعدی" : `${faPercent(d.hold_top_frac, 0)} برتر`}، یا بالاتر ولی بدون تأیید آزمون یک‌ماهه؛ خرید تازه نکنید و اگر دارید نگه دارید.`,
    },
    {
      zone: "avoid",
      title: "فروش",
      why: "امتیاز پایین؛ نخرید و اگر دارید فروش را بسنجید.",
    },
  ];
  return (
    <section className="card space-y-3" data-testid="tradable-ranking">
      <h2 className="text-lg font-bold">تصمیم امروز: خرید، صبر یا فروش (توصیه نیست)</h2>
      <p className="text-sm text-muted">
        همان حکم جدول بالا و صفحهٔ هر سهم؛ هر سهم یکی از این سه حالت را دارد (جز نمادهای بدون
        امتیاز). اغلب روزها محدودهٔ خرید خالی است یا آزمون‌های پذیرش مدل نگذشته‌اند و آن‌وقت این
        فهرست فقط رتبه‌بندی است. داده تا {jalali(d.as_of)}:{" "}
        {d.basket_size == null ? "نمادهای پرمعامله" : `${faNumber(d.basket_size)} نماد پرمعامله`}
        {extra > 0 &&
          ` و ${faNumber(extra)} نماد محدودهٔ خرید بیرون از آن‌ها («کم‌معامله‌تر»)`}.{" "}
        <Link href="/model#v2" className="text-accent underline">
          اعداد آزمون‌های پذیرش و همهٔ نمادها
        </Link>
      </p>
      {!d.recommendation_allowed && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn" data-testid="gate-note">
          هنوز آزمون‌های پذیرش اعتبار مدل کامل نگذشته‌اند؛ پس هیچ‌کدام از این سه ناحیه توصیهٔ مطمئن
          نیست. دلیل هر نماد در صفحهٔ خودش آمده است.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {cols.map((c) => (
          <Column
            key={c.zone}
            c={c}
            rows={tradable.filter((r) => rowVerdict(r) === ZONE[c.zone])}
          />
        ))}
      </div>
      <p className="text-xs text-muted">
        کنار گذاشته‌شده: {faNumber(queued.length)} سهم در صف فروش
        {queued.length > 0 && ` (${queued.map((r) => r.symbol).join("، ")})`} و{" "}
        {faNumber(funds.length)} صندوق
        {funds.length > 0 && ` (${funds.map((r) => r.symbol).join("، ")})`}؛ این‌ها در جدول کامل
        پایین هستند و برای همین شمار آنجا بیشتر است. نمادهای «صف خرید» نشان داده می‌شوند ولی ممکن
        است سفارش امروز پر نشود.
      </p>
    </section>
  );
}

function Column({ c, rows }: { c: Col; rows: RankingRow[] }) {
  // buy and hold: strongest first; sell: weakest (most urgent to exit) first
  const dir = c.zone === "avoid" ? 1 : -1;
  const shown = rows.slice().sort((a, b) => dir * ((a.score ?? 0) - (b.score ?? 0)));
  const head = shown.slice(0, 12);
  const rest = shown.slice(12);
  return (
    <div className={`well border ${verdictTone(ZONE[c.zone])}`} data-testid={`decision-${c.zone}`}>
      <div className="flex items-center gap-2">
        <span className={`${verdictPill(ZONE[c.zone])} pill-lg`}>{c.title}</span>
        <span className="text-sm font-semibold">{faNumber(rows.length)} سهم</span>
      </div>
      <p className="mt-2 text-xs text-muted">{c.why}</p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm">امروز سهم عادیِ بدون صف فروش در این ناحیه نیست.</p>
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
    <li>
      <Link
        href={
          r.instrument_id == null
            ? `/industries?q=${encodeURIComponent(r.symbol)}`
            : `/instruments/${r.instrument_id}`
        }
        className="chip block"
      >
        <span className="flex items-baseline gap-2">
          <span className="font-bold">{r.symbol}</span>
          <TradeBadge state={r.trade_state} idleDays={r.idle_days} lastTrade={r.last_trade_date} />
          <QueueBadge r={r} />
          {r.in_basket === false && (
            <span className="rounded bg-warn-soft px-1 text-[10px] text-warn">کم‌معامله‌تر</span>
          )}
          {r.change_pct != null && (
            <span
              className={`text-xs font-semibold ${r.change_pct > 0 ? "text-up" : r.change_pct < 0 ? "text-down" : "text-muted"}`}
            >
              {faPercent(r.change_pct, 1, true)}
            </span>
          )}
        </span>
        {r.name && <span className="block max-w-48 truncate text-xs text-muted">{r.name}</span>}
      </Link>
    </li>
  );
}
