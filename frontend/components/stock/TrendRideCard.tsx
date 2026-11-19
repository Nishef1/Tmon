"use client";

import type { ReactNode } from "react";
import { faDigits, faNumber, faPercent, faPrice, jalali } from "@/lib/format";
import { signedPct, signTone } from "@/lib/ui";
import { useOwned } from "@/components/stock/HoldWord";
import { rideStale, rideWarning, type Ride } from "@/components/stock/rideMarks";

type Block = NonNullable<Ride["history"]>["halves"][number];

const GRADE: Record<Ride["grade"], { label: string; cls: string }> = {
  proven: { label: "اثبات‌شده", cls: "v-buy" },
  probable: { label: "احتمالی", cls: "v-hold" },
  unproven: { label: "آزموده‌نشده", cls: "v-none" },
};

const rial = (n: number | null | undefined) => (n == null ? "—" : `${faPrice(n)} ریال`);
const per100 = (n: number) => faNumber(Math.round(n * 100));

/** The next close that would be an entry signal, when one day could still reach it. */
function Trigger({ r }: { r: Ride }) {
  const x = r.buy_trigger!;
  const rise = x / r.last_close - 1;
  if (r.day_rise_max != null && rise > r.day_rise_max)
    return (
      <p className="mt-2 text-sm" data-testid="ride-buy-trigger">
        نشانهٔ ورود فردا نمی‌آید: قیمت باید دست‌کم {faPercent(rise, 0)} بالا برود، بیشتر از بیشترین
        رشد یک‌روزهٔ این سهم در یک سال گذشته.
      </p>
    );
  return (
    <p className="mt-2 text-sm" data-testid="ride-buy-trigger">
      <b>قیمت نشانهٔ ورود بعدی: {rial(x)}</b> ({faPercent(Math.abs(rise), 0)}{" "}
      {rise >= 0 ? "بالاتر" : "پایین‌تر"} از قیمت پایانی امروز). اگر قیمت فردا تا نزدیک پایان بازار
      بالای این عدد باشد، نشانهٔ ورود می‌آید و قاعده در دقایق آخر همان روز می‌خرد، پیش از آنکه صف
      خرید ببندد. این عدد هر روز با قیمت‌های تازه عوض می‌شود.
    </p>
  );
}

// How often a signal came within 5 trading days of a day inside the 3% band, in the two halves
// of the last three years (docs/reports/trend-warn-2026-11.md); they hold only for that band.
const WARN_HIT = { buy: [56, 78], sell: [57, 74] } as const;

/** A buy or a sale is near: the next close needs only a small move to cross the line. */
function Warn({ r, owned }: { r: Ride; owned: boolean }) {
  const w = rideWarning(r);
  if (!w || r.warn_band == null) return null;
  const [lo, hi] = WARN_HIT[w.side];
  const band = faPercent(r.warn_band, 0);
  const buy = w.side === "buy";
  return (
    <div
      className="mt-3 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm"
      data-testid="ride-warn"
      data-side={w.side}
    >
      <p className="font-bold">
        {buy
          ? `هشدار: نشانهٔ ورود نزدیک است. قیمت فقط ${faPercent(Math.max(0, w.move), 1)} تا قیمت ورود فاصله دارد.`
          : `هشدار: فروش نزدیک است. قیمت فقط ${faPercent(Math.max(0, w.move), 1)} بالای خط فروش است.`}
      </p>
      <p className="mt-1">
        در سه سال اخیر، روزهایی که فاصله کمتر از {band} بود، از هر ۱۰۰ بار {faNumber(lo)} تا{" "}
        {faNumber(hi)} بار تا ۵ روز معاملاتی {buy ? "نشانهٔ ورود" : "فروش"} آمد. این هشدار خودش نشانه
        نیست:{" "}
        {buy
          ? "خرید فقط وقتی است که قیمت در دقایق آخر بازار بالای قیمت ورود باشد."
          : owned
            ? "فروش فقط وقتی است که قیمت در دقایق آخر بازار زیر خط فروش باشد. فردا نزدیک پایان بازار قیمت را با خط مقایسه کن."
            : "برای دارندهٔ سهم، فروش فقط وقتی است که قیمت در دقایق آخر بازار زیر خط فروش باشد."}
      </p>
    </div>
  );
}

