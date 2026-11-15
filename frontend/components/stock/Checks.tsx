import type { InstrumentDashboard } from "@/lib/api";
import { trustWord } from "@/components/PlainSummary";
import { faNumber, faPercent } from "@/lib/format";
import { signedPct } from "@/lib/ui";

type D = InstrumentDashboard;
type H = D["decision"]["horizons"][number];

type Status = "ok" | "warn" | "bad" | "info";
type Check = { key: string; status: Status; ask: string; answer: React.ReactNode };

const ICON: Record<Status, string> = { ok: "✓", warn: "!", bad: "✕", info: "•" };
const WORD: Record<Status, string> = {
  ok: "مثبت",
  warn: "هشدار",
  bad: "منفی",
  info: "اطلاعات",
};

/** "یک ماه (۲۰ روز معاملاتی)" -> "یک ماه". */
export const shortLabel = (label: string) => label.split(" (")[0];

/** Six-month share of similar past cases that beat the market, and the same share for all stocks. */
function regime(d: D): { rate: number; base: number } | null {
  const s = d.turning?.state.horizons.find((x) => x.horizon_days === 120);
  const b = d.turning?.base.horizons.find((x) => x.horizon_days === 120);
  return s?.beat != null && b?.beat != null ? { rate: s.beat, base: b.beat } : null;
}

const per100 = (x: number) => faNumber(Math.round(x * 100));

/** The questions a buyer asks, each answered from a different source of the page. Every row has a
 *  mark (✓ for, ! caution, ✕ against) so disagreement between the sources is visible at a glance
 *  instead of hidden in paragraphs. */
export function buildChecks(d: D, h: H | undefined): Check[] {
  const out: Check[] = [];
  const g = d.decision.gauge;
  if (g != null) {
    out.push({
      key: "rank",
      status: g >= 90 ? "ok" : g >= 70 ? "info" : "bad",
      ask: "امروز از بقیهٔ سهم‌ها قوی‌تر است؟",
      answer: (
        <>
          از <b>{faNumber(g, 0)}٪</b> سهم‌های بازار بهتر است
          {d.decision.rank != null && <> (رتبهٔ {faNumber(d.decision.rank)} امروز)</>}.
        </>
      ),
    });
  }
  if (h && h.top_excess != null && h.net_excess != null) {
    const trust = trustWord(h.ic_t);
    const status: Status =
      h.net_excess >= 0.01 && (h.ic_t ?? 0) >= 3 ? "ok" : h.net_excess > 0 ? "warn" : "bad";
    out.push({
      key: "history",
      status,
      ask: "در گذشته چنین قدرتی سود اضافه داده؟",
      answer: (
        <>
          اگر هر روز ۱۰٪ بالای فهرست را می‌خریدید و {shortLabel(h.label)} نگه می‌داشتید، بعد از
          کارمزد و مالیات ({faPercent(h.cost ?? 0, 2)}) به‌طور میانگین{" "}
          <b>
            {h.net_excess >= 0
              ? `${signedPct(h.net_excess)} بیشتر از بازار`
              : `${signedPct(h.net_excess)} کمتر از بازار`}
          </b>{" "}
          سود می‌کردید
          {trust && <> (اطمینان {trust})</>}.
        </>
      ),
    });
  }
  const r = regime(d);
  if (r) {
    const status: Status = r.rate > r.base + 0.03 ? "ok" : r.rate < r.base - 0.03 ? "warn" : "info";
    out.push({
      key: "state",
      status,
      ask: "حالت فعلی سهم در شش ماه بعد چه کرده؟",
      answer: (
        <>
          سهم‌های هم‌حالت{d.turning ? ` («${d.turning.state.title}»)` : ""} در گذشته{" "}
          <b>{per100(r.rate)} بار از هر ۱۰۰ بار</b> در شش ماه از بازار جلو زدند؛ برای همهٔ سهم‌ها
          این عدد {per100(r.base)} است.
        </>
      ),
    });
  }
  const mae = d.turning?.state.mae60_median;
  if (d.turning && mae != null) {
    const p10 = d.turning.state.mae60_p10;
    out.push({
      key: "dip",
      status: -mae >= 0.1 ? "warn" : "info",
      ask: "اگر بخرم، اول ممکن است ضرر ببینم؟",
      answer: (
        <>
          هم‌حالت‌ها در دو ماه اول معمولاً تا <b className="text-down">{faPercent(-mae, 0)}</b>{" "}
          پایین‌تر از قیمت خرید هم رفتند
          {p10 != null && (
            <>
              ؛ در بدترین ۱ مورد از هر ۱۰ مورد تا <b className="text-down">{faPercent(-p10, 0)}</b>
            </>
          )}
          . حتی اگر آخرش سود بدهد، باید این افت موقت را تحمل کنید.
        </>
      ),
    });
  }
  const sma = d.technical?.values.find((x) => x.key === "sma20")?.value;
  const close = d.price?.close;
  if (typeof sma === "number" && close) {
    const above = close > sma;
    out.push({
      key: "exit",
      status: above ? "info" : "warn",
      ask: "از کجا بفهمم اشتباه بوده‌ام؟",
      answer: above ? (
        <>
          اگر قیمت پایانی زیر <b>{faNumber(Math.round(sma))}</b> (میانگین ۲۰ روزه) بسته شود، روند
          کوتاه‌مدت شکسته است. قیمت الان {faPercent(close / sma - 1, 0)} بالای آن است؛ تا آن سطح
          حدود {faPercent(1 - sma / close, 0)} افت جا دارد.
        </>
      ) : (
        <>
          قیمت الان زیر میانگین ۲۰ روزه (<b>{faNumber(Math.round(sma))}</b>) است؛ روند کوتاه‌مدت
          ضعیف است.
        </>
      ),
    });
  }
  const q = d.decision.queue_state;
  if (q === "buy_queue" || q === "sell_queue") {
    out.push({
      key: "queue",
      status: "warn",
      ask: "خرید و فروشش عملی است؟",
      answer:
        q === "buy_queue"
          ? "روز آخر در صف خرید بود: سفارش ممکن است پر نشود؛ با حجم بزرگ و قیمت سقف وارد صف نشوید."
          : "روز آخر در صف فروش بود: فروش هم ممکن است پر نشود.",
    });
  }
  return out;
}

