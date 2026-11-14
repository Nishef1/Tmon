import type { InstrumentDashboard } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";

type D = InstrumentDashboard;

/** Six-month share of similar past cases that beat the market, and the same share for all stocks. */
function regime(d: D): { rate: number; base: number } | null {
  const s = d.turning?.state.horizons.find((x) => x.horizon_days === 120);
  const b = d.turning?.base.horizons.find((x) => x.horizon_days === 120);
  return s?.beat != null && b?.beat != null ? { rate: s.beat, base: b.beat } : null;
}

const per100 = (x: number) => faNumber(Math.round(x * 100));

/** The one paragraph that reads the whole page together: the one-month verdict (what the model
 *  was tested on), the six-month record of the stock's current state, today's queue and the
 *  price where the short-term trend breaks. Every number comes from a section further down. */
export function Synthesis({ d }: { d: D }) {
  const month = d.decision.horizons.find((h) => h.key === "M1");
  const v = month?.verdict ?? d.decision.verdict;
  if (v === "none" && !d.decision.queue_state) return null;
  const r = regime(d);
  const worse = r != null && r.rate < r.base - 0.03;
  const better = r != null && r.rate > r.base + 0.03;
  const rec = r ? ` (${per100(r.rate)} از ۱۰۰ در برابر ${per100(r.base)} برای همهٔ سهم‌ها)` : "";
  let head: string | null = null;
  let tone = "bg-accent-soft";
  if (v === "buy") {
    head = worse
      ? `برای حدود یک ماه قوی است، ولی سهم‌هایی که در همین حالت بودند در شش ماه بعد کمتر از بازار جلو زدند${rec}. اگر می‌خرید، کوتاه‌مدت و با سطح خروج پایین بخرید.`
      : `امتیاز یک‌ماهه و سابقهٔ حالت فعلی سهم هم‌جهت‌اند${rec}؛ نشانهٔ خرید محکم‌تر است.`;
    tone = worse ? "bg-warn-soft" : "bg-up-soft";
  } else if (v === "hold") {
    head = better
      ? `برای خرید تازه برتری ثابت‌شده‌ای ندارد، ولی حالت فعلی سهم در گذشته از بازار جلو زده${rec}؛ اگر دارید نگه دارید.`
      : `نه امتیاز و نه سابقهٔ حالت فعلی سهم دلیل محکمی برای خرید تازه نمی‌دهد${rec}؛ اگر دارید، نگه دارید و هشدارها را دنبال کنید.`;
  } else if (v === "sell") {
    head = better
      ? `امتیاز ضعیف است، ولی حالت فعلی سهم در گذشته بد نبوده${rec}؛ خرید تازه نکنید، اما عجله‌ای برای فروش هم نیست.`
      : `امتیاز ضعیف است و سابقهٔ حالت فعلی سهم هم منفی است${rec}؛ اگر دارید، فروش را جدی بسنجید.`;
    tone = better ? "bg-accent-soft" : "bg-down-soft";
  }
  const q = d.decision.queue_state;
  const queue =
    q === "buy_queue"
      ? "روز آخر در صف خرید بود: سفارش خرید ممکن است پر نشود؛ به قیمت سقف و با حجم بزرگ وارد صف نشوید."
      : q === "sell_queue"
        ? "روز آخر در صف فروش بود: فروش هم ممکن است پر نشود."
        : null;
  const sma = d.technical?.values.find((x) => x.key === "sma20")?.value;
  const close = d.price?.close;
  const exit =
    typeof sma === "number" && close
      ? close > sma
        ? `سطح خروج: اگر قیمت پایانی زیر ${faNumber(Math.round(sma))} (میانگین ۲۰ روزه، ${faPercent(1 - sma / close, 0)} پایین‌تر از قیمت فعلی) بسته شود، روند کوتاه‌مدت شکسته است.`
        : `قیمت الان زیر میانگین ۲۰ روزه (${faNumber(Math.round(sma))}) است: روند کوتاه‌مدت ضعیف است.`
      : null;
  if (!head && !queue && !exit) return null;
  return (
    <div className={`rounded-lg p-3 ${tone}`} data-testid="synthesis" data-verdict={v}>
      <p className="text-sm font-bold">جمع‌بندی</p>
      {head && <p className="mt-1">{head}</p>}
      {queue && <p className="mt-1 text-sm">{queue}</p>}
      {exit && (
        <p className="mt-1 text-sm" data-testid="exit-level">
          {exit}
        </p>
      )}
    </div>
  );
}
