"use client";

import type { ReactNode } from "react";
import { faNumber, faPercent, faPrice, jalali } from "@/lib/format";
import { signedPct, signTone } from "@/lib/ui";
import { useOwned } from "@/components/stock/HoldWord";
import type { Ride } from "@/components/stock/rideMarks";

type Block = NonNullable<Ride["history"]>["halves"][number];

const GRADE: Record<Ride["grade"], { label: string; cls: string }> = {
  proven: { label: "اثبات‌شده", cls: "v-buy" },
  probable: { label: "احتمالی", cls: "v-hold" },
  unproven: { label: "آزموده‌نشده", cls: "v-none" },
};

const rial = (n: number | null | undefined) => (n == null ? "—" : `${faPrice(n)} ریال`);
const range = (lo: number | null | undefined, hi: number | null | undefined) =>
  lo == null || hi == null ? null : `${faPrice(lo)} تا ${faPrice(hi)} ریال`;
const per100 = (n: number) => faNumber(Math.round(n * 100));

/** What the rule says today, in one or two sentences; the owner reads the sell line as theirs. */
function Now({ r, owned }: { r: Ride; owned: boolean }) {
  const gain = r.gain == null ? null : <b className={signTone(r.gain)}>{signedPct(r.gain, 0)}</b>;
  switch (r.status) {
    case "buy_next":
      return (
        <p>
          نشانهٔ ورود در {jalali(r.signal_date, "short")} با قیمت پایانی {rial(r.signal_close)} آمد.
          طبق قاعده، خرید با قیمت پایانی روز معاملاتی بعد است؛ اگر آن روز صف خرید باشد، تا ۲۰ روز
          منتظر باز شدن صف می‌ماند. از روز خرید، خط فروش {faPercent(r.trail, 0)} زیر بالاترین قیمت
          پایانی خواهد بود.
          {range(r.buy_low, r.buy_high) && (
            <>
              {" "}
              <b data-testid="ride-buy-range">رنج خرید: {range(r.buy_low, r.buy_high)}</b>؛ در ۸۰٪
              دوره‌های گذشته خرید در همین بازه نشست. صبر برای ارزان‌تر شدن سود نداشت: سفارش پایین‌تر
              از قیمت پایانی نشانه در هر دو نیمه بدتر از خرید روز بعد بود، چون سهم‌هایی که بالا
              می‌روند معمولاً برنمی‌گردند.
            </>
          )}
        </p>
      );
    case "open": {
      const room = r.stop ? r.last_close / r.stop - 1 : null;
      return (
        <>
          <p>
            قاعده در {jalali(r.entry_date, "short")} با {rial(r.entry_close)} خرید کرد. بالاترین
            قیمت پایانی از آن روز {rial(r.peak_close)} در {jalali(r.peak_date, "short")} بوده و سود
            تا امروز {gain} است (پیش از کارمزد).
          </p>
          <p className="mt-2 text-lg font-bold" data-testid="ride-stop">
            خط فروش: {rial(r.stop)}
          </p>
          {range(r.stop_low, r.stop_high) && (
            <p className="text-sm" data-testid="ride-sell-range">
              رنج فروش: {range(r.stop_low, r.stop_high)}. در ۸۰٪ فروش‌های گذشته، قیمت فروش (پایانی
              روز بعد از شکستن خط) در همین بازه نشست؛ یعنی از خط فروش حدود ۸٪ پایین‌تر تا ۲٪ بالاتر.
            </p>
          )}
          <p className="text-sm">
            {owned
              ? "اگر قیمت پایانی یک روز زیر این خط بیاید، قاعده فروش را با قیمت پایانی روز بعد می‌گوید. با بالا رفتن قیمت، خط هم بالا می‌آید."
              : "برای کسی که این سهم را ندارد: قاعده فقط روز شروع حرکت وارد می‌شود و آن روز گذشته است. صبر تا نشانهٔ بعد."}
            {room != null && room >= 0 && <> قیمت امروز {faPercent(room, 0)} بالای خط فروش است.</>}
          </p>
        </>
      );
    }
    case "sell_next":
      return (
        <p>
          قیمت پایانی {jalali(r.exit_signal_date, "short")} زیر خط فروش ({rial(r.stop)}) رفت.{" "}
          {owned
            ? "قاعده فروش را با قیمت پایانی روز معاملاتی بعد می‌گوید؛ اگر صف فروش باشد، روز اولی که صف باز شود."
            : "برای کسی که این سهم را ندارد، این روزها زمان ورود نیست."}{" "}
          سود این دوره تا امروز {gain} (پیش از کارمزد).
        </p>
      );
    case "closed":
      return (
        <p>
          آخرین دوره: خرید در {jalali(r.entry_date, "short")} با {rial(r.entry_close)}، فروش در{" "}
          {jalali(r.exit_date, "short")} با {rial(r.exit_close)}، یعنی {gain} (پیش از کارمزد). از آن
          روز {r.days_since_exit != null && `${faNumber(r.days_since_exit)} روز معاملاتی گذشته و `}
          نشانهٔ ورود تازه‌ای نیامده است{owned ? "." : "؛ صبر تا نشانهٔ بعد."}
        </p>
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
export function TrendRideCard({ r, instrumentId }: { r: Ride; instrumentId: number }) {
  const owned = useOwned(instrumentId);
  const g = GRADE[r.grade];
  const h = r.history;
  return (
    <section className="card" data-testid="trend-ride" data-status={r.status}>
      <h2 className="mb-1 font-bold">ورود و خروج روند</h2>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={`pill ${g.cls}`}>شواهد: {g.label}</span>
        <span className="text-sm text-muted">قاعدهٔ آزموده، توصیه نیست</span>
      </div>
      <Now r={r} owned={owned} />
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
        <p className="mt-1">
          «کف» و «سقف» روی نمودار را فقط بعداً می‌شد دید: بعد از هرکدام قیمت دست‌کم{" "}
          {faPercent(r.trail, 0)} برگشته است. این قاعده نمی‌تواند در کف بخرد: در سه سال اخیر خریدش
          در میانه ۶۰٪ بالاتر از کمترین قیمت ۱۲۰ روز قبل بود و فروشش ۳۴٪ زیر بالاترین قیمت دوره.
          خرید زودتر یا خط فروش تنگ‌تر در آزمون سود را کم کرد.
        </p>
        <p className="mt-1">
          خط فروش ۳۵٪ (به‌جای ۲۵٪) و دو رنج آمده‌اند: در هر دو بازهٔ زمانی (سه سال اخیر و از ۱۳۹۰) و
          در هر دو نیمه، خط ۳۵٪ از ۲۵٪ سود بیشتر داد. این سود بیشتر بخشی‌اش «بیشتر در روند ماندن» در
          بازار صعودی است. رنج‌ها بازهٔ ۸۰٪ از دوره‌های گذشته‌اند، نه تضمین؛ در آزمون بیرون از نمونه
          ۷۵ تا ۸۵٪ را پوشش دادند.
        </p>
        <p className="mt-1">
          در سه سال اخیر روی ۳۰۰ سهم پرمعامله، این ورود با همین خروج در هر دو نیمهٔ دوره از خرید در
          روزهای تصادفی بهتر بود؛ ولی از ۱۳۸۸ تا ۱۳۹۷ نبود، و سال‌های اخیر بیشتر بازار صعودی بوده.
          برای همین درجه‌اش «احتمالی» است. در روزهای جهش، صف خرید معمولاً خرید را ناممکن می‌کند.
        </p>
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
