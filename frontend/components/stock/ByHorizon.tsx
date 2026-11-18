import type { InstrumentDashboard } from "@/lib/api";
import { faNumber } from "@/lib/format";
import { signedPct } from "@/lib/ui";

type Row = InstrumentDashboard["decision"]["by_horizon"][number];

const STATUS: Record<Row["status"], { word: string; tone: string }> = {
  loss: { word: "بعد از کارمزد زیان‌ده", tone: "text-down" },
  unproven: { word: "ثابت‌نشده", tone: "text-muted" },
  probable: { word: "احتمالی", tone: "text-warn" },
  proven: { word: "ثابت‌شده", tone: "text-up" },
};

const tone = (x: number) => (x >= 0 ? "text-up" : "text-down");

/** The stock's zone measured at every holding period, so the reader sees why the verdict names
 *  one period only (docs/reports/horizon-profile-2026-11.md). */
export function ByHorizon({ rows, band }: { rows: Row[]; band: string | null | undefined }) {
  if (rows.length === 0) return null;
  const avoid = band === "avoid";
  const chosen = rows.find((r) => r.verdict_horizon);
  return (
    <div data-testid="by-horizon">
      <p className="text-sm leading-7 text-muted">
        {avoid
          ? "اگر هر روز از نیمهٔ پایین فهرست پرهیز می‌کردید و به‌جایش بازار را نگه می‌داشتید، بعد از کارمزد به‌طور میانگین این‌قدر جلو بودید:"
          : "اگر هر روز نیمهٔ بالای فهرست را می‌خریدید و این مدت نگه می‌داشتید، بعد از کارمزد به‌طور میانگین این‌قدر از بازار جلو بودید:"}
      </p>
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="border-b border-line text-start text-xs text-muted">
            <th className="py-1 text-start font-normal">نگه‌داری</th>
            <th className="py-1 text-start font-normal">میانگین</th>
            <th className="py-1 text-start font-normal">نیمهٔ اول / دوم</th>
            <th className="py-1 text-start font-normal">شواهد</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.days}
              data-days={r.days}
              data-status={r.status}
              className={`border-b border-line/60 ${r.verdict_horizon ? "bg-accent-soft font-semibold" : ""}`}
            >
              <td className="py-1.5">
                {r.label}
                {r.verdict_horizon && <span className="text-xs text-accent"> (حکم بالا)</span>}
              </td>
              <td className={`py-1.5 tabular-nums ${tone(r.net)}`}>{signedPct(r.net)}</td>
              <td className="py-1.5 tabular-nums">
                <span className={tone(r.net_h1)}>{signedPct(r.net_h1)}</span>
                {" / "}
                <span className={tone(r.net_h2)}>{signedPct(r.net_h2)}</span>
              </td>
              <td className={`py-1.5 ${STATUS[r.status].tone}`}>
                {STATUS[r.status].word}
                <span className="block text-xs font-normal text-muted">
                  {faNumber(r.windows)} دورهٔ جدا در داده
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs leading-6 text-muted">
        {chosen && <>حکم بالا برای {chosen.label} است. </>}
        در بازه‌های کوتاه، کارمزد خرید و فروش بیشتر از سود اضافه بوده است. بازه‌های بلندتر دوره‌های جدای
        کمتری در داده دارند و شواهدشان ضعیف‌تر است. بیشتر این داده از یک دورهٔ صعودی بازار است.
      </p>
    </div>
  );
}
