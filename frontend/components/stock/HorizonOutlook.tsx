import Link from "next/link";
import type { InstrumentDashboard, SymbolForecast } from "@/lib/api";
import { faDigits, faNumber, faPrice } from "@/lib/format";
import { signedPct } from "@/lib/ui";
import { HoldWord } from "@/components/stock/HoldWord";
import type { Ride } from "@/components/stock/rideMarks";
import { PERIOD_KEYS, PERIOD_SHORT, type Period } from "@/components/stock/outlook";

type D = InstrumentDashboard;
type Zone = D["decision"]["by_horizon"][number];

const rial = (n: number) => `${faPrice(Math.round(n))} ریال`;
const per100 = (x: number) => faNumber(Math.round(x * 100));

/** What the zone's record says for this period, in one sentence, and whether it backs a buy. */
function zoneLine(z: Zone | undefined, band: string | null | undefined): string {
  if (!z) {
    return band === "middle"
      ? "امتیاز این سهم وسط فهرست است و ناحیهٔ وسط برای هیچ بازه‌ای سابقهٔ جدا ندارد."
      : "سابقهٔ ناحیهٔ این سهم برای این بازه سنجیده نشده است.";
  }
  const avoid = band === "avoid";
  const who = avoid ? "پرهیز از نیمهٔ پایین فهرست" : "خرید نیمهٔ بالای فهرست";
  const how =
    z.status === "loss"
      ? "بعد از کارمزد در هر دو نیمهٔ داده زیان داده است"
      : z.status === "proven"
        ? "در هر دو نیمهٔ داده سود اضافهٔ ثابت‌شده داشته است"
        : z.status === "probable"
          ? "سود اضافه داشته ولی هنوز ثابت نشده است"
          : "سود اضافهٔ ثابت‌شده‌ای نداشته است";
  return `${who} با ${z.label} نگه‌داری ${how} (میانگین ${signedPct(z.net)} نسبت به بازار، نیمهٔ اول ${signedPct(z.net_h1)} و دوم ${signedPct(z.net_h2)}).`;
}

/** Where the trend rule's line sits against this period's range: the one link between the
 *  forecast and the rule's own buy and sell days. */
function rideLine(r: Ride | null, low: number, high: number): string | null {
  if (!r) return null;
  // the range is the price on the period's last day, not the lowest or highest on the way
  const path = "بازه فقط قیمت روز آخر را می‌گوید؛ قیمت میان راه ممکن است از آن بیرون برود.";
  if (r.status === "open" && r.stop != null) {
    return r.stop >= low
      ? `خط فروش روند (${rial(r.stop)}) داخل این بازه است: ممکن است در این مدت نشانهٔ فروش روند بیاید.`
      : `خط فروش روند (${rial(r.stop)}) زیر کف این بازه است. ${path}`;
  }
  if (r.buy_trigger != null) {
    return r.buy_trigger <= high
      ? `قیمت ورود روند (${rial(r.buy_trigger)}) داخل این بازه است: ممکن است در این مدت نشانهٔ ورود روند بیاید.`
      : `قیمت ورود روند (${rial(r.buy_trigger)}) بالای سقف این بازه است. ${path}`;
  }
  return null;
}

/** One card for "if I hold for N days": the tested price range, the chance of a gain after cost,
 *  the zone's record for that period, the trend rule's line, and the page's one final verdict.
 *  Every line names its source, so the reader sees how the parts of the page meet. */
