import type { InstrumentDashboard } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { NextCandles } from "@/components/entry/NextCandles";

type D = InstrumentDashboard;

/** Share of similar past cases that beat the market in six months, or null when unknown. */
function pastWinRate(t: D["turning"]): { rate: number; base: number | null } | null {
  const h = t?.state.horizons.find((x) => x.horizon_days === 120);
  if (!t || !h || h.beat == null) return null;
  const b = t.base.horizons.find((x) => x.horizon_days === 120);
  return { rate: h.beat, base: b?.beat ?? null };
}

function Meter({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  return (
    <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-line" aria-hidden>
      <div
        className={`h-full rounded-full ${rate >= 0.5 ? "bg-up" : "bg-hold"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/** One word for how far the past evidence can be trusted (t is the statistical strength). */
export function trustWord(t: number | null | undefined): string | null {
  if (t == null) return null;
  return t >= 3 ? "زیاد" : t >= 2 ? "متوسط" : "کم";
}

/** The plain answers under the decision: how sure, how deep the dip, place in the group, and the
 * next candles. The verdict itself lives in the decision card above; nothing is repeated here. */
export function PlainFacts({ d }: { d: D }) {
  const v = d.decision.verdict;
  const win = pastWinRate(d.turning);
  const t = d.turning;
  const per100 = win ? Math.round(win.rate * 100) : null;
  const clash =
    t && v === "buy" && t.state.tone === "down"
      ? "امتیاز سهم بالاست، ولی سهم‌هایی که در همین وضعیت بودند در گذشته اغلب از بازار عقب ماندند. این دو را کنار هم ببینید."
      : t && v === "sell" && t.state.tone === "up"
        ? "امتیاز سهم پایین است، ولی سهم‌هایی که در همین وضعیت بودند در گذشته اغلب از بازار جلو زدند."
        : null;
  const peers = d.peers;
  return (
    <div data-testid="plain-summary" data-verdict={v}>
      <dl className="space-y-3">
        {win && per100 != null && (
          <div data-testid="plain-winrate">
            <dt className="text-sm text-muted">چقدر می‌شود مطمئن بود؟</dt>
            <dd className="mt-0.5">
              از هر ۱۰۰ سهمِ هم‌وضعیت، <b>{faNumber(per100)}</b> تا در شش ماه بعد از بازار بهتر شدند
              {win.base != null && <> (همهٔ سهم‌ها: {faNumber(Math.round(win.base * 100))})</>}.
              <Meter rate={win.rate} />
            </dd>
          </div>
        )}
        {t && t.state.mae60_median != null && (
          <div>
            <dt className="text-sm text-muted">اگر بخرم، چقدر ممکن است اول ضرر ببینم؟</dt>
            <dd className="mt-0.5">
              معمولاً تا <b className="text-down">{faPercent(-t.state.mae60_median, 0)}</b> زیر قیمت
              خرید در دو ماه اول
              {t.state.mae60_p10 != null && (
                <>
                  ؛ در بدترین حالت‌ها تا{" "}
                  <b className="text-down">{faPercent(-t.state.mae60_p10, 0)}</b>
                </>
              )}
              .
            </dd>
          </div>
        )}
        {peers && peers.position != null && (
          <div>
            <dt className="text-sm text-muted">در گروه خودش چطور است؟</dt>
            <dd className="mt-0.5">
              {peers.position === 1
                ? `بهترین امتیاز میان ${faNumber(peers.scored)} سهم گروه.`
                : `رتبهٔ ${faNumber(peers.position)} از ${faNumber(peers.scored)}؛ بهترین گروه ${peers.items[0]?.symbol ?? ""} است.`}
            </dd>
          </div>
        )}
      </dl>
      {d.entry && d.entry.own.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <h3 className="mb-1 text-sm text-muted">کندل‌های بعدی چه می‌شوند؟</h3>
          <NextCandles e={d.entry} />
        </div>
      )}
      {clash && (
        <p className="mt-3 rounded-lg bg-warn-soft p-2 text-sm" data-testid="plain-clash">
          {clash}
        </p>
      )}
      <p className="mt-3 text-xs text-muted">
        این درصدها سابقهٔ سهم‌های مشابه است، نه تضمین آینده. «بازار» یعنی میانگین همهٔ سهم‌های
        پرمعامله در همان روزها.
      </p>
    </div>
  );
}
