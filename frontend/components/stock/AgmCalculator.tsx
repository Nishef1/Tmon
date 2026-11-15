import Link from "next/link";
import type { AgmDecision } from "@/lib/api";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";

export const AGM_INPUT_LABEL: Record<string, string> = {
  dps: "سود نقدی هر سهم (ریال)",
  price_now: "قیمت فعلی (ریال)",
  months_to_payment: "ماه تا دریافت سود (k)",
  monthly_discount: "نرخ تنزیل ماهانه (r_m)",
  alt_monthly_return: "بازده ماهانهٔ جایگزین (r_alt)",
  months_alt: "ماه‌های سرمایه‌گذاری جایگزین (k′)",
  round_trip_costs: "هزینهٔ رفت‌وبرگشت (ریال)",
  expected_drop_after: "افت مورد انتظار پس از بازگشایی (ریال)",
  dividend_tax: "مالیات سود (ریال)",
};

export const AGM_FIELDS = [
  "dps",
  "months_to_payment",
  "expected_drop_after",
  "dividend_tax",
  "months_alt",
] as const;

export type AgmQuery = Partial<Record<(typeof AGM_FIELDS)[number], string>>;

/** The dividend-meeting calculator: hold until the meeting or sell before it. */
export function AgmCalculator({
  q,
  agm,
}: {
  q: AgmQuery;
  agm: { ok: true; data: AgmDecision } | { ok: false; error: string } | null;
}) {
  return (
    <section>
      <h2 className="mb-1 font-bold">
        <Link href="/glossary/agm_decision" className="hover:text-accent">
          مجمع: نگه‌داشتن یا فروش
        </Link>
      </h2>
      <p className="mb-3 text-xs text-muted">
        قیمت، نرخ بدون ریسک و هزینهٔ معامله از پایگاه داده خوانده می‌شوند؛ سود نقدی و زمان پرداخت را
        از اطلاعیهٔ مجمع وارد کنید.
      </p>
      <form method="get" action="#agm" className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        {AGM_FIELDS.map((f) => (
          <label key={f} className="flex flex-col gap-1">
            <span>
              {AGM_INPUT_LABEL[f]}
              {(f === "dps" || f === "months_to_payment") && " *"}
            </span>
            <input
              name={f}
              type="number"
              step="any"
              min={f === "expected_drop_after" ? undefined : 0}
              required={f === "dps" || f === "months_to_payment"}
              defaultValue={q[f] ?? ""}
              dir="ltr"
              className="tile"
            />
          </label>
        ))}
        <div className="flex items-end">
          <button type="submit" className="btn btn-primary">
            محاسبه
          </button>
        </div>
      </form>
      {agm && !agm.ok && (
        <div className="mt-3">
          <ErrorState message={agm.error} />
        </div>
      )}
      {agm?.ok && (
        <div className="mt-4 space-y-3">
          <p className="text-lg font-extrabold">
            {agm.data.decision === "hold" ? "نگه‌داشتن تا مجمع" : "فروش پیش از مجمع"}
          </p>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            <div className="flex justify-between border-b border-line py-1.5">
              <dt>ارزش فعلی سود</dt>
              <dd className="font-semibold">
                <Num term="dps" value={agm.data.pv_dividend} kind="price" />
              </dd>
            </div>
            <div className="flex justify-between border-b border-line py-1.5">
              <dt>NetHold</dt>
              <dd className="font-semibold">
                <Num term="agm_decision" value={agm.data.net_hold} kind="price" />
              </dd>
            </div>
            <div className="flex justify-between border-b border-line py-1.5">
              <dt>NetSell</dt>
              <dd className="font-semibold">
                <Num term="agm_decision" value={agm.data.net_sell} kind="price" />
              </dd>
            </div>
          </dl>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr className="text-muted">
                  <th>ورودی</th>
                  <th>مقدار</th>
                  <th>منبع</th>
                </tr>
              </thead>
              <tbody>
                {agm.data.inputs.map((x) => (
                  <tr key={x.name} className="border-t border-line">
                    <td className="py-1.5">{AGM_INPUT_LABEL[x.name] ?? x.name}</td>
                    <td className="py-1.5">
                      <Num
                        term="agm_decision"
                        value={x.value}
                        digits={x.value !== 0 && Math.abs(x.value) < 1 ? 4 : 0}
                      />
                    </td>
                    <td className="py-1.5 text-xs text-muted" dir="ltr">
                      {x.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
