import Link from "next/link";
import type { Diagnosis, Gate } from "@/lib/api";
import { Num } from "@/components/Num";
import { faDigits } from "@/lib/format";

const FAILED_LABEL: Record<string, string> = {
  bucket: "نمونهٔ آماری سطل کم است",
  ev: "سود خالص مورد انتظار کمتر از حداقل",
  p_min: "احتمال برد کمتر از حداقل احتمال",
};

const DROP_LABEL: Record<string, string> = {
  liquidity: "نقدشوندگی کم",
  correlation: "همبستگی زیاد با نماد انتخاب‌شده",
  sector_cap: "سقف صنعت",
  max_positions: "سقف تعداد پوزیشن",
};

/**
 * Exact numbers behind "no recommendation": how many symbols each rule removed, the binding rule,
 * the nearest misses with their shortfall, and the out-of-sample gate. Shown whenever a section
 * has nothing to recommend, so an empty list is never an unexplained one.
 */
export function WhyNoRecommendation({
  diagnosis,
  gate,
}: {
  diagnosis: Diagnosis | null;
  gate: Gate | null;
}) {
  if (!diagnosis && !gate) {
    return (
      <p className="mt-3 text-sm text-muted" data-testid="why-missing">
        جزئیات دلیل برای این اجرا ذخیره نشده است (اجرا پیش از افزودن این گزارش انجام شده). با اجرای
        بعدی چرخهٔ روزانه عددها اینجا می‌آیند.
      </p>
    );
  }
  const d = diagnosis;
  const st = d?.stats;
  const binding = d?.stages.find((s) => s.key === d.binding);
  return (
    <div className="mt-4 space-y-4 text-sm" data-testid="why-none">
      {d && binding && (
        <p>
          <strong>مهم‌ترین مانع:</strong> «{binding.label}» که{" "}
          <Num term="candidates" value={binding.lost} kind="count" /> نماد از{" "}
          <Num term="candidates" value={d.universe} kind="count" /> نماد را حذف کرد.
        </p>
      )}

      {d && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[22rem] text-right" data-testid="funnel">
            <caption className="pb-1 text-start text-muted">
              قیف تصمیم امروز (هر ردیف شرط قبلی را هم دارد)
            </caption>
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="py-1 font-normal">مرحله</th>
                <th className="py-1 font-normal">باقی‌مانده</th>
                <th className="py-1 font-normal">حذف‌شده</th>
                <th className="py-1 font-normal">فقط با همین شرط</th>
              </tr>
            </thead>
            <tbody>
              {d.stages.map((s) => (
                <tr
                  key={s.key}
                  className={`border-b border-line/60 ${s.key === d.binding ? "bg-warn-soft" : ""}`}
                >
                  <td className="py-1">{faDigits(s.label)}</td>
                  <td className="py-1">
                    <Num term="candidates" value={s.count} kind="count" />
                  </td>
                  <td className="py-1">
                    {s.key === "universe" ? (
                      "—"
                    ) : (
                      <Num term="candidates" value={s.lost} kind="count" />
                    )}
                  </td>
                  <td className="py-1">
                    <Num term="candidates" value={s.alone} kind="count" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {d && st && (
        <ul className="list-inside list-disc space-y-1" data-testid="why-stats">
          <li>
            بیشترین <Num term="p_win" value={st.p_win_max} kind="percent" digits={1} /> و میانهٔ{" "}
            <Num term="p_win" value={st.p_win_median} kind="percent" digits={1} /> احتمال برد؛
            میانهٔ حداقل لازم <Num term="p_win" value={st.p_min_median} kind="percent" digits={1} />{" "}
            (سربه‌سر <Num term="p_win" value={st.p_breakeven_median} kind="percent" digits={1} />
            ، حاشیه <Num term="p_win" value={d.margin} kind="percent" digits={0} />، کف{" "}
            <Num term="p_win" value={d.p_floor} kind="percent" digits={0} />
            ).
          </li>
          <li>
            بیشترین سود خالص مورد انتظار{" "}
            <Num term="ev" value={st.ev_max} kind="percent" digits={2} />
            ، میانه <Num term="ev" value={st.ev_median} kind="percent" digits={2} />؛ حداقل لازم{" "}
            <Num term="ev" value={d.ev_min_abs} kind="percent" digits={2} />. نمادهای با سود مثبت:{" "}
            <Num term="candidates" value={st.n_ev_positive} kind="count" />.
          </li>
          <li>
            تعداد مقدارهای متمایز احتمال برد بین نمادها:{" "}
            <Num term="p_win" value={st.n_distinct_p_win} kind="count" />
            {st.n_distinct_p_win <= 3 && (
              <>
                {" "}
                — مدل امروز تقریباً همهٔ نمادها را یک‌جور امتیاز داده و نمادها را از هم جدا نمی‌کند.
              </>
            )}
          </li>
          {Object.keys(d.dropped_by_portfolio).length > 0 && (
            <li>
              حذف‌شده در پرتفوی:{" "}
              {Object.entries(d.dropped_by_portfolio).map(([k, v], i) => (
                <span key={k}>
                  {i > 0 && "، "}
                  {DROP_LABEL[k] ?? k} <Num term="candidates" value={v} kind="count" />
                </span>
              ))}
            </li>
          )}
        </ul>
      )}

      {d && d.nearest.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-right" data-testid="near-miss">
            <caption className="pb-1 text-start text-muted">
              نزدیک‌ترین نمادها به عبور (بیشترین سود مورد انتظار بین ردشده‌ها)
            </caption>
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="py-1 font-normal">نماد</th>
                <th className="py-1 font-normal">احتمال برد</th>
                <th className="py-1 font-normal">حداقل لازم</th>
                <th className="py-1 font-normal">کمبود</th>
                <th className="py-1 font-normal">سود خالص</th>
                <th className="py-1 font-normal">دلیل رد</th>
              </tr>
            </thead>
            <tbody>
              {d.nearest.map((m, i) => (
                <tr key={m.instrument?.id ?? i} className="border-b border-line/60">
                  <td className="py-1">
                    {m.instrument ? (
                      <Link href={`/instruments/${m.instrument.id}`} className="text-accent">
                        {m.instrument.symbol}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-1">
                    <Num term="p_win" value={m.p_win} kind="percent" digits={1} />
                  </td>
                  <td className="py-1">
                    <Num term="p_win" value={m.p_min} kind="percent" digits={1} />
                  </td>
                  <td className="py-1">
                    <Num term="p_win" value={m.shortfall} kind="percent" digits={1} />
                  </td>
                  <td className="py-1">
                    <Num term="ev" value={m.ev} kind="percent" digits={2} signed />
                  </td>
                  <td className="py-1">
                    {m.failed.map((f) => FAILED_LABEL[f] ?? f).join("، ") || "—"}
                    {m.failed.includes("bucket") && (
                      <>
                        {" "}
                        (<Num term="sample_size" value={m.bucket_n} kind="count" /> نمونه)
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {gate && !gate.tier_a_allowed && (
        <div data-testid="why-gate">
          <p className="font-semibold">آزمون خارج از نمونه (پس از هزینه) چه می‌گوید:</p>
          <ul className="mt-1 list-inside list-disc space-y-1">
            {gate.reasons.map((r) => (
              <li key={r}>{faDigits(r)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
