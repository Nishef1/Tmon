import type { InstrumentDashboard } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { verdictPill, verdictTone } from "@/lib/ui";

type D = InstrumentDashboard;

const ACTION: Record<string, string> = {
  buy: "خرید",
  hold: "صبر کنید (اگر دارید نگه دارید)",
  sell: "نخرید (اگر دارید فروش را بررسی کنید)",
  none: "نظری نیست",
};

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

/** The whole page in four plain lines: what to do, how often it worked before, the usual dip
 * after buying, and the place in the group. No jargon; every number comes from the cards below. */
export function PlainSummary({ d }: { d: D }) {
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
    <section className={`card ${verdictTone(v)}`} data-testid="plain-summary" data-verdict={v}>
      <h2 className="mb-2 font-bold">خلاصه به زبان ساده</h2>
      <dl className="space-y-3">
        <div>
          <dt className="text-sm text-muted">چه کنم؟</dt>
          <dd className="mt-0.5 flex flex-wrap items-center gap-2">
            <span className={`${verdictPill(v)} pill-lg`}>{ACTION[v] ?? ACTION.none}</span>
          </dd>
        </div>
        {win && per100 != null && (
          <div data-testid="plain-winrate">
            <dt className="text-sm text-muted">چقدر می‌شود مطمئن بود؟</dt>
            <dd className="mt-0.5">
              در گذشته از هر ۱۰۰ سهمی که در همین وضعیت بودند، <b>{faNumber(per100)}</b> تا در شش ماه
              بعد از میانگین بازار بهتر شدند
              {win.base != null && (
                <> (برای همهٔ سهم‌ها {faNumber(Math.round(win.base * 100))} تا)</>
              )}
              .
              <Meter rate={win.rate} />
            </dd>
          </div>
        )}
        {t && t.state.mae60_median != null && (
          <div>
            <dt className="text-sm text-muted">اگر الان بخرم، چقدر ممکن است اول ضرر ببینم؟</dt>
            <dd className="mt-0.5">
              معمولاً تا <b className="text-down">{faPercent(-t.state.mae60_median, 0)}</b> پایین‌تر
              از قیمت خرید در دو ماه اول.
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
      {clash && (
        <p className="mt-3 rounded-lg bg-warn-soft p-2 text-sm" data-testid="plain-clash">
          {clash}
        </p>
      )}
      <p className="mt-3 text-xs text-muted">
        این درصدها سابقهٔ سهم‌های مشابه در گذشته است، نه تضمین آیندهٔ همین سهم.
        {!d.decision.advice_allowed &&
          " مدل هنوز همهٔ آزمون‌های اعتبار را پاس نکرده؛ قطعی نگیرید."}{" "}
        «بازار» یعنی میانگین همهٔ سهم‌های پرمعامله در همان روزها.
      </p>
    </section>
  );
}
