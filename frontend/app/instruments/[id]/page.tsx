import Link from "next/link";
import { notFound } from "next/navigation";
import {
  apiGet,
  entryOdds,
  type AgmDecision,
  type DashEntry,
  type InstrumentBook,
  type InstrumentDashboard,
  type InstrumentDetail,
} from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import {
  SymbolContext,
  SymbolDecision,
  SymbolFacts,
  SymbolTechnical,
  SymbolValuation,
} from "@/components/SymbolDashboard";
import { Fold } from "@/components/stock/Fold";
import { StockHeader } from "@/components/stock/StockHeader";
import { StockNews } from "@/components/stock/StockNews";
import { LiveQuote } from "@/components/LiveQuote";
import { CandleChart, type Level, type Mark } from "@/components/CandleChart";
import { BookCard } from "@/components/book/BookCard";
import { EntryOddsCard } from "@/components/entry/EntryOddsCard";
import { labelColor } from "@/components/entry/EntryParts";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";
import { SignalTable } from "@/components/SignalTable";

export const dynamic = "force-dynamic";

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

type Search = Partial<Record<(typeof AGM_FIELDS)[number] | "h", string>>;

function isNum(v: string | undefined): v is string {
  return v !== undefined && v.trim() !== "" && Number.isFinite(Number(v));
}

const SHORT: Record<string, string> = { better: "ورود+", worse: "ورود−" };

/** One arrow per entry day of the last year whose setup had a tested edge: green up under the
 *  candle when the setup was better than buying any other symbol, red down over it when worse.
 *  Days whose setups made no tested difference are left off. */
