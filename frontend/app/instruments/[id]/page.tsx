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
  SymbolDecision,
  SymbolCompany,
  SymbolFacts,
  SymbolTechnical,
  SymbolValuation,
} from "@/components/SymbolDashboard";
import { Fold } from "@/components/stock/Fold";
import { PeersCard } from "@/components/PeersCard";
import { TurningCard } from "@/components/TurningCard";
import { DriversCard } from "@/components/DriversCard";
import { StockHeader } from "@/components/stock/StockHeader";
import { StockNews } from "@/components/stock/StockNews";
import { LiveWhenOpen } from "@/components/stock/LiveWhenOpen";
import { StockAlerts } from "@/components/stock/StockAlerts";
import { AGM_FIELDS, AgmCalculator } from "@/components/stock/AgmCalculator";
import { CandleChart, type Level, type Mark } from "@/components/CandleChart";
import { BookCard } from "@/components/book/BookCard";
import { EntryOddsCard } from "@/components/entry/EntryOddsCard";
import { labelColor } from "@/components/entry/EntryParts";
import { ErrorState } from "@/components/ErrorState";
import { SignalTable } from "@/components/SignalTable";

export const dynamic = "force-dynamic";

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

  const dd = dash.ok ? dash.data : null;
  const agmNear = !!dd?.meeting && dd.meeting.days_left >= 0 && dd.meeting.days_left <= 30;

  return (
    <main className="space-y-4">
      <StockHeader d={d} dash={dd} book={book.ok ? book.data : null} />

      {dd && (
        <StockAlerts
          instrumentId={d.instrument.id}
          halted={dd.trade_state === "halted"}
          idleDays={dd.idle_days}
          meeting={dd.meeting ?? null}
          events={[
            ...d.events.map((e) => ({
              when: e.announced_at ?? "",
              title: e.title ?? "نامهٔ کدال",
            })),
            ...d.letters.map((l) => ({ when: l.published_at ?? "", title: l.title })),
          ].filter((x) => x.when)}
        />
      )}

      {dd && <SymbolDecision d={dd} id={d.instrument.id} horizon={q.h} />}

      <LiveWhenOpen instrumentId={d.instrument.id} />

      <section className="card min-w-0" data-testid="chart-section">
        <h2 className="mb-2 text-lg font-extrabold">نمودار قیمت</h2>
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
              شده‌اند.
              {open && " خط‌چین‌ها سطح‌های آخرین سیگنال بازِ این نماد هستند."}
              {marks.length > 0 &&
                " پیکان سبز/قرمز: کندل ورودی که در گذشته بهتر/بدتر از بقیهٔ سهم‌ها بوده."}
            </p>
          </>
        )}
      </section>

      {dd?.peers && <PeersCard p={dd.peers} />}

      {dd && (
        <Fold id="facts" title="ارزش‌گذاری و معاملات" hint="P/E، حقیقی و حقوقی، سرانه، قیمت">
          <SymbolValuation d={dd} />
          <SymbolFacts d={dd} />
        </Fold>
      )}

      {book.ok && (
        <Fold id="book" title="رفتار خریداران و فروشندگان" hint="ردهٔ سهم در کل بازار، روز به روز">
          <BookCard b={book.data} />
        </Fold>
      )}

      {dd && (dd.turning || dd.drivers) && (
        <Fold id="context" title="چه چیزی این سهم را حرکت می‌دهد؟" hint="حالت فعلی و عامل‌ها">
          {dd.turning && <TurningCard t={dd.turning} />}
          {dd.drivers && <DriversCard d={dd.drivers} />}
        </Fold>
      )}

      {entry && (
        <Fold id="entry" title="آزمایشگاه ورود" hint="بعد از کندل‌هایی مثل امروز در گذشته چه شد">
          <EntryOddsCard e={entry} odds={odds} />
        </Fold>
      )}

      {dd?.technical && (
        <Fold
          id="technical"
          title="تحلیل تکنیکال و ریسک"
          hint="اندیکاتورها، سابقهٔ آزموده و بیشترین افت"
        >
          <SymbolTechnical d={dd} />
        </Fold>
      )}

      <Fold
        id="agm"
        title="مجمع و سود نقدی"
        hint={
          dd?.meeting
            ? `مجمع ${faNumber(dd.meeting.days_left)} روز دیگر`
            : "تاریخ مجمع، حجم مبنا و ماشین‌حساب نگه‌داری یا فروش"
        }
        open={asked || agmNear || true}
      >
        {dd && <SymbolCompany d={dd} />}
        <AgmCalculator q={q} agm={agm} />
      </Fold>

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

      <StockNews d={d} />
    </main>
  );
}
