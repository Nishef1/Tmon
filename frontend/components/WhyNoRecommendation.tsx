import Link from "next/link";
import type { Diagnosis, Gate } from "@/lib/api";
import { Num } from "@/components/Num";
import { faDigits } from "@/lib/format";

const FAILED_LABEL: Record<string, string> = {
  bucket: "نمونهٔ گذشتهٔ گروه احتمالش کم است",
  ev: "سود خالص مورد انتظارش از حداقل لازم کمتر است",
  p_min: "احتمال موفقیتش از حداقل لازم کمتر است",
};

const DROP_LABEL: Record<string, string> = {
  liquidity: "نقدشوندگی کم (معامله‌پذیری پایین)",
  correlation: "همبستگی زیاد با نماد انتخاب‌شده",
  sector_cap: "سقف سهم یک صنعت در سبد",
  max_positions: "سقف تعداد سهم‌های سبد",
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
        دلیل این نتیجه برای این اجرا ذخیره نشده است، چون اجرا پیش از افزودن این گزارش انجام شده
        بود. با اجرای بعدی چرخهٔ روزانه، عددها اینجا نمایش داده می‌شوند.
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
          <strong>بیشترین نماد را این مرحله حذف کرد:</strong> «{faDigits(binding.label)}»؛{" "}
          <Num term="candidates" value={binding.lost} kind="count" /> نماد از{" "}
          <Num term="candidates" value={d.universe} kind="count" /> نماد در همین مرحله کنار رفتند.
        </p>
      )}

      {d && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[22rem] text-right" data-testid="funnel">
            <caption className="pb-1 text-start text-muted">
              مراحل تصمیم امروز؛ هر ردیف شرط‌های ردیف‌های قبل را هم دارد
            </caption>
            <thead>
              <tr className="border-b border-line text-muted">
                <th>شرط</th>
                <th>باقی‌مانده</th>
                <th>حذف‌شده</th>
                <th>اگر فقط همین شرط بود</th>
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
            احتمال موفقیت نمادها: بیشترین <Num term="p_win" value={st.p_win_max} kind="percent" digits={1} /> و میانه{" "}
            <Num term="p_win" value={st.p_win_median} kind="percent" digits={1} />. میانهٔ حداقل احتمالِ لازم{" "}
            <Num term="p_win" value={st.p_min_median} kind="percent" digits={1} /> است؛ این عدد از نقطهٔ
            سربه‌سر (<Num term="p_win" value={st.p_breakeven_median} kind="percent" digits={1} />) به‌اضافهٔ
            حاشیهٔ اطمینان <Num term="p_win" value={d.margin} kind="percent" digits={0} /> ساخته می‌شود و
            هرگز کمتر از <Num term="p_win" value={d.p_floor} kind="percent" digits={0} /> نیست.
          </li>
          <li>
            سود خالص مورد انتظار: بیشترین{" "}
            <Num term="ev" value={st.ev_max} kind="percent" digits={2} />
            ، میانه <Num term="ev" value={st.ev_median} kind="percent" digits={2} />؛ حداقل لازم{" "}
            <Num term="ev" value={d.ev_min_abs} kind="percent" digits={2} />. نمادهای با سود مثبت:{" "}
            <Num term="candidates" value={st.n_ev_positive} kind="count" />.
          </li>
          <li>
            تعداد عددهای متفاوتی که مدل به‌عنوان احتمال موفقیت به نمادها داده است:{" "}
            <Num term="p_win" value={st.n_distinct_p_win} kind="count" />
            {st.n_distinct_p_win <= 3 && (
              <>
                {" "}
                ؛ یعنی مدل امروز تقریباً همهٔ نمادها را یک‌جور امتیاز داده و نمادها را از هم جدا نمی‌کند.
              </>
            )}
          </li>
          {Object.keys(d.dropped_by_portfolio).length > 0 && (
            <li>
              نمادهایی که قید پرتفوی کنارشان گذاشت:{" "}
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
              نمادهایی که به قبول‌شدن نزدیک‌تر بودند (از بین ردشده‌ها، بیشترین سود مورد انتظار را دارند)
            </caption>
            <thead>
              <tr className="border-b border-line text-muted">
                <th>نماد</th>
                <th>احتمال موفقیت</th>
                <th>حداقل لازم</th>
                <th>چقدر کم است</th>
                <th>سود خالص</th>
                <th>چرا رد شد</th>
              </tr>
            </thead>
            <tbody>
              {d.nearest.map((m, i) => (
                <tr key={m.instrument?.id ?? i} className="border-b border-line/60">
                  <td className="py-1">
                    {m.instrument ? (
                      <>
                        <Link href={`/instruments/${m.instrument.id}`} className="text-accent">
                          {m.instrument.symbol}
                        </Link>
                        {m.instrument.name && (
                          <div className="text-xs text-muted">{m.instrument.name}</div>
                        )}
                      </>
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
          <p className="font-semibold">نتیجهٔ آزمون روی گذشته (خارج از نمونهٔ آموزش و پس از کسر هزینه):</p>
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