export function HorizonOutlook({
  f,
  d,
  ride,
  period,
  href,
  id,
  fundNote,
}: {
  f: SymbolForecast;
  d: D;
  ride: Ride | null;
  period: Period;
  href: (key: string) => string;
  id: number;
  /** for a fund: what testing the ranges on funds showed (shown, never hidden) */
  fundNote?: string;
}) {
  const price = f.price ?? 0;
  const low = price * (1 + period.low);
  const mid = price * (1 + period.mid);
  const high = price * (1 + period.high);
  const zone = d.decision.by_horizon.find((z) => z.days === period.days);
  const verdictDays = d.decision.by_horizon.find((z) => z.verdict_horizon)?.days ?? 60;
  const isVerdict = period.days === verdictDays;
  const noBuy = zone?.status === "loss" && d.decision.band !== "avoid";
  const ridePart = rideLine(ride, low, high);
  return (
    <section
      className="card scroll-mt-28"
      id="outlook"
      data-testid="outlook"
      data-period={period.key}
    >
      <h2 className="text-lg font-extrabold">اگر این مدت نگه دارید</h2>
      <nav className="mt-2 flex flex-wrap gap-2" aria-label="بازهٔ پیش‌بینی">
        {PERIOD_KEYS.filter((k) => f.horizons.some((x) => x.key === k)).map((k) => (
          <Link
            key={k}
            href={href(k)}
            scroll={false}
            className="tab tab-pill tab-sm"
            aria-current={k === period.key ? "page" : undefined}
            data-testid={`period-${k}`}
          >
            {PERIOD_SHORT[k]}
          </Link>
        ))}
      </nav>

      <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-lg bg-surface-2 p-3" data-testid="outlook-range">
          <dt className="text-xs text-muted">بازهٔ قیمت پس از {period.label} (۸ بار از ۱۰)</dt>
          <dd className="mt-1 text-base font-bold tabular-nums">
            {rial(low)} تا {rial(high)}
          </dd>
          <dd className="mt-1 text-xs text-muted">
            میانه {rial(mid)} ({signedPct(period.mid)}). روی نمودار با نقطه‌چین کشیده شده است.
          </dd>
        </div>
        <div className="rounded-lg bg-surface-2 p-3" data-testid="outlook-chance">
          <dt className="text-xs text-muted">سود بعد از کارمزد خرید و فروش</dt>
          <dd className="mt-1 text-base font-bold tabular-nums">
            {per100(period.p_gain_net)} مسیر از ۱۰۰
          </dd>
          <dd className="mt-1 text-xs text-muted">
            در شبیه‌سازی از حرکت‌های گذشتهٔ همین سهم؛ این عدد خودش آزموده نشده است.
          </dd>
        </div>
      </dl>

      {fundNote && (
        <p className="mt-3 rounded-lg bg-warn-soft p-3 text-sm" data-testid="fund-ranges-note">
          {faDigits(fundNote)}
        </p>
      )}

      <ul className="mt-3 list-inside list-disc space-y-1.5 text-sm leading-7">
        <li data-testid="outlook-tested">
          {period.reliable ? (
            <>
              این بازه روی {faNumber(period.windows)} دورهٔ جدا از گذشتهٔ همین سهم آزموده شد:{" "}
              {period.coverage80 != null && (
                <>قیمت در {per100(period.coverage80)} دوره از ۱۰۰ داخل بازهٔ خام ماند</>
              )}
              {period.calibrated ? " و بازه به اندازه‌ای اصلاح شد که ۸ از ۱۰ را بپوشاند." : "."}
            </>
          ) : (
            <>
              گذشتهٔ این سهم برای آزمودن این بازه دورهٔ جدای کافی ندارد ({faNumber(period.windows)}{" "}
              دوره)؛ بازه آزموده نیست.
            </>
          )}
        </li>
        <li data-testid="outlook-zone">{zoneLine(zone, d.decision.band)}</li>
        {ridePart && <li data-testid="outlook-ride">{ridePart}</li>}
      </ul>

      <p
        className="mt-3 rounded-lg bg-accent-soft p-3 text-sm leading-7"
        data-testid="outlook-verdict"
      >
        {noBuy && !isVerdict && (
          <>
            <b>برای {period.label} نشانهٔ خرید نیست:</b> کارمزد از سود اضافهٔ این ناحیه بیشتر بوده
            است.{" "}
          </>
        )}
        {!isVerdict && !noBuy && <>حکم فقط برای سه ماه داده می‌شود. </>}
        حکم نهایی صفحه (سه ماه):{" "}
        <b>
          <HoldWord
            label={d.decision.label}
            holderLabel={d.decision.holder_label}
            instrumentId={id}
          />
        </b>
        . <Link href="#decision">چرا؟</Link>
      </p>
      <p className="mt-2 text-xs leading-6 text-muted">
        بازه‌ها از شبیه‌سازی حرکت‌های گذشتهٔ همین سهم با نوسان امروز به دست آمده‌اند. روزهای تعطیل از
        پیش معلوم نیستند، پس پایان بازه روی نمودار ممکن است یکی دو روز جابه‌جا باشد. بیشتر دادهٔ
        بازار از یک دورهٔ صعودی است.
      </p>
    </section>
  );
}
