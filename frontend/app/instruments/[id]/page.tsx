import Link from "next/link";
import { notFound } from "next/navigation";
import {
  apiGet,
  type AgmDecision,
  type InstrumentDashboard,
  type InstrumentDetail,
} from "@/lib/api";
import { featureInfo } from "@/lib/glossary";
import { jalali } from "@/lib/format";
import { SymbolDashboard } from "@/components/SymbolDashboard";
import { LiveQuote } from "@/components/LiveQuote";
import { CandleChart, type Level } from "@/components/CandleChart";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { SignalTable } from "@/components/SignalTable";

export const dynamic = "force-dynamic";

const STAGE_LABEL: Record<string, string> = {
  invitation: "دعوت",
  decisions: "تصمیمات",
  decisions_summary: "خلاصهٔ تصمیمات",
  decisions_registered: "ثبت تصمیمات",
  dividend_schedule: "زمان‌بندی پرداخت سود",
  dividend_schedule_prior_years: "زمان‌بندی سود سال‌های قبل",
  ordinary_extraordinary_invitation: "دعوت مجمع عادی به‌طور فوق‌العاده",
  ordinary_extraordinary_decisions: "تصمیمات مجمع عادی به‌طور فوق‌العاده",
  ordinary_extraordinary_decisions_summary: "خلاصهٔ تصمیمات مجمع فوق‌العاده",
  egm_invitation: "دعوت مجمع فوق‌العاده",
  egm_decisions: "تصمیمات مجمع فوق‌العاده",
  meeting_cancelled: "لغو جلسه",
  board_proposal: "پیشنهاد هیئت‌مدیره",
  auditor_opinion: "نظر حسابرس",
  documents: "مدارک",
  registered: "ثبت",
  board_decision_delegated: "تصمیم هیئت‌مدیره (تفویض)",
  board_meeting_scheduled: "زمان جلسهٔ هیئت‌مدیره",
  board_decision: "تصمیم هیئت‌مدیره",
  rights_deadline_extended: "تمدید مهلت حق‌تقدم",
  public_subscription_extended: "تمدید پذیره‌نویسی",
};

const TYPE_LABEL: Record<string, string> = {
  agm_dividend: "مجمع عادی",
  egm_capital_increase: "افزایش سرمایه",
  rights_offering: "حق‌تقدم",
  other: "سایر",
};