function entryMarks(e: DashEntry): Mark[] {
  const byDay = new Map<string, "better" | "worse">();
  for (const m of e.marks) {
    if (m.label !== "better" && m.label !== "worse") continue;
    if (byDay.get(m.date) !== "worse") byDay.set(m.date, m.label);
  }
  return [...byDay].map(([time, label]) => ({
    time,
    text: SHORT[label],
    color: labelColor(label),
    above: label === "worse",
  }));
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
  const [res, dash, odds, book] = await Promise.all([
    apiGet<InstrumentDetail>(`/instruments/${id}`),
    apiGet<InstrumentDashboard>(`/instruments/${id}/dashboard`),
    entryOdds(),
    apiGet<InstrumentBook>(`/instruments/${id}/book`),
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
        { price: open.take_profit, title: "حد سود", color: "var(--up)" },
        { price: open.entry_price, title: "مرجع", color: "var(--ref)" },
        { price: open.stop_loss, title: "حد ضرر", color: "var(--down)" },
      ]
    : [];

  const entry = dash.ok ? dash.data.entry : null;
  const marks = entry ? entryMarks(entry) : [];

  return (
    <main className="space-y-6">
      <StockHeader d={d} dash={dash.ok ? dash.data : null} book={book.ok ? book.data : null} />

      <LiveQuote instrumentId={d.instrument.id} />

      {dash.ok && <SymbolDecision d={dash.data} id={d.instrument.id} horizon={q.h} />}

      <section className="card">
        <h2 className="mb-2 font-bold">نمودار قیمت تعدیل‌شده</h2>
        {d.candles.length === 0 ? (
          <p className="text-sm text-muted">دادهٔ قیمتی برای این نماد موجود نیست.</p>
        ) : (
          <>
            <CandleChart candles={d.candles} levels={levels} marks={marks} />
            <p className="mt-2 text-xs text-muted">
              قیمت‌ها برای سود نقدی و افزایش سرمایه{" "}
              <Link href="/glossary/adjusted_price" className="underline">
                تعدیل
              </Link>{" "}
              شده‌اند. روزهای توقف نماد نمایش داده نمی‌شوند.
              {open && " خط‌چین‌ها سطح‌های آخرین سیگنال بازِ این نماد هستند."}
              {marks.length > 0 &&
                " پیکان‌ها کندل‌های ورودِ آزموده‌شدهٔ یک سال اخیرند: سبز یعنی بعد از چنین کندلی در گذشته بیشتر از بقیهٔ سهم‌ها بالا رفته، قرمز کمتر، خاکستری فرقی نداشته."}
            </p>
          </>
        )}
      </section>

      <StockNews d={d} />

      {dash.ok && <SymbolContext d={dash.data} />}

      {entry && (
        <Fold id="entry" title="آزمایشگاه ورود" hint="بعد از کندل‌هایی مثل امروز در گذشته چه شد">
          <EntryOddsCard e={entry} odds={odds} />
        </Fold>
      )}

      {dash.ok && dash.data.technical && (
        <Fold
          id="technical"
          title="تحلیل تکنیکال و ریسک"
          hint="اندیکاتورها، سابقهٔ آزموده و بیشترین افت"
        >
          <SymbolTechnical d={dash.data} />
        </Fold>
      )}

      {book.ok && (
        <Fold id="book" title="رفتار خریداران و فروشندگان" hint="ردهٔ سهم در کل بازار، روز به روز">
          <BookCard b={book.data} />
        </Fold>
      )}

      {dash.ok && (
        <Fold
          id="facts"
          title="ارزش‌گذاری، شرکت و معاملات امروز"
          hint="P/E، مجمع، قیمت، حقیقی و حقوقی"
        >
          <SymbolValuation d={dash.data} />
          <SymbolFacts d={dash.data} />
        </Fold>
      )}

      <Fold id="holders" title="سهامداران عمده" hint="دارندگان یک درصد یا بیشتر">
        <section data-testid="shareholders">
          <p className="mb-2 text-xs text-muted">
            دارندگان حدود یک درصد یا بیشتر از سهام، طبق فهرست بورس
            {d.shareholders_at ? ` (دریافت: ${jalali(d.shareholders_at, "long")})` : ""}. «تغییر»
            تعداد سهم خرید (مثبت) یا فروش (منفی) نسبت به فهرست قبلی است.
          </p>
          {d.shareholders.length === 0 ? (
            <p className="text-sm text-muted">فهرست سهامداران عمده برای این نماد در دسترس نیست.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl min-w-[28rem]">
                <thead>
                  <tr className="text-right">
                    <th>سهامدار</th>
                    <th>درصد</th>
                    <th>تعداد سهم</th>
                    <th>تغییر</th>
                  </tr>
                </thead>
                <tbody>
                  {d.shareholders.map((h, i) => (
                    // TSETMC lists several holders under one name ("شخص حقیقی"), so the name alone is not a key
                    <tr key={`${i}-${h.name}`}>
                      <td className="font-semibold">{h.name}</td>
                      <td>{h.percent == null ? "—" : faPercent(h.percent / 100, 2)}</td>
                      <td>{h.shares == null ? "—" : faNumber(h.shares)}</td>
                      <td className={signTone(h.change_amount)}>
                        {h.change_amount == null || h.change_amount === 0
                          ? "—"
                          : faNumber(h.change_amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </Fold>
      {d.signals.length > 0 && (
        <Fold
          id="signals"
          title="سیگنال‌های منتشرشده"
          hint={`${faNumber(d.signals.length)} سیگنال`}
        >
          <section className="space-y-2">
            <SignalTable items={d.signals} showSymbol={false} />
          </section>
        </Fold>
      )}

      <Fold id="agm" title="مجمع: نگه‌داشتن یا فروش" hint="ماشین‌حساب سود نقدی" open={asked}>
        <section>
          <h2 className="mb-1 font-bold">
            <Link href="/glossary/agm_decision" className="hover:text-accent">
              مجمع: نگه‌داشتن یا فروش
            </Link>
          </h2>
          <p className="mb-3 text-xs text-muted">
            قیمت، نرخ بدون ریسک و هزینهٔ معامله از پایگاه داده خوانده می‌شوند؛ سود نقدی و زمان
            پرداخت را از اطلاعیهٔ مجمع وارد کنید.
          </p>
          <form
            method="get"
            action="#agm"
            className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2"
          >
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
      </Fold>
    </main>
  );
}
