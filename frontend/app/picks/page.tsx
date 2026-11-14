import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Pick } from "@/lib/api";
import { faNumber, jalali } from "@/lib/format";
import { signedPct, signTone, verdictPill } from "@/lib/ui";
import { DeletePick } from "@/components/DeletePick";
import { ErrorState } from "@/components/ErrorState";

export const metadata: Metadata = { title: "خریدهای من" };
export const dynamic = "force-dynamic";

const STATUS: Record<string, { text: string; cls: string }> = {
  inside: { text: "داخل بازه", cls: "text-up" },
  above: { text: "بالاتر از بازه", cls: "text-up" },
  below: { text: "پایین‌تر از بازه", cls: "text-down" },
  pending: { text: "هنوز نرسیده", cls: "text-muted" },
};

function PickCard({ p }: { p: Pick }) {
  return (
    <section className="card" data-testid="pick" data-symbol={p.symbol}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold">
          <Link href={`/instruments/${p.instrument_id}`} className="hover:text-accent">
            {p.symbol}
          </Link>{" "}
          <span className="text-sm font-normal text-muted">{p.name}</span>
        </h2>
        <DeletePick id={p.id} />
      </div>
      <p className="mt-1 text-sm text-muted">
        پیش‌بینی روی دادهٔ {jalali(p.as_of)} ثابت شد
        {p.gauge != null && <> (امتیاز {faNumber(p.gauge, 0)} از ۱۰۰)</>}
        {p.paid_price != null && <> · قیمت خرید شما {faNumber(p.paid_price)}</>}
        {p.last_return != null && p.last_date && (
          <>
            {" "}
            · تا {jalali(p.last_date)}:{" "}
            <b className={signTone(p.last_return)}>{signedPct(p.last_return)}</b>
          </>
        )}
      </p>

      {p.candles.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm" data-testid="pick-candles">
            <thead>
              <tr className="text-start text-muted">
                <th className="py-1 text-start font-medium">بعد از</th>
                <th className="text-start font-medium">پیش‌بینی (۸ از ۱۰ بار بین)</th>
                <th className="text-start font-medium">شانس بالا رفتن</th>
                <th className="text-start font-medium">واقعیت</th>
                <th className="text-start font-medium">نتیجه</th>
              </tr>
            </thead>
            <tbody>
              {p.candles.map((c) => {
                const st = STATUS[c.status] ?? STATUS.pending;
                return (
                  <tr
                    key={c.h}
                    data-h={c.h}
                    data-status={c.status}
                    className="border-t border-line"
                  >
                    <td className="py-1.5">{faNumber(c.h)} کندل</td>
                    <td>
                      {c.q10 != null && c.q90 != null
                        ? `${signedPct(c.q10)} تا ${signedPct(c.q90)}`
                        : "—"}
                    </td>
                    <td>{c.up != null ? `${faNumber(Math.round(c.up * 100))}٪` : "—"}</td>
                    <td className={c.actual != null ? signTone(c.actual) : "text-muted"}>
                      {c.actual != null ? signedPct(c.actual) : "—"}
                    </td>
                    <td className={st.cls}>{st.text}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {p.resolved > 0 && (
        <p className="mt-2 text-sm" data-testid="pick-score">
          از {faNumber(p.resolved)} پیش‌بینی که زمانش رسیده، {faNumber(p.inside)} تا داخل بازه بود
          (انتظار می‌رود حدود ۸ از ۱۰) و جهت {faNumber(p.direction_ok)} تا درست بود.
        </p>
      )}

      {p.verdicts.length > 0 && (
        <div className="mt-3">
          <h3 className="mb-1 text-sm font-semibold">تصمیم مدل برای هر بازه، پس از کسر کارمزد</h3>
          <ul className="space-y-1 text-sm" data-testid="pick-verdicts">
            {p.verdicts.map((v) => (
              <li key={v.key} className="flex flex-wrap items-center gap-2">
                <span className="w-20">{v.label}</span>
                <span className={verdictPill(v.verdict)}>{v.verdict_label}</span>
                {v.net == null ? (
                  <span className="text-muted">هنوز {faNumber(v.days)} کندل نگذشته است.</span>
                ) : (
                  <span>
                    بازده <b className={signTone(v.actual)}>{signedPct(v.actual)}</b>، پس از کارمزد{" "}
                    <b className={signTone(v.net)}>{signedPct(v.net)}</b> ·{" "}
                    <b className={v.right ? "text-up" : "text-down"}>
                      {v.right ? "تصمیم درست بود" : "تصمیم اشتباه بود"}
                    </b>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export default async function PicksPage() {
  const res = await apiGet<Pick[]>("/picks");
  return (
    <main className="space-y-5">
      <div>
        <h1 className="page-title">خریدهای من</h1>
        <p className="lead">
          در صفحهٔ هر نماد «این سهم را خریدم» را بزنید. پیش‌بینی همان روز همان‌طور که بود ذخیره
          می‌شود و با هر کندل جدید با قیمت واقعی مقایسه می‌شود تا ببینیم کجا درست گفته و کجا اشتباه.
          بازده‌ها روی قیمت تعدیل‌شده‌اند. این ابزار تحلیل است، نه توصیه.
        </p>
      </div>
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : res.data.length === 0 ? (
        <p className="card text-muted">هنوز خریدی ثبت نکرده‌اید.</p>
      ) : (
        res.data.map((p) => <PickCard key={p.id} p={p} />)
      )}
    </main>
  );
}