/** What the rule says today, in one or two sentences; the owner reads the sell line as theirs. */
function Now({ r, owned }: { r: Ride; owned: boolean }) {
  const gain = r.gain == null ? null : <b className={signTone(r.gain)}>{signedPct(r.gain, 0)}</b>;
  const today = (d: string | null) => d != null && d === r.last_date;
  switch (r.status) {
    case "buy_next":
      return r.same_day ? (
        <p>
          نشانهٔ ورود در {jalali(r.signal_date, "short")} با قیمت پایانی {rial(r.signal_close)} آمد،
          ولی آن روز صف خرید بود. طبق قاعده، خرید با قیمت پایانی اولین روزی است که صف باز شود (تا ۲۰
          روز معاملاتی). از روز خرید، خط فروش {faPercent(r.trail, 0)} زیر بالاترین قیمت پایانی خواهد
          بود.
        </p>
      ) : (
        <p>
          نشانهٔ ورود در {jalali(r.signal_date, "short")} با قیمت پایانی {rial(r.signal_close)} آمد.
          طبق قاعده، خرید با قیمت پایانی روز معاملاتی بعد است؛ اگر آن روز صف خرید باشد، تا ۲۰ روز
          منتظر باز شدن صف می‌ماند.
        </p>
      );
    case "open": {
      const room = r.stop ? r.last_close / r.stop - 1 : null;
      return (
        <>
          <p>
            {today(r.entry_date) ? (
              <>
                نشانهٔ ورود امروز آمد و قاعده با قیمت پایانی امروز ({rial(r.entry_close)}) خرید کرد.
                کسی که امروز نخرید، فردا هم می‌تواند بخرد؛ در آزمون، خرید یک روز دیرتر کمی کمتر سود
                داد.
              </>
            ) : (
              <>
                قاعده در {jalali(r.entry_date, "short")} با {rial(r.entry_close)} خرید کرد. بالاترین
                قیمت پایانی از آن روز {rial(r.peak_close)} در {jalali(r.peak_date, "short")} بوده و
                سود تا امروز {gain} است (پیش از کارمزد).
              </>
            )}
          </p>
          <p className="mt-2 text-lg font-bold" data-testid="ride-stop">
            خط فروش: {rial(r.stop)}
          </p>
          <p className="text-sm">
            {owned
              ? r.same_day
                ? "اگر قیمت یک روز تا نزدیک پایان بازار زیر این خط باشد، قاعده فروش را در دقایق آخر همان روز می‌گوید، پیش از آنکه صف فروش ببندد. با بالا رفتن قیمت، خط هم بالا می‌آید."
                : "اگر قیمت پایانی یک روز زیر این خط بیاید، قاعده فروش را با قیمت پایانی روز بعد می‌گوید. با بالا رفتن قیمت، خط هم بالا می‌آید."
              : "برای کسی که این سهم را ندارد: قاعده فقط روز شروع حرکت وارد می‌شود و آن روز گذشته است. صبر تا نشانهٔ بعد."}
            {room != null && room >= 0 && <> قیمت امروز {faPercent(room, 0)} بالای خط فروش است.</>}
          </p>
        </>
      );
    }
    case "sell_next":
      return (
        <p>
          قیمت پایانی {jalali(r.exit_signal_date, "short")} زیر خط فروش ({rial(r.stop)}) رفت
          {r.same_day ? "، ولی آن روز صف فروش بود" : ""}.{" "}
          {owned
            ? r.same_day
              ? "قاعده فروش را با قیمت پایانی اولین روزی می‌گوید که صف فروش باز شود."
              : "قاعده فروش را با قیمت پایانی روز معاملاتی بعد می‌گوید؛ اگر صف فروش باشد، روز اولی که صف باز شود."
            : "برای کسی که این سهم را ندارد، این روزها زمان ورود نیست."}{" "}
          سود این دوره تا امروز {gain} (پیش از کارمزد).
        </p>
      );
    case "closed":
      return (
        <>
          <p>
            {today(r.exit_date) ? (
              <>
                قیمت امروز زیر خط فروش رفت و قاعده با قیمت پایانی امروز ({rial(r.exit_close)})
                فروخت؛ این دوره از خرید در {jalali(r.entry_date, "short")} {gain} بود (پیش از
                کارمزد).{owned && " اگر امروز نفروختی، قاعده فروش را فردا می‌گوید."}
              </>
            ) : (
              <>
                آخرین دوره: خرید در {jalali(r.entry_date, "short")} با {rial(r.entry_close)}، فروش
                در {jalali(r.exit_date, "short")} با {rial(r.exit_close)}، یعنی {gain} (پیش از
                کارمزد). از آن روز{" "}
                {r.days_since_exit != null &&
                  `${faNumber(r.days_since_exit)} روز معاملاتی گذشته و `}
                نشانهٔ ورود تازه‌ای نیامده است{owned ? "." : "؛ صبر تا نشانهٔ بعد."}
              </>
            )}
          </p>
          {r.buy_trigger != null && !rideStale(r) && <Trigger r={r} />}
        </>
      );
  }
}

