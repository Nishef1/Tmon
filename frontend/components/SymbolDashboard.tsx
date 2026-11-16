import Link from "next/link";
import { HoldWord } from "@/components/stock/HoldWord";
import type { ReactNode } from "react";
import type { InstrumentDashboard } from "@/lib/api";
import { Gauge } from "@/components/Gauge";
import { TrackBuyButton } from "@/components/TrackBuyButton";
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

const sign = (n: number | null | undefined) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");

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

const DEFAULT_HORIZON = "M1";

/** The verdict for one holding period, with the small gauge beside it. */
export function Verdict({
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
        {h && verdict !== "buy" && !h.vetoed && d.gauge != null && d.gauge >= 90 && (
          <p className="rounded-lg bg-warn-soft p-2 text-sm" data-testid="wait-why">
            چرا با امتیاز بالا «<HoldWord verdict={verdict} label={label} instrumentId={id} />
            »؟ خودِ سهم قوی است، ولی برای {shortLabel(h.label)} سودِ اضافهٔ گذشته
            {h.net_excess != null && <> پس از کارمزد ({signedPct(h.net_excess)})</>} کافی نبوده است.
            بازهٔ دیگری را در بالا انتخاب کنید.
          </p>
        )}
      </div>
      <div className="w-40 shrink-0" data-testid="gauge-box">
        <Gauge
          value={d.gauge}
          label="جایگاه امروز در بازار"
          zones={
            d.zone_hold_from != null && d.zone_buy_from != null
              ? { hold: d.zone_hold_from, buy: d.zone_buy_from }
              : undefined
          }
        />
        <p className="text-center text-xs text-muted">
          {d.gauge == null
            ? "امتیازی محاسبه نشده"
            : `جایگاه امروز در بازار${d.rank != null ? ` · رتبهٔ ${faNumber(d.rank)}` : ""}`}
        </p>
        {d.gauge != null && verdict !== "buy" && d.gauge >= (d.zone_buy_from ?? 90) && (
          <p className="text-center text-xs text-muted" data-testid="gauge-not-advice">
            این فقط رتبه است؛ توصیه همان کلمهٔ کنارش است.
          </p>
        )}
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

      <details className="mt-3 border-t border-line pt-3" data-testid="checks-details" open>
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
        {d.holding && <Holding h={d.holding} />}
        {(more.length > 0 || d.signals.length > 0) && (
          <details>
            <summary className="cursor-pointer font-semibold">جزئیات برای کارشناس</summary>
            <div className="mt-2 space-y-3">
              <SignalBars signals={d.signals} />
              {more.length > 0 && (
                <ul className="list-inside list-disc space-y-1.5 text-muted">
                  {more.map((r) => (
                    <li key={r}>{faDigits(r)}</li>
                  ))}
                </ul>
              )}
            </div>
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
        <Row k="حجم مبنا" v={baseVol && baseVol > 1 ? faNumber(baseVol) : "ندارد"} />
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
        باشد یا هنوز خوانده نشده باشد، نمایش داده نمی‌شود. حجم مبنا کمترین حجم معامله‌ای است که باید
        انجام شود تا دامنهٔ مجاز نوسان روز بعد کامل اعمال شود؛ بورس آن را ثبت می‌کند و برای بیشتر
        سهم‌ها وجود ندارد (عدد ۱ یا خالی).
      </p>
    </section>
  );
}

/** The decision card: verdict per holding period, the synthesis and the plain answers. */
export function SymbolDecision({ d, id, horizon }: { d: D; id: number; horizon?: string }) {
  return (
    <div data-testid="symbol-dashboard">
      <Decision d={d.decision} dash={d} horizon={horizon ?? DEFAULT_HORIZON} id={id} />
    </div>
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

function Split({
  title,
  real,
  legal,
}: {
  title: string;
  real: number | null | undefined;
  legal: number | null | undefined;
}) {
  if (real == null || legal == null || real + legal <= 0) return null;
  const tot = real + legal;
  const r = real / tot;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold">{title}</span>
        <span className="text-muted">
          حقیقی {faPercent(r, 0)} · حقوقی {faPercent(1 - r, 0)}
        </span>
      </div>
      <div
        className="flex h-3 gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`${title}: حقیقی ${faPercent(r, 0)}، حقوقی ${faPercent(1 - r, 0)}`}
      >
        <span className="bg-accent" style={{ width: `${r * 100}%` }} />
        <span style={{ width: `${(1 - r) * 100}%`, background: "var(--series-1)" }} />
      </div>
    </div>
  );
}

/** Who is buying and selling today, as two bars (real people against institutions) and the
 *  per-capita line. */
export function SymbolFlow({ d }: { d: D }) {
  const f = d.flow;
  if (!f) return null;
  return (
    <section className="space-y-3" data-testid="flow-summary">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold">خریدار و فروشنده امروز چه کسانی‌اند؟</h2>
        <span className="flex gap-3 text-xs text-muted">
          <span className="flex items-center gap-1">
            <i className="inline-block size-2.5 rounded-sm bg-accent" aria-hidden />
            حقیقی
          </span>
          <span className="flex items-center gap-1">
            <i
              className="inline-block size-2.5 rounded-sm"
              style={{ background: "var(--series-1)" }}
              aria-hidden
            />
            حقوقی
          </span>
        </span>
      </div>
      <Split title="خرید" real={f.buy_volume_i} legal={f.buy_volume_n} />
      <Split title="فروش" real={f.sell_volume_i} legal={f.sell_volume_n} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <Row k="سرانهٔ خرید حقیقی" v={toman(f.per_capita_buy)} />
        <Row k="سرانهٔ فروش حقیقی" v={toman(f.per_capita_sell)} />
        <Row
          k="قدرت خریدار"
          v={f.power == null ? "—" : faNumber(f.power, 2)}
          tone={f.power != null ? (f.power >= 1 ? "text-up" : "text-down") : ""}
        />
        {f.net_real_value == null && f.net_real_volume != null ? (
          <Row
            k="خالص ورود حقیقی‌ها (به سهم)"
            v={`${f.net_real_volume < 0 ? "−" : ""}${qty(Math.abs(f.net_real_volume))} سهم`}
            tone={sign(f.net_real_volume)}
          />
        ) : (
          <Row k="خالص ورود پول حقیقی" v={toman(f.net_real_value)} tone={sign(f.net_real_value)} />
        )}
      </dl>
    </section>
  );
}

/** The few numbers the header and the flow bars do not already show, as one line. */
export function SymbolFacts({ d }: { d: D }) {
  const p = d.price;
  const f = d.flow;
  const rows: [string, ReactNode][] = [];
  if (p?.last != null) {
    rows.push([
      "آخرین معامله",
      <>
        {faNumber(p.last)}
        {p.last_change != null && (
          <span className={sign(p.last_change)}> ({faPercent(p.last_change, 2, true)})</span>
        )}
      </>,
    ]);
  }
  if (p?.limit_down != null && p.limit_up != null) {
    rows.push(["دامنهٔ مجاز نوسان", `${faNumber(p.limit_down)} تا ${faNumber(p.limit_up)}`]);
  }
  if (p?.avg_volume_10 != null) rows.push(["میانگین حجم ۱۰ روزه", qty(p.avg_volume_10)]);
  if (p?.avg_volume_22 != null) rows.push(["میانگین حجم ۲۲ روزه", qty(p.avg_volume_22)]);
  if (p?.base_volume != null && p.base_volume > 1) rows.push(["حجم مبنا", qty(p.base_volume)]);
  if (f?.buy_count_i != null && f.sell_count_i != null) {
    rows.push([
      "خریدار / فروشندهٔ حقیقی",
      `${faNumber(f.buy_count_i)} / ${faNumber(f.sell_count_i)}`,
    ]);
  }
  if (d.shares != null) rows.push(["تعداد سهام", qty(d.shares)]);
  if (d.isin)
    rows.push([
      "ISIN",
      <bdi key="isin" dir="ltr">
        {d.isin}
      </bdi>,
    ]);
  if (d.fund) {
    rows.push(["ارزش خالص دارایی (NAV ابطال)", faNumber(d.fund.nav)]);
    if (d.fund.bubble != null) {
      rows.push(["حباب صندوق (قیمت بازار نسبت به NAV)", faPercent(d.fund.bubble, 2, true)]);
    }
  }
  if (rows.length === 0) return null;
  return (
    <dl
      className="flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-sm"
      data-testid="facts-line"
    >
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-1.5">
          <dt className="text-muted">{k}</dt>
          <dd className="font-semibold">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
