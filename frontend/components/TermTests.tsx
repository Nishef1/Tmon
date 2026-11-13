import type { TaSignal, TaSignals } from "@/lib/api";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";

const LABEL_FA: Record<TaSignal["label"], string> = {
  works: "کار کرده",
  direction_only: "فقط جهت را درست گفته",
  reverse_small: "کمی برعکس",
  backfires: "برعکس",
  no_edge: "برتری نداشته",
  too_few: "نمونهٔ کم",
};

const pct = (x: number | null | undefined, d = 1) => (x == null ? "—" : faPercent(x, d, true));

function One({ s, cost }: { s: TaSignal; cost: number }) {
  return (
    <article className="tile space-y-2" data-testid="term-test">
      <h3 className="font-bold">
        <span className={s.side === "buy" ? "text-up" : "text-down"}>
          {s.side === "buy" ? "نشانهٔ خرید" : "نشانهٔ فروش"}:
        </span>{" "}
        {s.title} <span className="chip text-xs font-normal">{LABEL_FA[s.label]}</span>
      </h3>
      <p className="text-sm leading-7">{faDigits(s.verdict)}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-center text-sm">
          <thead className="text-muted">
            <tr>
              <th className="py-1 text-start font-normal">چند کندل بعد</th>
              <th className="py-1 font-normal">بازده نسبت به بقیهٔ سهم‌ها</th>
              <th className="py-1 font-normal">نیمهٔ اول / دوم تاریخچه</th>
              <th className="py-1 font-normal">بالا رفته (بقیه)</th>
              <th className="py-1 font-normal">سال‌های درست</th>
            </tr>
          </thead>
          <tbody>
            {s.horizons.map((h) => (
              <tr key={h.h} className="border-t border-line">
                <td className="py-1 text-start">{faNumber(h.h)}</td>
                <td className="py-1" dir="ltr">
                  {pct(h.excess_mean)}
                </td>
                <td className="py-1" dir="ltr">
                  {pct(h.halves[0])} / {pct(h.halves[1])}
                </td>
                <td className="py-1">
                  {faNumber(100 * h.up)} ({faNumber(100 * h.up_all)}) از ۱۰۰
                </td>
                <td className="py-1">
                  {h.years_pos == null
                    ? "—"
                    : `${faNumber(100 * (s.side === "buy" ? h.years_pos : 1 - h.years_pos))} از ۱۰۰`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        {faNumber(s.n)} بار در {faNumber(s.symbols)} نماد. کارمزد رفت‌وبرگشت {faPercent(cost, 1)}{" "}
        است؛{" "}
        {s.side === "buy"
          ? "بازدهِ اضافهٔ کمتر از آن یعنی بعد از کارمزد سودی نمانده."
          : "فروختن و بعد دوباره خریدن فقط وقتی می‌ارزد که سهم بیش از این مقدار عقب بماند."}
        {s.locked_share != null &&
          s.locked_share > 0.05 &&
          ` ${faNumber(100 * s.locked_share)} از ۱۰۰ بار فردای نشانه سهم در صف بود و قابل معامله نبود؛ آن روزها کنار گذاشته شده‌اند` +
            (s.x20_with_locked != null
              ? ` (با آن‌ها بازده ۲۰ کندل ${faPercent(s.x20_with_locked, 1, true)} می‌شد).`
              : ".")}
      </p>
    </article>
  );
}

/** How every classic reading of a glossary term did on the whole TSETMC history. */
export function TermTests({ term, doc }: { term: string; doc: TaSignals | null }) {
  const sigs = doc?.available ? doc.signals.filter((s) => s.term === term) : [];
  if (!doc || sigs.length === 0) return null;
  const cost = doc.round_trip_cost ?? 0;
  return (
    <section className="space-y-3" data-testid="term-tests">
      <h2 className="font-bold">در آزمون ما: کی خرید، کی فروش، چند کندل بعد؟</h2>
      <p className="text-sm leading-7 text-muted">
        هر خوانش کتابی روی همهٔ نمادهای پرمعاملهٔ بورس تهران از {jalali(doc.history_first)} تا{" "}
        {jalali(doc.history_last)} با قیمت تعدیل‌شده آزموده شده: ورود با پایانی فردای نشانه، و
        مقایسه با بقیهٔ سهم‌هایی که همان روز قابل خرید بودند. نیمهٔ اول تا {jalali(doc.split_date)}{" "}
        است؛ نتیجه‌ای که فقط در یک نیمه دیده شود به حساب نمی‌آید.
      </p>
      {sigs.map((s) => (
        <One key={s.key} s={s} cost={cost} />
      ))}
      <p className="text-xs text-muted">
        این شرح گذشته است، نه پیش‌بینی و نه توصیه. برای فروش، بازده منفی نسبت به بقیه یعنی نشانه
        درست گفته است.
      </p>
    </section>
  );
}
