import type { InstrumentDashboard } from "@/lib/api";
import { faPercent } from "@/lib/format";
import { NextCandles } from "@/components/entry/NextCandles";

type D = InstrumentDashboard;

/** One word for how far the past evidence can be trusted (t is the statistical strength). */
export function trustWord(t: number | null | undefined): string | null {
  if (t == null) return null;
  return t >= 3 ? "زیاد" : t >= 2 ? "متوسط" : "کم";
}

/** The plain answers under the decision: how sure, how deep the dip and the next
 * candles. How similar stocks did in six months is in the synthesis and the state card; the verdict itself lives in the decision card above; nothing is repeated here. */
export function PlainFacts({ d }: { d: D }) {
  const v = d.decision.verdict;
  const t = d.turning;
  return (
    <div data-testid="plain-summary" data-verdict={v}>
      <dl className="space-y-3">
        {t && t.state.mae60_median != null && (
          <div>
            <dt className="text-sm text-muted">اگر بخرم، چقدر ممکن است اول ضرر ببینم؟</dt>
            <dd className="mt-0.5">
              معمولاً تا <b className="text-down">{faPercent(-t.state.mae60_median, 0)}</b> زیر قیمت
              خرید در دو ماه اول
              {t.state.mae60_p10 != null && (
                <>
                  ؛ در یک‌دهم بدترین موارد تا{" "}
                  <b className="text-down">{faPercent(-t.state.mae60_p10, 0)}</b>
                </>
              )}
              {t.base.mae60_median != null && (
                <> (برای همهٔ سهم‌ها معمولاً {faPercent(-t.base.mae60_median, 0)})</>
              )}
              . این از سابقهٔ سهم‌های هم‌حالت است؛ بیشترین افت خود این سهم در یک سال اخیر در بخش
              ریسک آمده.
            </dd>
          </div>
        )}
      </dl>
      {d.entry && d.entry.own.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <h3 className="mb-1 text-sm text-muted">کندل‌های بعدی چه می‌شوند؟</h3>
          <p className="mb-2 text-xs text-muted" data-testid="candles-vs-verdict">
            این کندل‌ها قیمت خود سهم را نشان می‌دهند و چون تورم تقریباً همهٔ قیمت‌ها را بالا می‌برد،
            اغلب رو به سودند. حکم «خرید» سخت‌گیرتر است: سهم باید پس از کسر کارمزد از کل بازار جلو
            بزند و این برتری در آزمون گذشته شانسی نبوده باشد. پس «صبر کنید» کنار کندل سبز یعنی سود
            احتمالی هست، ولی بیشتر از بازار بودنش ثابت نشده؛ وقتی هر دو هم‌جهت‌اند، نشانه محکم‌تر
            است.
          </p>
          <NextCandles e={d.entry} />
        </div>
      )}
      <p className="mt-3 text-xs text-muted">
        این درصدها سابقهٔ سهم‌های مشابه است، نه تضمین آینده. «بازار» یعنی میانگین همهٔ سهم‌های
        پرمعامله در همان روزها.
      </p>
    </div>
  );
}