function Past({ h, years }: { h: Block; years: number }): ReactNode {
  return (
    <>
      در {faNumber(years)} سال اخیر این قاعده {faNumber(h.n)} بار روی سهم‌های پرمعامله خرید کرد (
      {faNumber(h.open)} دوره هنوز باز است و با قیمت امروز حساب شده). از هر ۱۰۰ بار{" "}
      <b>{per100(h.win)}</b> بار پس از کارمزد سود داد؛ دورهٔ وسط (میانه){" "}
      <b className={signTone(h.net_median)}>{signedPct(h.net_median, 0)}</b> بود و میانگین{" "}
      <b className={signTone(h.excess_mean)}>
        {faPercent(Math.abs(h.excess_mean), 1)} {h.excess_mean >= 0 ? "بیشتر" : "کمتر"}
      </b>{" "}
      از بازار در همان روزها. نگهداری وسط {faNumber(h.hold_median)} روز معاملاتی بود.
    </>
  );
}

/** The trend-ride hint: buy near the start of a run, sell when a close falls a third below the
 *  highest close since the buy (docs/reports/trend-ride-2026-11.md). */
export function TrendRideCard({
  r,
  instrumentId,
  fundNote,
}: {
  r: Ride;
  instrumentId: number;
  /** for a fund: what testing the rule on funds showed; the stock study below is then left out */
  fundNote?: string;
}) {
  const owned = useOwned(instrumentId);
  const g = GRADE[r.grade];
  const h = r.history;
  return (
    <section className="card" data-testid="trend-ride" data-status={r.status}>
      <h2 className="mb-1 font-bold">ورود و خروج روند</h2>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={`pill ${g.cls}`}>شواهد: {g.label}</span>
        <span className="text-sm text-muted">
          {fundNote
            ? "روی صندوق‌ها آزموده شد و از نگه‌داشتنِ ساده بهتر نبود"
            : "قاعدهٔ آزموده، توصیه نیست"}
        </span>
      </div>
      {fundNote && (
        <p className="mb-2 rounded-lg bg-warn-soft p-3 text-sm" data-testid="fund-ride-note">
          {faDigits(fundNote)} رتبه‌بندی مدل، توصیه نیست.
        </p>
      )}
      {rideStale(r) && (
        <p className="mb-2 rounded-lg bg-warn-soft p-3 text-sm" data-testid="ride-stale">
          این سهم از {jalali(r.last_date)} معامله نشده است. آنچه در ادامه می‌آید وضعیت قاعده در
          آخرین روز معامله است؛ تا سهم دوباره معامله نشود، نشانهٔ خرید یا فروشی نمی‌آید.
        </p>
      )}
      <Now r={r} owned={owned} />
      <Warn r={r} owned={owned} />
      {h && (
        <p className="mt-3 text-sm" data-testid="ride-history">
          <Past h={h} years={r.history_years} />
        </p>
      )}
      <details className="mt-3 text-sm text-muted">
        <summary className="cursor-pointer font-semibold">قاعده و آزمونش</summary>
        <p className="mt-1">
          نشانهٔ ورود روز اولی است که قیمت پایانی بالای میانگین ۵۰ روزه باشد، میانگین ۵۰ روزه بالای
          میانگین ۲۰۰ روزه، و قیمت حداکثر {faPercent(r.near_high, 0)} زیر بالاترین قیمت ۲۵۰ روز. خط
          فروش {faPercent(r.trail, 0)} زیر بالاترین قیمت پایانی از روز خرید است. دوره پس از{" "}
          {faNumber(r.max_hold_days)} روز معاملاتی تمام می‌شود، مگر روند هنوز برقرار باشد (قیمت
          بالای میانگین ۵۰ و میانگین ۵۰ بالای ۲۰۰)؛ آن‌وقت دوره ادامه دارد و شمارش و بالاترین قیمت
          از همان روز از نو حساب می‌شود. همهٔ قیمت‌ها تعدیل‌شده‌اند.
        </p>
        {!fundNote && (
          <>
            <p className="mt-1">
              «کف» و «سقف» روی نمودار را فقط بعداً می‌شد دید: بعد از هرکدام قیمت دست‌کم{" "}
              {faPercent(r.trail, 0)} برگشته است. این قاعده نمی‌تواند در کف بخرد: در سه سال اخیر
              خریدش در میانه ۵۷٪ بالاتر از کمترین قیمت ۱۲۰ روز قبل بود و فروشش ۳۶٪ زیر بالاترین قیمت
              دوره. خرید زودتر (شکست سقف ۶۰ روزه، روز جهش پرحجم)، خط فروش تنگ‌تر یا فروش زودتر با
              «هشدار» در آزمون سود را کم کرد.
            </p>
            <p className="mt-1">
              زمان خرید و فروش: در سه سال اخیر روز بعد از ۱۸٪ نشانه‌ها صف خرید بود و آن خریدها
              به‌طور میانگین ۱۳٪ بالاتر از قیمت نشانه انجام شد؛ روز بعد از ۱۷٪ شکستن‌های خط هم صف
              فروش بود و آن فروش‌ها ۸٪ پایین‌تر از قیمت روز شکست انجام شد. خرید با قیمت پایانی همان
              روز نشانه و فروش با قیمت پایانی همان روزی که خط شکست، به‌جای روز بعد، در هر دو نیمهٔ سه
              سال اخیر و از ۱۳۹۰ سود بیشتری داد؛ در سه سال اخیر کم (حدود ۰.۴ و ۲ واحد درصد برای هر
              سهم)، از ۱۳۹۰ بیشتر. در عمل یعنی سفارش در دقایق آخر بازار با قیمت لحظه‌ای؛ آزمون با
              قیمت آخرین معامله همان نتیجه را داد. اگر خود روز نشانه صف خرید باشد، این راه هم کمکی
              نمی‌کند.
            </p>
            <p className="mt-1">
              آزمون پاک‌سازی آینده: همهٔ نشانه‌ها با حذف داده‌های بعد از چهار تاریخ گذشته دوباره
              ساخته شدند و هیچ‌کدام از دادهٔ بعد از روز خودش استفاده نکرده بود. تنها اختلاف، خطای گرد
              کردن در سهم‌های متوقف بود که درست شد. خط فروش ۳۵٪ در هر دو بازهٔ زمانی و هر دو نیمه از
              ۲۵٪ سود بیشتر داد؛ بخشی از این سود از «بیشتر در روند ماندن» در بازار صعودی است.
            </p>
            <p className="mt-1">
              در سه سال اخیر روی ۳۰۰ سهم پرمعامله، این ورود با همین خروج در هر دو نیمهٔ دوره از خرید
              در روزهای تصادفی بهتر بود؛ ولی از ۱۳۸۸ تا ۱۳۹۷ نبود، و سال‌های اخیر بیشتر بازار صعودی
              بوده. برای همین درجه‌اش «احتمالی» است. در روزهای جهش، صف خرید معمولاً خرید را ناممکن
              می‌کند.
            </p>
          </>
        )}
        {h && h.halves.length === 2 && (
          <p className="mt-1">
            نیمهٔ اول ({jalali(h.first, "short")} تا {jalali(h.split_date, "short")}): میانگین{" "}
            {signedPct(h.halves[0].excess_mean)} نسبت به بازار، {per100(h.halves[0].win)} از ۱۰۰ با
            سود. نیمهٔ دوم: {signedPct(h.halves[1].excess_mean)}، {per100(h.halves[1].win)} از ۱۰۰ با
            سود، و {faNumber(h.halves[1].open)} دوره از {faNumber(h.halves[1].n)} هنوز باز.
          </p>
        )}
      </details>
    </section>
  );
}