const AGM_INPUT_LABEL: Record<string, string> = {
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

const AGM_FIELDS = [
  "dps",
  "months_to_payment",
  "expected_drop_after",
  "dividend_tax",
  "months_alt",
] as const;

type Search = Partial<Record<(typeof AGM_FIELDS)[number], string>>;

function isNum(v: string | undefined): v is string {
  return v !== undefined && v.trim() !== "" && Number.isFinite(Number(v));
}

export default async function InstrumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Search>;
}) {
  const { id } = await params;
  const q = await searchParams;
  if (!/^\d+$/.test(id)) notFound();
  const [res, dash] = await Promise.all([
    apiGet<InstrumentDetail>(`/instruments/${id}`),
    apiGet<InstrumentDashboard>(`/instruments/${id}/dashboard`),
  ]);
  if (!res.ok && res.status === 404) notFound();
  if (!res.ok) {
    return (
      <main className="space-y-4">
        <ErrorState message={res.error} />
      </main>
    );
  }
  const d = res.data;
  const asked = isNum(q.dps) && isNum(q.months_to_payment);
  const agm = asked
    ? await apiGet<AgmDecision>(
        `/instruments/${id}/agm`,
        Object.fromEntries(AGM_FIELDS.filter((f) => isNum(q[f])).map((f) => [f, q[f] as string])),
      )
    : null;
  const open = d.signals.find((s) => s.outcome === "pending");
  const levels: Level[] = open
    ? [
        { price: open.take_profit, title: "حد سود", color: "#1d6a43" },
        { price: open.entry_price, title: "مرجع", color: "#6b675f" },
        { price: open.stop_loss, title: "حد ضرر", color: "#a32d2d" },
      ]
    : [];

  return (
    <main className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-accent">
          ← توصیه‌های امروز
        </Link>
        <h1 className="mt-2 text-2xl font-extrabold">{d.instrument.symbol}</h1>
        {d.instrument.name && <p className="text-muted">{d.instrument.name}</p>}
      </div>

      <Disclaimer />

      {dash.ok && <SymbolDashboard d={dash.data} />}

      <LiveQuote instrumentId={d.instrument.id} />

      <section className="rounded-2xl border border-line bg-surface p-4">
        <h2 className="mb-2 font-bold">نمودار قیمت تعدیل‌شده</h2>
        {d.candles.length === 0 ? (
          <p className="text-sm text-muted">دادهٔ قیمتی برای این نماد موجود نیست.</p>
        ) : (
          <>
            <CandleChart candles={d.candles} levels={levels} />
            <p className="mt-2 text-xs text-muted">
              قیمت‌ها برای سود نقدی و افزایش سرمایه{" "}
              <Link href="/glossary/adjusted_price" className="underline">
                تعدیل
              </Link>{" "}
              شده‌اند. روزهای توقف نماد نمایش داده نمی‌شوند.
              {open && " خط‌چین‌ها سطح‌های آخرین سیگنال بازِ این نماد هستند."}
            </p>
          </>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-4">
        <h2 className="mb-2 font-bold">
          شاخص‌ها
          {d.features_date && (
            <span className="text-sm font-normal text-muted">
              {" "}
              · تا {jalali(d.features_date, "long")}
            </span>
          )}
        </h2>
        {d.features.length === 0 ? (
          <p className="text-sm text-muted">شاخصی برای این نماد محاسبه نشده است.</p>
        ) : (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {d.features.map((f) => {
              const info = featureInfo(f.feature);
              return (
                <div key={f.feature} className="flex justify-between border-b border-line py-1.5">
                  <dt>
                    <Link href={`/glossary/${info.term}`} className="hover:text-accent">
                      {info.label}
                    </Link>
                  </dt>
                  <dd className="font-semibold">
                    <Num term={info.term} value={f.value} digits={2} />
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="font-bold">سیگنال‌های منتشرشده برای این نماد</h2>
        {d.signals.length === 0 ? (
          <p className="text-sm text-muted">تاکنون سیگنالی برای این نماد منتشر نشده است.</p>
        ) : (
          <SignalTable items={d.signals} showSymbol={false} />
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-4">
        <h2 className="mb-2 font-bold">
          <Link href="/glossary/codal_event" className="hover:text-accent">
            رویدادهای کدال
          </Link>
        </h2>
        {d.events.length === 0 ? (
          <p className="text-sm text-muted">
            رویداد مجمع یا افزایش سرمایه‌ای برای این نماد ثبت نشده است.
          </p>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {d.events.map((e, i) => (
              <li key={`${e.url ?? ""}-${i}`} className="flex flex-wrap gap-x-3 gap-y-1 py-2">
                <span className="text-muted">
                  {e.announced_at ? jalali(e.announced_at, "short") : "—"}
                </span>
                <span className="font-semibold">
                  {TYPE_LABEL[e.type] ?? e.type}
                  {e.stage && ` · ${STAGE_LABEL[e.stage] ?? e.stage}`}
                </span>
                {e.url ? (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-w-0 break-words text-accent underline"
                  >
                    {e.title ?? "نامهٔ کدال"}
                  </a>
                ) : (
                  <span className="min-w-0 break-words">{e.title}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-4" id="agm">
        <h2 className="mb-1 font-bold">
          <Link href="/glossary/agm_decision" className="hover:text-accent">
            مجمع: نگه‌داشتن یا فروش
          </Link>
        </h2>
        <p className="mb-3 text-xs text-muted">
          قیمت، نرخ بدون ریسک و هزینهٔ معامله از پایگاه داده خوانده می‌شوند؛ سود نقدی و زمان پرداخت
          را از اطلاعیهٔ مجمع وارد کنید.
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
                className="rounded-lg border border-line bg-surface px-3 py-2"
              />
            </label>
          ))}
          <div className="flex items-end">
            <button type="submit" className="rounded-lg bg-accent px-4 py-2 font-bold text-white">
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
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted">
                  <th className="py-1 text-start font-normal">ورودی</th>
                  <th className="py-1 text-start font-normal">مقدار</th>
                  <th className="py-1 text-start font-normal">منبع</th>
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
        )}
      </section>
    </main>
  );
}
