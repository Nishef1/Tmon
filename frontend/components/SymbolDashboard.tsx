import Link from "next/link";
import { HoldWord } from "@/components/stock/HoldWord";
import type { ReactNode } from "react";
import type { InstrumentDashboard } from "@/lib/api";
import { Gauge } from "@/components/Gauge";
import { DriversCard } from "@/components/DriversCard";
import { PeersCard } from "@/components/PeersCard";
import { PriceRange } from "@/components/PlainSummary";
import { TrackBuyButton } from "@/components/TrackBuyButton";
import { TurningCard } from "@/components/TurningCard";
import { TechnicalCard } from "@/components/TechnicalCard";
import { Checks, shortLabel } from "@/components/stock/Checks";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";
import { signedPct, verdictPill, verdictTone } from "@/lib/ui";

type D = InstrumentDashboard;

/** Share counts and volumes in short Persian units. */
function qty(n: number | null | undefined): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${faNumber(n / 1e12, 2)} هزار میلیارد`;
  if (a >= 1e9) return `${faNumber(n / 1e9, 2)} میلیارد`;
  if (a >= 1e6) return `${faNumber(n / 1e6, 1)} میلیون`;
  if (a >= 1e3) return `${faNumber(n / 1e3, 1)} هزار`;
  return faNumber(n);
}

/** Rial -> toman, short units. */
function toman(rial: number | null | undefined): string {
  if (rial == null) return "—";
  const t = rial / 10;
  const a = Math.abs(t);
  if (a >= 1e12) return `${faNumber(t / 1e12, 2)} هزار میلیارد تومان`;
  if (a >= 1e9) return `${faNumber(t / 1e9, 1)} میلیارد تومان`;
  if (a >= 1e6) return `${faNumber(t / 1e6, 1)} میلیون تومان`;
  return `${faNumber(t)} تومان`;
}

function Row({ k, v, tone }: { k: string; v: ReactNode; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line py-1.5 last:border-0">
      <dt className="text-muted">{k}</dt>
      <dd className={`font-semibold ${tone ?? ""}`}>{v}</dd>
    </div>
  );
}

function Card({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="card">
      <h2 className="mb-1 font-bold">{title}</h2>
      {note && <p className="mb-2 text-xs text-muted">{note}</p>}
      <dl>{children}</dl>
    </section>
  );
}

const sign = (n: number | null | undefined) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");

/** Where `v` sits between `lo` and `hi` (0-100), for the range bars. */
function pos(v: number | null, lo: number | null, hi: number | null): number | null {
  if (v == null || lo == null || hi == null || hi <= lo) return null;
  return Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
}

function RangeBar({
  title,
  lo,
  hi,
  at,
  mark,
}: {
  title: string;
  lo: number | null;
  hi: number | null;
  at: number | null;
  mark?: number | null;
}) {
  const p = pos(at, lo, hi);
  if (p == null || lo == null || hi == null) return null;
  const r = pos(mark ?? null, lo, hi);
  return (
    <div className="py-2">
      <div className="mb-1 flex justify-between text-xs text-muted">
        <span>{title}</span>
        <span>
          {faNumber(lo)} تا {faNumber(hi)}
        </span>
      </div>
      <div className="relative h-2 rounded bg-accent-soft">
        {r != null && (
          <span className="absolute top-[-3px] h-3.5 w-px bg-muted" style={{ right: `${r}%` }} />
        )}
        <span
          className="absolute top-[-2px] h-3 w-3 rounded-full bg-accent"
          style={{ right: `calc(${p}% - 6px)` }}
        />
      </div>
    </div>
  );
}

const barTone = (pct: number) => (pct >= 66 ? "bg-up" : pct >= 33 ? "bg-hold" : "bg-down");

function SignalBars({ signals }: { signals: D["decision"]["signals"] }) {
  if (!signals.length) return null;
  return (
    <details data-testid="signal-bars">
      <summary className="cursor-pointer font-semibold">چرا این امتیاز را گرفته؟</summary>
      <p className="mb-2 mt-2 text-muted">
        مدل چهار چیز را می‌سنجد و هر کدام را با همهٔ سهم‌های بازار مقایسه می‌کند. نوار پرتر یعنی
        بهتر از سهم‌های بیشتری است.
      </p>
      <ul className="space-y-3">
        {signals.map((g) => (
          <li key={g.key}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold">{g.name}</span>
              <span className="text-sm">{faNumber(g.pct, 0)} از ۱۰۰</span>
            </div>
            <div className="mt-1 h-2.5 rounded-full bg-line" aria-hidden>
              <div
                className={`h-full rounded-full ${barTone(g.pct)}`}
                style={{ width: `${Math.max(3, g.pct)}%` }}
              />
            </div>
            <p className="mt-1 text-sm text-muted">{faDigits(g.text)}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Holding({ h }: { h: NonNullable<D["decision"]["holding"]> }) {
  return (
    <details data-testid="holding">
      <summary className="cursor-pointer font-semibold">
        اگر بخرم، تا کی نگه دارم و کی بفروشم؟
      </summary>
      <ul className="mt-2 list-inside list-disc space-y-1.5 text-muted">
        {h.lines.map((l) => (
          <li key={l}>{faDigits(l)}</li>
        ))}
      </ul>
    </details>
  );
}

export const DEFAULT_HORIZON = "M1";

/** The verdict for one holding period, with the small gauge beside it. */
function Verdict({
  d,
  h,
  id,
}: {
  d: D["decision"];
  h: NonNullable<D["decision"]["horizons"][number]> | undefined;
  id: number;
}) {
  const verdict = h?.verdict ?? d.verdict;
  const label = h?.verdict_label ?? d.label;
  const weak = h?.weak ?? d.weak ?? false;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3" data-testid="verdict-head">
      <div className="min-w-[15rem] flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`${verdictPill(verdict)} pill-lg`} data-testid="verdict-word">
            <HoldWord verdict={verdict} label={label} instrumentId={id} weak={weak} />
          </span>
          {h && <span className="text-muted">برای {shortLabel(h.label)}</span>}
        </div>
        <p className="text-base font-semibold leading-8">
          {faDigits((h?.headline ?? (d.summary || d.headline)).replace(/^برای [^:]*:\s*/, ""))}
        </p>
        {h && verdict !== "buy" && d.gauge != null && d.gauge >= 90 && (
          <p className="rounded-lg bg-warn-soft p-2 text-sm" data-testid="wait-why">
            چرا با امتیاز بالا «<HoldWord verdict={verdict} label={label} instrumentId={id} />
            »؟ خودِ سهم قوی است، ولی برای {shortLabel(h.label)} سودِ اضافهٔ گذشته
            {h.net_excess != null && <> پس از کارمزد ({signedPct(h.net_excess)})</>} کافی نبوده.
            بازهٔ دیگری را در بالا انتخاب کنید.
          </p>
        )}
      </div>
      <div className="w-36 shrink-0" data-testid="gauge-box">
        <Gauge value={d.gauge} label="جایگاه امروز در بازار" />
        <p className="text-center text-xs text-muted">
          {d.gauge == null
            ? "امتیازی محاسبه نشده"
            : `جایگاه امروز در بازار${d.rank != null ? ` · رتبهٔ ${faNumber(d.rank)}` : ""}`}
        </p>
      </div>
    </div>
  );
}

/** One card for the whole decision, in reading order: the holding period (tabs), its verdict,
 *  the questions behind it with a mark each, the bottom line, and the long explanations closed. */
function Decision({
  d,
  dash,
  horizon,
  id,
}: {
  d: D["decision"];
  dash: D;
  horizon: string;
  id: number;
}) {
  const items = d.horizons;
  const h =
    items.find((x) => x.key === horizon) ??
    items.find((x) => x.key === DEFAULT_HORIZON) ??
    items[0];
  const verdict = h?.verdict ?? d.verdict;
  const more = [...(h?.reasons ?? []), ...d.reasons.slice(1)];
  return (
    <section
      className={`card ${verdictTone(verdict)}`}
      data-testid="symbol-decision"
      data-verdict={verdict}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-extrabold">چه کنم؟</h2>
        <span className="text-xs text-muted">
          {d.as_of ? `بر پایهٔ دادهٔ ${jalali(d.as_of)}` : ""}
        </span>
      </div>
      {items.length > 0 && (
        <nav className="mb-3 flex flex-wrap gap-2" aria-label="بازهٔ نگهداری" id="horizon">
          <span className="self-center text-sm text-muted">تا کی نگه می‌دارید؟</span>
          {items.map((x) => (
            <Link
              key={x.key}
              href={`/instruments/${id}?h=${x.key}#horizon`}
              scroll={false}
              className="tab tab-pill tab-sm"
              aria-current={x.key === h?.key ? "page" : undefined}
              data-testid={`horizon-${x.key}`}
            >
              {shortLabel(x.label)}
              <span className={`${verdictPill(x.verdict)} ms-2`}>
                <HoldWord
                  verdict={x.verdict}
                  label={x.verdict_label}
                  instrumentId={id}
                  weak={x.weak}
                />
              </span>
            </Link>
          ))}
        </nav>
      )}

      <div data-testid="horizons" data-horizon={h?.key} data-verdict={h?.verdict}>
        <Verdict d={d} h={h} id={id} />
      </div>

      {!d.advice_allowed && (
        <p className="mt-3 text-xs text-muted" data-testid="not-advice">
          ⚠ این یک رتبه‌بندی آماری است، نه توصیهٔ سرمایه‌گذاری؛ آزمون‌های اعتبار مدل هنوز کامل
          نشده‌اند.
        </p>
      )}

      <details className="mt-3 border-t border-line pt-3" data-testid="checks-details">
        <summary className="cursor-pointer select-none text-sm font-semibold text-accent">
          چرا؟ چک‌لیست تصمیم
        </summary>
        <div className="mt-3">
          <Checks d={dash} h={h} />
        </div>
      </details>

      <div className="mt-3">
        <TrackBuyButton id={id} symbol={dash.instrument.symbol} />
      </div>

      <div className="mt-4 space-y-2 text-sm">
        <SignalBars signals={d.signals} />
        {d.holding && <Holding h={d.holding} />}
        {more.length > 0 && (
          <details>
            <summary className="cursor-pointer font-semibold">جزئیات برای کارشناس</summary>
            <ul className="mt-2 list-inside list-disc space-y-1.5 text-muted">
              {more.map((r) => (
                <li key={r}>{faDigits(r)}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </section>
  );
}

const FA_VERDICT: Record<string, { label: string; cls: string }> = {
  cheap: { label: "ارزان‌تر از گروه", cls: "v-buy" },
  fair: { label: "نزدیک به گروه", cls: "v-none" },
  expensive: { label: "گران‌تر از گروه", cls: "v-sell" },
  loss: { label: "زیان‌ده", cls: "v-sell" },
  unknown: { label: "نامشخص", cls: "v-none" },
};

function Fundamental({ f, sector }: { f: NonNullable<D["fundamental"]>; sector?: string | null }) {
  const v = FA_VERDICT[f.verdict] ?? FA_VERDICT.unknown;
  return (
    <section className="card" data-testid="fundamental" data-verdict={f.verdict}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="font-bold">سود و ارزش‌گذاری (EPS و P/E)</h2>
        <span className={`pill ${v.cls}`}>{v.label}</span>
      </div>
      <dl>
        <Row
          k="سود هر سهم (EPS)"
          v={f.eps == null ? "—" : `${faNumber(f.eps)} ریال`}
          tone={sign(f.eps)}
        />
        <Row k="P/E این سهم" v={f.pe == null ? "—" : faNumber(f.pe, 1)} />
        <Row
          k={`P/E گروه${sector ? ` «${sector}»` : ""}`}
          v={f.sector_pe == null ? "—" : faNumber(f.sector_pe, 1)}
        />
        {f.vs_sector != null && (
          <Row
            k="نسبت به گروه"
            v={faPercent(f.vs_sector, 0, true)}
            tone={f.vs_sector < 0 ? "text-up" : "text-down"}
          />
        )}
      </dl>
      <p className="mt-2 text-muted">{faDigits(f.text)}</p>
      <p className="mt-1 text-sm text-muted">منبع: بورس تهران (سود پیش‌بینی‌شدهٔ ناشر).</p>
    </section>
  );
}

function Company({ d }: { d: D }) {
  const r = d.ranges;
  const m = d.meeting;
  const baseVol = d.base_volume != null && d.base_volume > 1 ? d.base_volume : null;
  const empty = !m && !r && !baseVol && d.share_changes.length === 0;
  if (empty) return null;
  return (
    <section className="card" data-testid="company">
      <h2 className="mb-1 font-bold">مجمع و اطلاعات شرکت</h2>
      <dl>
        <Row
          k="مجمع بعدی"
          v={
            m
              ? `${jalali(m.date)}${m.clock ? ` ساعت ${faDigits(m.clock)}` : ""} (${m.days_left === 0 ? "امروز" : `${faNumber(m.days_left)} روز دیگر`})`
              : "مجمع اعلام‌شده‌ای ثبت نشده"
          }
        />
        {m && <Row k="نوع مجمع" v={m.kind} />}
        <Row k="حجم مبنا" v={baseVol ? faNumber(baseVol) : "ثبت نشده (۱ یا خالی)"} />
        {r?.week_min != null && r.week_max != null && (
          <Row k="بازهٔ یک هفته" v={`${faNumber(r.week_min)} تا ${faNumber(r.week_max)}`} />
        )}
        {r?.year_min != null && r.year_max != null && (
          <Row k="بازهٔ یک سال" v={`${faNumber(r.year_min)} تا ${faNumber(r.year_max)}`} />
        )}
        {d.share_changes.map((c) => (
          <Row
            key={c.date}
            k={`تغییر سرمایه ${jalali(c.date, "short")}`}
            v={`${faNumber(c.shares_old)} ← ${faNumber(c.shares_new)} سهم${c.change_pct != null ? ` (${faPercent(c.change_pct, 0, true)})` : ""}`}
          />
        ))}
      </dl>
      <p className="mt-2 text-sm text-muted">
        منبع: بورس تهران و کدال. روز مجمع از متن آگهی دعوت خوانده می‌شود؛ اگر آگهی روز را ننوشته
        باشد یا هنوز خوانده نشده باشد، نمایش داده نمی‌شود. حجم مبنا همان عددی است که بورس ثبت کرده و
        برای بیشتر سهم‌ها ۱ است.
      </p>
    </section>
  );
}

function shareOf(part: number | null, whole: number | null): string {
  return part != null && whole ? ` (${faPercent(part / whole, 1)})` : "";
}

/** The decision card: verdict per holding period, the synthesis and the plain answers. */
export function SymbolDecision({ d, id, horizon }: { d: D; id: number; horizon?: string }) {
  return (
    <div className="space-y-4" data-testid="symbol-dashboard">
      <Decision d={d.decision} dash={d} horizon={horizon ?? DEFAULT_HORIZON} id={id} />
      <PriceRange d={d} />
    </div>
  );
}

/** Where the stock stands: its current state's past record, what moves it, and its group. */
export function SymbolContext({ d }: { d: D }) {
  return (
    <>
      {d.turning && <TurningCard t={d.turning} />}
      {d.drivers && <DriversCard d={d.drivers} />}
      {d.peers && <PeersCard p={d.peers} />}
    </>
  );
}

export function SymbolTechnical({ d }: { d: D }) {
  return d.technical ? <TechnicalCard t={d.technical} /> : null;
}

export function SymbolCompany({ d }: { d: D }) {
  return <Company d={d} />;
}

export function SymbolValuation({ d }: { d: D }) {
  return <>{d.fundamental && <Fundamental f={d.fundamental} sector={d.sector_name} />}</>;
}

/** Today's price, trades, real/legal money and the symbol's facts. */
export function SymbolFacts({ d }: { d: D }) {
  const p = d.price;
  const f = d.flow;
  const buyTot =
    f && f.buy_volume_i != null && f.buy_volume_n != null ? f.buy_volume_i + f.buy_volume_n : null;
  const sellTot =
    f && f.sell_volume_i != null && f.sell_volume_n != null
      ? f.sell_volume_i + f.sell_volume_n
      : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {p && (
          <Card title="قیمت" note={`روز ${jalali(p.date)}`}>
            <Row k="قیمت پایانی" v={p.close == null ? "—" : faNumber(p.close)} />
            <Row
              k="تغییر پایانی"
              v={p.close_change == null ? "—" : faPercent(p.close_change, 2, true)}
              tone={sign(p.close_change)}
            />
            <Row k="آخرین معامله" v={p.last == null ? "—" : faNumber(p.last)} />
            <Row
              k="تغییر آخرین معامله"
              v={p.last_change == null ? "—" : faPercent(p.last_change, 2, true)}
              tone={sign(p.last_change)}
            />
            <Row k="قیمت دیروز" v={p.prev_close == null ? "—" : faNumber(p.prev_close)} />
            <Row k="اولین قیمت" v={p.open == null ? "—" : faNumber(p.open)} />
            <RangeBar title="بازهٔ قیمت امروز" lo={p.low} hi={p.high} at={p.close} />
            <RangeBar
              title="دامنهٔ مجاز نوسان"
              lo={p.limit_down}
              hi={p.limit_up}
              at={p.close}
              mark={p.prev_close}
            />
          </Card>
        )}

        {p && (
          <Card
            title="معاملات"
            note="میانگین‌ها از روزهای معاملاتی اخیر محاسبه شده‌اند؛ نسبت حجم، حجم امروز تقسیم بر میانگین ۳۰ روز قبل است."
          >
            <Row k="تعداد معاملات" v={p.trades == null ? "—" : faNumber(p.trades)} />
            <Row k="حجم معاملات" v={qty(p.volume)} />
            <Row k="ارزش معاملات" v={toman(p.value)} />
            <Row k="میانگین حجم ۱۰ روزه" v={qty(p.avg_volume_10)} />
            <Row k="میانگین حجم ۲۲ روزه" v={qty(p.avg_volume_22)} />
            <Row
              k="نسبت حجم امروز به ۳۰ روز"
              v={p.volume_ratio_30 == null ? "—" : faNumber(p.volume_ratio_30, 2)}
              tone={p.volume_ratio_30 != null && p.volume_ratio_30 >= 1.5 ? "text-up" : ""}
            />
            {p.base_volume != null && <Row k="حجم مبنا" v={qty(p.base_volume)} />}
          </Card>
        )}

        {f && (
          <Card title="پول حقیقی و حقوقی" note={`روز ${jalali(f.date)}`}>
            <Row
              k="خرید حقیقی"
              v={`${qty(f.buy_volume_i)} سهم${shareOf(f.buy_volume_i ?? null, buyTot)}`}
            />
            <Row
              k="فروش حقیقی"
              v={`${qty(f.sell_volume_i)} سهم${shareOf(f.sell_volume_i ?? null, sellTot)}`}
            />
            <Row
              k="خرید حقوقی"
              v={`${qty(f.buy_volume_n)} سهم${shareOf(f.buy_volume_n ?? null, buyTot)}`}
            />
            <Row
              k="فروش حقوقی"
              v={`${qty(f.sell_volume_n)} سهم${shareOf(f.sell_volume_n ?? null, sellTot)}`}
            />
            <Row
              k="خالص ورود پول حقیقی"
              v={toman(f.net_real_value)}
              tone={sign(f.net_real_value)}
            />
            <Row
              k="تعداد خریدار / فروشندهٔ حقیقی"
              v={`${f.buy_count_i == null ? "—" : faNumber(f.buy_count_i)} / ${f.sell_count_i == null ? "—" : faNumber(f.sell_count_i)}`}
            />
            <Row
              k="تعداد خریدار / فروشندهٔ حقوقی"
              v={`${f.buy_count_n == null ? "—" : faNumber(f.buy_count_n)} / ${f.sell_count_n == null ? "—" : faNumber(f.sell_count_n)}`}
            />
          </Card>
        )}

        {f && (
          <Card
            title="سرانه و قدرت خریدار"
            note="سرانه = ارزش خرید (یا فروش) حقیقی تقسیم بر تعداد کدهای حقیقی. قدرت خریدار = سرانهٔ خرید ÷ سرانهٔ فروش."
          >
            <Row k="سرانهٔ خرید (امروز)" v={toman(f.per_capita_buy)} />
            <Row k="سرانهٔ خرید (میانگین ۱۰ روز)" v={toman(f.avg10_per_capita_buy)} />
            <Row k="سرانهٔ فروش (امروز)" v={toman(f.per_capita_sell)} />
            <Row k="سرانهٔ فروش (میانگین ۱۰ روز)" v={toman(f.avg10_per_capita_sell)} />
            <Row
              k="قدرت خریدار (امروز)"
              v={f.power == null ? "—" : faNumber(f.power, 2)}
              tone={f.power != null ? (f.power >= 1 ? "text-up" : "text-down") : ""}
            />
            <Row
              k="قدرت خریدار (میانگین ۱۰ روز)"
              v={f.avg10_power == null ? "—" : faNumber(f.avg10_power, 2)}
            />
          </Card>
        )}

        <Card title="اطلاعات نماد">
          {d.sector_name && <Row k="گروه صنعت" v={d.sector_name} />}
          {d.board && <Row k="بازار" v={d.board} />}
          {d.isin && <Row k="شناسهٔ ISIN" v={<bdi dir="ltr">{d.isin}</bdi>} />}
          {d.shares != null && <Row k="تعداد سهام" v={qty(d.shares)} />}
          {d.market_cap != null && <Row k="ارزش بازار" v={toman(d.market_cap)} />}
          {d.fund && (
            <>
              <Row k="ارزش ابطال (NAV)" v={faNumber(d.fund.nav)} />
              <Row
                k="حباب صندوق"
                v={d.fund.bubble == null ? "—" : faPercent(d.fund.bubble, 2, true)}
                tone={d.fund.bubble != null && Math.abs(d.fund.bubble) > 0.03 ? "text-down" : ""}
              />
              <Row k="تاریخ NAV" v={jalali(d.fund.nav_date)} />
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
