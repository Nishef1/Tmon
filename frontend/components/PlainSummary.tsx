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
              سهم‌هایی که در همین حالت بودند، در دو ماه اول بعد از خرید معمولاً تا{" "}
              <b className="text-down">{faPercent(-t.state.mae60_median, 0)}</b> پایین‌تر از قیمت
              خرید هم رفتند
              {t.state.mae60_p10 != null && (
                <>
                  ؛ در بدترین ۱ مورد از هر ۱۰ مورد تا{" "}
                  <b className="text-down">{faPercent(-t.state.mae60_p10, 0)}</b>
                </>
              )}
              . یعنی حتی اگر آخرش سود بدهد، باید تحمل این افت موقت را داشته باشید.
            </dd>
          </div>
        )}
      </dl>
      {d.entry && d.entry.own.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <h3 className="mb-1 text-sm text-muted">کندل‌های بعدی چه می‌شوند؟</h3>
          <p className="mb-2 text-xs text-muted" data-testid="candles-vs-verdict">
            اینجا فقط قیمت خود سهم است. «نگهداری» در بالا یعنی ثابت نشده که این سهم از کل بازار جلو
            بزند، حتی اگر قیمتش احتمالاً بالا برود.
          </p>
          <NextCandles e={d.entry} />
        </div>
      )}
    </div>
  );
}
