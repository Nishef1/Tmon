import Link from "next/link";
import type { Deep, DeepMethod } from "@/lib/api";
import { faNumber, faPercent, formatValue, jalali } from "@/lib/format";
import { methodLabel } from "@/components/model/methods";
import { Num } from "@/components/Num";

/** Reading order of the rows: the linear references, the trees, then the networks, then the mixes. */
const ORDER = [
  "ridge4_x120",
  "icw_x250",
  "gbm",
  "mlp",
  "dmlp",
  "gru",
  "tcn",
  "diff",
  "resid",
  "gbm_gru",
  "deep_avg",
  "hedge_all",
];

const horizonLabel = (h: number) => `${faNumber(h)} روز`;

function seedRange(m: DeepMethod): string | null {
  const v = (m.seed_ic ?? []).filter((x): x is number => x != null);
  if (v.length < 2) return null;
  return `${formatValue(Math.min(...v), "plain", 3)} تا ${formatValue(Math.max(...v), "plain", 3)}`;
}

/** Every method of the deep study against equal weights, per horizon, with the gate verdict. */
export function DeepStudy({ d }: { d: Deep }) {
  const names = ORDER.filter((n) => d.horizons.some((h) => n in h.methods));
  const passed = d.horizons.flatMap((h) =>
    Object.entries(h.methods)
      .filter(([, m]) => m.gate?.passed)
      .map(([n]) => `${methodLabel(n)} در افق ${horizonLabel(h.horizon_days)}`),
  );
  const cost = d.round_trip_cost ?? 0;
  return (
    <section className="space-y-4" data-testid="deep-study">
      <div className="space-y-2">
        <h3 className="text-lg font-bold">
          یادگیری عمیق، خودبازگشتی و دیفیوژن: آزموده شد (ترنسفورمر نه)
        </h3>
        <p className="text-sm leading-7">
          شبکهٔ عمیق، دو مدل <Link href="/glossary/autoregressive">خودبازگشتی</Link> (GRU و TCN روی
          ۱۶ روز اخیر هر سهم)، یک <Link href="/glossary/diffusion_model">دیفیوژن</Link> شرطی،{" "}
          <Link href="/glossary/residual_learning">یادگیری باقیمانده</Link> روی وزن مساوی و
          ترکیب‌هایشان با GBM و Hedge همه بدون نگاه به آینده سنجیده شدند: مدل در هر روز فقط با نتیجه‌هایی
          آموزش می‌بیند که تا آن روز معلوم بودند و هر ۱۲۶ روز دوباره آموزش می‌بیند. هر شبکه با{" "}
          {faNumber(d.seeds.length)} بذر تصادفی متفاوت آموزش داده شده و امتیازش میانگین همین اجراهاست. دورهٔ آزمون خارج از
          نمونه {jalali(d.oos_from)} تا {jalali(d.last)}، با مرز دو نیمه در {jalali(d.mid)}. معیار
          قبولی همان <Link href="/glossary/adapt_gate">دروازهٔ ارتقا</Link> است.
        </p>
        <p className="alert-warn text-sm leading-7 text-ink" data-testid="deep-caveat">
          داده فقط یک رژیم صعودی را دارد و هر دو نیمه در همان رژیم‌اند.{" "}
          <b>
            {passed.length === 0
              ? "هیچ روشی در هیچ افقی از دروازه نگذشت."
              : `از دروازه گذشتند: ${passed.join("؛ ")}.`}
          </b>{" "}
          در افق‌های بلند وزن مساوی از همهٔ روش‌ها بهتر ماند. این نتیجهٔ گذشته است، نه پیش‌بینی و نه
          توصیه؛ ما مشاور سرمایه‌گذاری دارای مجوز نیستیم.
        </p>
      </div>

      <div className="overflow-x-auto" data-testid="deep-matrix">
        <table className="tbl min-w-[44rem]">
          <caption className="mb-1 text-start text-xs text-muted">
            بهبود IC هر روش نسبت به وزن مساوی، همراه با t. علامت ✓ یعنی آن روش از دروازه گذشته است.
          </caption>
          <thead>
            <tr>
              <th>روش</th>
              {d.horizons.map((h) => (
                <th key={h.horizon_days}>{horizonLabel(h.horizon_days)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {names.map((n) => (
              <tr key={n}>
                <td>{methodLabel(n)}</td>
                {d.horizons.map((h) => {
                  const m = h.methods[n];
                  return (
                    <td key={h.horizon_days} data-passed={m?.gate?.passed ?? false}>
                      {m ? (
                        <>
                          <Num value={m.d_ic?.mean} digits={3} signed term="ic" />{" "}
                          <span className="text-xs text-muted">
                            (t=
                            <Num value={m.d_ic?.t} digits={1} term="t_stat" />)
                          </span>
                          {m.gate?.passed && <b className="mr-1 text-up">✓</b>}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-3">
        {d.horizons.map((h) => (
          <details key={h.horizon_days} className="card" data-testid={`deep-h${h.horizon_days}`}>
            <summary className="cursor-pointer font-bold">
              جزئیات افق {horizonLabel(h.horizon_days)}
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="tbl min-w-[52rem]">
                <thead>
                  <tr>
                    <th>روش</th>
                    <th>IC</th>
                    <th>بهبود IC نسبت به وزن مساوی</th>
                    <th>نیمهٔ اول ← دوم</th>
                    <th>بازدهٔ اضافهٔ ۱۰٪ بالای فهرست (هزینه {faPercent(cost, 2)})</th>
                    <th>
                      <Link href="/glossary/seed_spread">IC هر بذر تصادفی</Link>
                    </th>
                    <th>نتیجه</th>
                  </tr>
                </thead>
                <tbody>
                  {["equal", ...names]
                    .filter((n) => n in h.methods)
                    .map((n) => {
                      const m = h.methods[n];
                      return (
                        <tr key={n} data-passed={m.gate?.passed ?? false}>
                          <td>{methodLabel(n)}</td>
                          <td>
                            <Num value={m.ic.mean} digits={4} term="ic" />
                          </td>
                          <td>
                            {m.d_ic ? (
                              <>
                                <Num value={m.d_ic.mean} digits={4} signed term="ic" />{" "}
                                <span className="text-xs text-muted">
                                  (t=
                                  <Num value={m.d_ic.t} digits={1} term="t_stat" />)
                                </span>
                              </>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            {m.d_ic_early && m.d_ic_late ? (
                              <>
                                <Num value={m.d_ic_early.mean} digits={3} signed term="ic" /> ←{" "}
                                <Num value={m.d_ic_late.mean} digits={3} signed term="ic" />
                              </>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            <Num value={m.ex.mean} kind="percent" digits={2} term="adapt_gate" />
                          </td>
                          <td className="text-xs">{seedRange(m) ?? "—"}</td>
                          <td className="text-sm">
                            {!m.gate ? (
                              <span className="text-muted">مرجع</span>
                            ) : m.gate.passed ? (
                              <b className="text-up">از دروازه گذشت</b>
                            ) : (
                              <span className="text-muted">{m.gate.reasons.join("؛ ")}</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </details>
        ))}
        <p className="text-xs leading-6 text-muted">
          Hedge برای شروع به تاریخچهٔ خودش نیاز دارد و چند ماه دیرتر شروع می‌شود. بهبودش فقط روی
          روزهای مشترک با وزن مساوی حساب شده است، پس IC خام آن با ردیف‌های دیگر بازهٔ یکسانی ندارد.
        </p>
      </div>
    </section>
  );
}
