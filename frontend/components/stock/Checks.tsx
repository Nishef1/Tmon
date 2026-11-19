import type { InstrumentDashboard } from "@/lib/api";
import { trustWord } from "@/components/PlainSummary";
import { faDigits, faNumber, faPercent } from "@/lib/format";
import { shortLabel, signedPct } from "@/lib/ui";
import { rideWarning } from "@/components/stock/rideMarks";

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
          از <b>{faNumber(Math.min(99, Math.round(g)), 0)}٪</b> سهم‌های بازار بهتر است
          {d.decision.rank != null && <> (رتبهٔ {faNumber(d.decision.rank)} امروز)</>}.
        </>
      ),
    });
  }
  const band = d.decision.band;
  if (h && h.net_excess != null && band && band !== "middle") {
    const trust = trustWord(h.ic_t);
    const avoid = band === "avoid";
    const grade = d.decision.grade;
    const status: Status =
      grade === "proven" ? "ok" : grade === "probable" || h.net_excess > 0 ? "warn" : "bad";
    const word = d.decision.grade_label;
    out.push({
      key: "history",
      status,
      ask: avoid ? "در گذشته پرهیز از چنین سهمی سود داده؟" : "در گذشته چنین قدرتی سود اضافه داده؟",
      answer: avoid ? (
        <>
          اگر از ناحیهٔ پایین فهرست پرهیز می‌کردید و به‌جایش بازار را {shortLabel(h.label)} نگه
          می‌داشتید، بعد از کارمزد ({faPercent(h.cost ?? 0, 2)}) به‌طور میانگین{" "}
          <b>
            {h.net_excess >= 0
              ? `${signedPct(h.net_excess)} بیشتر`
              : `${signedPct(h.net_excess)} کمتر`}
          </b>{" "}
          سود می‌کردید
          {word && <> (شواهد این ناحیه: {word})</>}.
        </>
      ) : (
        <>
          اگر هر روز نیمهٔ بالای فهرست را می‌خریدید و {shortLabel(h.label)} نگه می‌داشتید، بعد از
          کارمزد و مالیات ({faPercent(h.cost ?? 0, 2)}) به‌طور میانگین{" "}
          <b>
            {h.net_excess >= 0
              ? `${signedPct(h.net_excess)} بیشتر از بازار`
              : `${signedPct(h.net_excess)} کمتر از بازار`}
          </b>{" "}
          سود می‌کردید
          {word && <> (شواهد این ناحیه: {word})</>}
          {trust && h.net_excess < 0 && (
            <> (قدرت رتبه‌بندی از نظر آماری {trust} است، ولی کارمزد را پوشش نمی‌دهد)</>
          )}
          .
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
          <b>{per100(r.rate)} بار از هر ۱۰۰ بار</b> در شش ماه از بازار جلو زدند؛ برای همهٔ سهم‌ها این
          عدد {per100(r.base)} است.
        </>
      ),
    });
  }
  const ride = d.turning?.ride;
  if (ride) {
    const warn = rideWarning(ride);
    const open = ride.status === "open";
    out.push({
      key: "ride",
      status: warn ? "warn" : "info",
      ask: "قاعدهٔ ورود و خروج روند چه می‌گوید؟",
      answer: (
        <>
          {open ? "دورهٔ روند باز است" : "دورهٔ روندی باز نیست"}
          {warn &&
            (warn.side === "sell"
              ? `؛ قیمت فقط ${faPercent(warn.move, 1)} بالای خط فروش است و فروش روند نزدیک است`
              : `؛ با ${faPercent(warn.move, 1)} رشد نشانهٔ ورود روند می‌آید`)}
          . آزمون سه سال اخیر نشان داد باز یا بسته بودن این دوره، کنار امتیاز سهم، سود اضافهٔ
          ثابت‌شده‌ای نمی‌افزاید؛ برای همین حکم را عوض نمی‌کند و فقط زمان خرید و فروش را نشان
          می‌دهد.
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
  // tested classic readings the symbol fired lately: they were judged on their own, apart from
  // the score, so they are shown beside the verdict and never change it
  for (const f of d.technical?.fired ?? []) {
    if (f.label !== "works" && f.label !== "backfires") continue;
    const up = (f.side === "buy") !== (f.label === "backfires");
    const when = f.ago === 0 ? "در آخرین روز معاملاتی" : `${faNumber(f.ago)} روز معاملاتی پیش`;
    out.push({
      key: `signal-${f.key}`,
      status: up ? "ok" : "warn",
      ask: up ? "نشانهٔ فنی آزموده‌ای موافق است؟" : "نشانهٔ فنی آزموده‌ای مخالف است؟",
      answer: (
        <>
          «{f.title}» {when} دیده شد. {faDigits(f.verdict)} این نشانه جدا از امتیاز سهم آزموده شده و
          در حکم حساب نشده است.
        </>
      ),
    });
  }
  const close = d.price?.close;
  const sma = d.technical?.values.find((x) => x.key === "sma20")?.value;
  const stop = ride?.status === "open" ? ride.stop : null;
  if (stop != null && close) {
    // one exit level on the page: the trend rule's sell line, the same as the card and the chart
    out.push({
      key: "exit",
      status: ride && rideWarning(ride) ? "warn" : "info",
      ask: "از کجا بفهمم اشتباه بوده‌ام؟",
      answer: (
        <>
          اگر قیمت پایانی زیر <b>{faNumber(Math.round(stop))}</b> (خط فروش قاعدهٔ روند) بسته شود،
          قاعده می‌فروشد. قیمت امروز {faPercent(close / stop - 1, 0)} بالای آن است.
          {typeof sma === "number" && sma > stop && close > sma && (
            <>
              {" "}
              میانگین ۲۰ روزه ({faNumber(Math.round(sma))}) نزدیک‌تر است، ولی خروج با آن آزموده نشده
              است.
            </>
          )}
        </>
      ),
    });
  } else if (typeof sma === "number" && close) {
    const above = close > sma;
    out.push({
      key: "exit",
      status: above ? "info" : "warn",
      ask: "از کجا بفهمم اشتباه بوده‌ام؟",
      answer: above ? (
        <>
          اگر قیمت پایانی زیر <b>{faNumber(Math.round(sma))}</b> (میانگین ۲۰ روزه) بسته شود، روند
          کوتاه‌مدت شکسته است. قیمت امروز {faPercent(close / sma - 1, 0)} بالای آن است؛ تا آن سطح
          حدود {faPercent(1 - sma / close, 0)} افت جا دارد.
        </>
      ) : (
        <>
          قیمت امروز زیر میانگین ۲۰ روزه (<b>{faNumber(Math.round(sma))}</b>) است؛ روند کوتاه‌مدت
          ضعیف است.
        </>
      ),
    });
  }
  const rsi = d.technical?.values.find((x) => x.key === "rsi")?.value;
  const green = d.entry?.green ?? 0;
  const hot = typeof rsi === "number" && rsi > 80;
  if (hot || green >= 6) {
    const parts = [
      hot ? `RSI ۱۴ روزه ${faNumber(rsi, 0)} است (بالای ۸۰)` : null,
      green >= 6 ? `${faNumber(green)} کندل سبز پشت هم آمده` : null,
    ].filter(Boolean);
    out.push({
      key: "heat",
      status: "warn",
      ask: "کوتاه‌مدت داغ نیست؟",
      answer: (
        <>
          {parts.join(" و ")}. کوتاه‌مدت اشباع خرید است و ممکن است چند روز اصلاح شود؛ این هشدار حکم
          بالا را عوض نمی‌کند، ولی ورود را بهتر است پله‌پله یا نزدیک سطح خروج انجام دهید.
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

/** The one paragraph that reads the rows together, for the answer the page gives. */
function bottomLine(
  d: D,
  h: H | undefined,
  checks: Check[],
): { text: string; tone: string } | null {
  const code = d.decision.code;
  const period = h ? shortLabel(h.label) : "این بازه";
  const state = checks.find((c) => c.key === "state")?.status;
  const worse = state === "warn";
  const better = state === "ok";
  const grade = d.decision.grade_label ?? "ثابت‌نشده";
  switch (code) {
    case "buy":
      return worse
        ? {
            text: `برای ${period} قوی است، ولی سهم‌هایی که در همین حالت بودند در شش ماه بعد کمتر از بازار جلو زدند. اگر می‌خرید، کم‌حجم و با سطح خروج پایین بخرید.`,
            tone: "bg-warn-soft",
          }
        : {
            text: `امتیاز امروز و سابقهٔ ${period} هم‌جهت‌اند و شواهد این ناحیه ${grade} است. باز هم سطح خروج را از پیش مشخص کنید.`,
            tone: "bg-up-soft",
          };
    case "candidate":
      return {
        text: `نامزد خرید است، نه توصیه: شواهد این ناحیه ${grade} است. اگر می‌خرید، کم‌حجم و با سطح خروج مشخص بخرید.`,
        tone: "bg-accent-soft",
      };
    case "candidate_queue":
      return {
        text: "نامزد خرید است، ولی در صف خرید است؛ خرید امروز عملاً ممکن نیست و به قیمت سقف صف نباید خرید.",
        tone: "bg-warn-soft",
      };
    case "wait":
      return {
        text: "امتیاز بالاست، ولی حالت فعلی سهم در گذشته از بازار جلو نزده است؛ فعلاً صبر کنید. اگر دارید، نگه دارید.",
        tone: "bg-warn-soft",
      };
    case "wait_market":
      return {
        text: "بازار امروز می‌گوید سهام نخرید؛ صبر کنید تا سهم سرمایه در سهام دوباره مثبت شود. اگر دارید، هشدارهای پرتفوی را دنبال کنید.",
        tone: "bg-warn-soft",
      };
    case "avoid":
      return {
        text: `امتیاز در ناحیهٔ پایین است و عقب‌ماندگی این ناحیه شواهد دارد (${grade}). خرید تازه نکنید؛ اگر دارید، فروش را بسنجید.`,
        tone: "bg-down-soft",
      };
    case "with_market":
      return {
        text:
          d.decision.band === "avoid"
            ? `امتیاز پایین است، ولی عقب‌ماندگی این ناحیه هنوز ثابت نشده (${grade}). خرید تازه دلیلی ندارد و فروش هم لازم نیست؛ همراه بازار بمانید${better ? "، و حالت فعلی سهم در گذشته بد نبوده" : ""}.`
            : `برای ${period} نه نامزد خرید است نه دلیلی برای پرهیز دارد؛ همراه بازار بمانید. اگر دارید، نگه دارید.`,
        tone: "bg-accent-soft",
      };
    default:
      return null;
  }
}

/** The answers behind the verdict: one row per question with a ✓ / ! / ✕ mark, a one-line
 *  agreement summary above them and the bottom line under them. */
export function Checks({ d, h }: { d: D; h: H | undefined }) {
  const checks = buildChecks(d, h);
  if (checks.length === 0) return null;
  const sum = agreement(checks);
  const last = bottomLine(d, h, checks);
  const against = checks.some((c) => c.key.startsWith("signal-") && c.status === "warn");
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
          {against && (
            <p className="mt-1" data-testid="synthesis-signal">
              یک نشانهٔ فنی آزموده هم خلاف این حکم است. حکم را عوض نمی‌کند، چون جدا آزموده شده؛ ولی
              دلیل خوبی است که اگر می‌خرید کم‌حجم بخرید و خط فروش را جدی بگیرید.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
