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
  SymbolFlow,
  SymbolTechnical,
  SymbolValuation,
} from "@/components/SymbolDashboard";
import { Fold } from "@/components/stock/Fold";
import { PeersCard } from "@/components/PeersCard";
import { TurningCard } from "@/components/TurningCard";
import { TrendRideCard } from "@/components/stock/TrendRideCard";
import { rideMarks } from "@/components/stock/rideMarks";
import { DriversCard } from "@/components/DriversCard";
import { StockHeader } from "@/components/stock/StockHeader";
import { JumpNav, type JumpItem } from "@/components/stock/JumpNav";
import { PriceRange } from "@/components/PlainSummary";
import { StockNews } from "@/components/stock/StockNews";
import { LiveWhenOpen } from "@/components/stock/LiveWhenOpen";
import { StockAlerts } from "@/components/stock/StockAlerts";
import { AGM_FIELDS, AgmCalculator } from "@/components/stock/AgmCalculator";
import { CandleChart, type Mark } from "@/components/CandleChart";
import { BookCard } from "@/components/book/BookCard";
import { EntryOddsCard } from "@/components/entry/EntryOddsCard";
import { labelColor } from "@/components/entry/EntryParts";
import { ErrorState } from "@/components/ErrorState";

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
  const entry = dash.ok ? dash.data.entry : null;
  const ride = dash.ok ? (dash.data.turning?.ride ?? null) : null;
  const arrows = entry ? entryMarks(entry) : [];
  const marks = [...arrows, ...(ride ? rideMarks(ride) : [])];

  const dd = dash.ok ? dash.data : null;
  const firedHere = (dd?.technical?.fired.length ?? 0) > 0;
  // the entry lab only earns a card when a state of today beat or trailed the rest of the market
  const entryDecisive = !!entry?.now.some((s) => s.label === "better" || s.label === "worse");
  const agmNear = !!dd?.meeting && dd.meeting.days_left >= 0 && dd.meeting.days_left <= 30;

  const jumps: JumpItem[] = [
    ...(dd ? [{ id: "decision", label: "چه کنم؟" }] : []),
    ...(d.candles.length > 0 ? [{ id: "chart", label: "نمودار" }] : []),
    ...(ride ? [{ id: "ride", label: "ورود و خروج روند" }] : []),
    ...(dd?.peers ? [{ id: "peers", label: "همگروه‌ها" }] : []),
    ...(dd ? [{ id: "facts", label: "پول و ارزش‌گذاری" }] : []),
    ...(book.ok ? [{ id: "book", label: "خریداران و فروشندگان" }] : []),
    ...(entryDecisive ? [{ id: "entry", label: "آزمایشگاه ورود" }] : []),
    ...(dd && (dd.technical || dd.turning || dd.drivers)
      ? [{ id: "technical", label: "تکنیکال و محرک‌ها" }]
      : []),
    { id: "agm", label: "مجمع" },
    { id: "holders", label: "سهامداران" },
    { id: "news", label: "کدال و خبر" },
  ];

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

      <JumpNav items={jumps} />

      {dd && (
        <div id="decision" className="scroll-mt-28">
          <SymbolDecision d={dd} id={d.instrument.id} horizon={q.h} />
        </div>
      )}

      <LiveWhenOpen instrumentId={d.instrument.id} />

      <section className="card min-w-0 scroll-mt-28" data-testid="chart-section" id="chart">
        <h2 className="mb-2 text-lg font-extrabold">نمودار قیمت</h2>
        {d.candles.length === 0 ? (
          <p className="text-sm text-muted">دادهٔ قیمتی برای این نماد موجود نیست.</p>
        ) : (
          <>
            <CandleChart candles={d.candles} marks={marks} />
            <p className="mt-2 text-xs text-muted">
              قیمت‌ها برای سود نقدی و افزایش سرمایه{" "}
              <Link href="/glossary/adjusted_price" className="underline">
                تعدیل
              </Link>{" "}
              شده‌اند.
              {arrows.length > 0 &&
                " پیکان سبز یعنی ورود در آن کندل در گذشته بهتر از بقیهٔ سهم‌ها بوده است و پیکان قرمز یعنی بدتر."}
              {ride?.entry_date &&
                " «روند خرید» و «روند فروش» روزهای آخرین دورهٔ قاعدهٔ ورود و خروج روند هستند."}
            </p>
          </>
        )}
      </section>

      {ride && (
        <div id="ride" className="scroll-mt-28">
          <TrendRideCard r={ride} instrumentId={d.instrument.id} />
        </div>
      )}

      {dd && <PriceRange d={dd} />}

      {dd?.peers && (
        <div id="peers" className="scroll-mt-28">
          <PeersCard p={dd.peers} />
        </div>
      )}

      {dd && (
        <Fold id="facts" title="پول و ارزش‌گذاری" hint="حقیقی و حقوقی، سرانه، P/E">
          <div className="grid items-start gap-x-8 gap-y-4 lg:grid-cols-2">
            <SymbolFlow d={dd} />
            <SymbolValuation d={dd} />
          </div>
          <SymbolFacts d={dd} />
        </Fold>
      )}

      {book.ok && (
        <Fold id="book" title="رفتار خریداران و فروشندگان" hint="ردهٔ سهم در کل بازار، روز به روز">
          <BookCard b={book.data} />
        </Fold>
      )}

      {entryDecisive && entry && (
        <Fold id="entry" title="آزمایشگاه ورود" hint="بعد از کندل‌هایی مثل امروز در گذشته چه شد">
          <EntryOddsCard e={entry} odds={odds} />
        </Fold>
      )}

      {dd && (dd.technical || dd.turning || dd.drivers) && (
        <Fold
          id="technical"
          title="تکنیکال، ریسک و محرک‌ها"
          hint="اندیکاتورها، جای سهم در ریزش و رشد، بیشترین افت"
        >
          {dd.technical && <SymbolTechnical d={dd} />}
          {(dd.turning || dd.drivers) && (
            <div className="grid items-start gap-x-8 gap-y-4 lg:grid-cols-2">
              {dd.turning && <TurningCard t={dd.turning} skipWarning={firedHere} />}
              {dd.drivers && <DriversCard d={dd.drivers} />}
            </div>
          )}
          {entry && !entryDecisive && (
            <p className="text-sm text-muted" data-testid="entry-none">
              حالت امروز این سهم در آزمون کل بورس از خریدن هر سهم دیگری بهتر یا بدتر نبوده است؛{" "}
              <Link href="/model#entry" className="underline">
                آزمایشگاه ورود
              </Link>{" "}
              همهٔ حالت‌ها را نشان می‌دهد.
            </p>
          )}
        </Fold>
      )}

      <Fold
        id="agm"
        title="مجمع و سود نقدی"
        hint={
          dd?.meeting
            ? `مجمع ${faNumber(dd.meeting.days_left)} روز دیگر`
            : "تاریخ مجمع، حجم مبنا و ماشین‌حساب «نگه داشتن یا فروش»"
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

      <StockNews d={d} />
    </main>
  );
}