/** What the marks add up to, in one line. */
function agreement(checks: Check[]): { text: string; tone: string } | null {
  const ok = checks.filter((c) => c.status === "ok").length;
  const against = checks.filter((c) => c.status === "warn" || c.status === "bad").length;
  if (ok + against === 0) return null;
  if (against === 0) {
    return { text: "همهٔ نشانه‌ها هم‌جهت‌اند.", tone: "bg-up-soft text-up" };
  }
  if (ok === 0) {
    return { text: "هیچ‌کدام از نشانه‌ها موافق نیست.", tone: "bg-down-soft text-down" };
  }
  return {
    text: `نشانه‌ها یکی نیستند: ${faNumber(ok)} مورد موافق، ${faNumber(against)} مورد هشدار.`,
    tone: "bg-warn-soft text-warn",
  };
}

/** The one paragraph that reads the rows together, for the chosen holding period. */
function bottomLine(
  d: D,
  h: H | undefined,
  checks: Check[],
): { text: string; tone: string } | null {
  const v = h?.verdict ?? d.decision.verdict;
  const period = h ? shortLabel(h.label) : "این بازه";
  const state = checks.find((c) => c.key === "state")?.status;
  const worse = state === "warn";
  const better = state === "ok";
  if (v === "buy") {
    return worse
      ? {
          text: `برای ${period} قوی است، ولی سهم‌هایی که در همین حالت بودند در شش ماه بعد کمتر از بازار جلو زدند. اگر می‌خرید، کوتاه‌مدت و با سطح خروج پایین بخرید.`,
          tone: "bg-warn-soft",
        }
      : {
          text: `امتیاز امروز و سابقهٔ ${period} هم‌جهت‌اند؛ نشانهٔ خرید محکم‌تر است. باز هم سطح خروج را از پیش مشخص کنید.`,
          tone: "bg-up-soft",
        };
  }
  if (v === "hold") {
    return {
      text: better
        ? `برای ${period} برتری ثابت‌شده‌ای برای خرید تازه نیست، ولی حالت فعلی سهم در گذشته از بازار جلو زده است. اگر دارید نگه دارید.`
        : `برای ${period} دلیل محکمی برای خرید تازه نیست. اگر دارید، نگه دارید و هشدارها را دنبال کنید.`,
      tone: "bg-accent-soft",
    };
  }
  if (v === "sell") {
    return better
      ? {
          text: `امتیاز ضعیف است، ولی حالت فعلی سهم در گذشته بد نبوده؛ خرید تازه نکنید، اما عجله‌ای هم برای فروش نیست.`,
          tone: "bg-accent-soft",
        }
      : {
          text: `امتیاز ضعیف است و سابقهٔ حالت فعلی هم منفی است. اگر دارید، فروش را جدی بسنجید.`,
          tone: "bg-down-soft",
        };
  }
  return null;
}

/** The answers behind the verdict: one row per question with a ✓ / ! / ✕ mark, a one-line
 *  agreement summary above them and the bottom line under them. */
export function Checks({ d, h }: { d: D; h: H | undefined }) {
  const checks = buildChecks(d, h);
  if (checks.length === 0) return null;
  const sum = agreement(checks);
  const last = bottomLine(d, h, checks);
  return (
    <div data-testid="checks" data-verdict={h?.verdict ?? d.decision.verdict}>
      {sum && (
        <p className={`rounded-lg px-3 py-2 text-sm font-bold ${sum.tone}`} data-testid="agreement">
          {sum.text}
        </p>
      )}
      <ul className="mt-1">
        {checks.map((c) => (
          <li key={c.key} className={`check check-${c.status}`} data-check={c.key}>
            <span className="check-ico" aria-hidden>
              {ICON[c.status]}
            </span>
            <div className="min-w-0">
              <p className="font-semibold">
                {c.ask} <span className="sr-only">({WORD[c.status]})</span>
              </p>
              <p className="mt-0.5 text-sm leading-7 text-muted">{c.answer}</p>
            </div>
          </li>
        ))}
      </ul>
      {last && (
        <div className={`mt-2 rounded-lg p-3 ${last.tone}`} data-testid="synthesis">
          <p className="text-sm font-bold">کلام آخر</p>
          <p className="mt-1">{last.text}</p>
        </div>
      )}
    </div>
  );
}
