import type { ReactNode } from "react";
import type { InstrumentDashboard } from "@/lib/api";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";
import { signedPct, signTone } from "@/lib/ui";

type T = NonNullable<InstrumentDashboard["turning"]>;
type S = T["state"];

const HORIZON_FA: Record<number, string> = { 20: "یک ماه", 60: "سه ماه", 120: "شش ماه" };

const TONE: Record<S["tone"], { label: string; cls: string }> = {
  up: { label: "در گذشته بهتر از بازار", cls: "v-buy" },
  down: { label: "در گذشته بدتر از بازار", cls: "v-sell" },
  none: { label: "سابقهٔ پایداری ندارد", cls: "v-none" },
};

const pct = (n: number | null | undefined, d = 0) => (n == null ? "—" : faPercent(n, d));
const h120 = (s: S) => s.horizons.find((h) => h.horizon_days === 120) ?? null;

function ToneLabel({ s }: { s: S }) {
  const t = TONE[s.tone];
  return <span className={`pill ${t.cls}`}>{t.label}</span>;
}

/** The three questions a reader asks at a turning point, answered from this state's history. */
function Answers({ t }: { t: T }) {
  const s = t.state;
  const h = h120(s);
  const b = h120(t.base);
  if (!h) return <p className="text-muted">برای این حالت نمونهٔ کافی در گذشته نیست.</p>;
  const [h1, h2] = s.halves_excess_120;
  const lines: { q: string; a: ReactNode }[] = [
    {
      q: "در گذشته بعد از این حالت چه شده؟",
      a: (
        <>
          در {faNumber(s.n)} روز-سهم مشابه ({faNumber(s.episodes ?? 0)} دوره در{" "}
          {faNumber(s.symbols ?? 0)} نماد)، بازدهٔ شش ماه بعد به‌طور میانگین{" "}
          <b className={signTone(h.excess_mean)}>{signedPct(h.excess_mean)}</b> نسبت به میانگین
          بازار بوده و {pct(h.beat)} موارد از بازار جلو زده‌اند.
          {h1 != null && h2 != null && (
            <>
              {" "}
              نیمهٔ اول تاریخ (تا {jalali(t.split_date, "short")}):{" "}
              <b className={signTone(h1)}>{signedPct(h1)}</b>، نیمهٔ دوم:{" "}
              <b className={signTone(h2)}>{signedPct(h2)}</b>.
            </>
          )}
        </>
      ),
    },
    {
      q: "اگر الان بخرم، قبل از هر سودی چقدر ممکن است پایین برود؟",
      a:
        s.mae60_median == null ? (
          "نامعلوم"
        ) : (
          <>
            در نیمی از موارد قیمت در ۶۰ روز بعد از ورود تا{" "}
            <b className="text-down">{faPercent(-s.mae60_median, 0)}</b> پایین‌تر رفت و در یک‌دهم
            بدترین موارد تا <b className="text-down">{faPercent(-(s.mae60_p10 ?? 0), 0)}</b>
            {t.base.mae60_median != null && (
              <> (برای همهٔ سهم‌ها: {faPercent(-t.base.mae60_median, 0)})</>
            )}
            .
          </>
        ),
    },
    {
      q: "شانس جهش بزرگ در برابر ریزش سنگین",
      a: (
        <>
          شانس دست‌کم <b className="text-up">{faPercent(0.5, 0, true)}</b> در شش ماه:{" "}
          <b>{pct(h.p_up50)}</b>
          {b && <> (همهٔ سهم‌ها {pct(b.p_up50)})</>}؛ شانس افت دست‌کم{" "}
          <b className="text-down">۲۰٪</b>: <b>{pct(h.p_dn20)}</b>
          {b && <> (همهٔ سهم‌ها {pct(b.p_dn20)})</>}.
        </>
      ),
    },
  ];
  return (
    <dl className="space-y-3" data-testid="turning-answers">
      {lines.map((l) => (
        <div key={l.q}>
          <dt className="font-semibold">{l.q}</dt>
          <dd className="mt-0.5">{l.a}</dd>
        </div>
      ))}
      {s.skewed && (
        <p className="text-sm text-muted">
          میانگین را چند برندهٔ بزرگ بالا برده‌اند؛ مورد میانه {signedPct(h.excess_median)} نسبت به
          بازار بوده (برای همهٔ سهم‌ها {signedPct(b?.excess_median)}). یعنی بیشتر موارد سود چشمگیری
          نداشتند و نتیجه به چند برگشت بزرگ بسته بود.
        </p>
      )}
    </dl>
  );
}

function HorizonTable({ s, base }: { s: S; base: S }) {
  if (s.horizons.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm" data-testid="turning-horizons">
        <thead className="text-muted">
          <tr>
            <th className="py-1 text-start font-normal">بازه</th>
            <th className="py-1 font-normal">مازاد میانگین</th>
            <th className="py-1 font-normal">مازاد میانه</th>
            <th className="py-1 font-normal">جلوتر از بازار</th>
            <th className="py-1 font-normal">میانهٔ همهٔ سهم‌ها</th>
          </tr>
        </thead>
        <tbody>
          {s.horizons.map((h) => {
            const b = base.horizons.find((x) => x.horizon_days === h.horizon_days);
            return (
              <tr key={h.horizon_days} className="border-t border-line text-center">
                <td className="py-1 text-start">{HORIZON_FA[h.horizon_days] ?? h.horizon_days}</td>
                <td className={`py-1 ${signTone(h.excess_mean)}`}>{signedPct(h.excess_mean)}</td>
                <td className={`py-1 ${signTone(h.excess_median)}`}>
                  {signedPct(h.excess_median)}
                </td>
                <td className="py-1">{pct(h.beat)}</td>
                <td className={`py-1 ${signTone(b?.excess_median)}`}>
                  {signedPct(b?.excess_median)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Now({ t }: { t: T }) {
  const items: [string, ReactNode, string?][] = [
    ["فاصله از سقف ۵۲ هفته", pct(t.dd, 0), signTone(t.dd)],
    ["بازده ۲۰ روز", signedPct(t.ret20, 0), signTone(t.ret20)],
    ["بازده ۶۰ روز", signedPct(t.ret60, 0), signTone(t.ret60)],
    ["خالص خرید حقیقی (۵ روز)", signedPct(t.net5, 1), signTone(t.net5)],
    ["قدرت خریدار (۵ روز)", t.power5 == null ? "—" : faNumber(t.power5, 2)],
    [
      "نسبت به میانگین ۲۰ روزه",
      t.above_sma20 == null ? "—" : t.above_sma20 ? "بالای آن" : "زیر آن",
    ],
    [
      "کل بازار",
      t.market_bull == null
        ? "—"
        : `${t.market_bull ? "صعودی" : "نزولی"}${t.market_drawdown != null ? (t.market_drawdown > -0.01 ? "، نزدیک سقف یک‌ساله" : `، ${faPercent(-t.market_drawdown, 0)} زیر سقف یک‌ساله`) : ""}`,
    ],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="turning-now">
      {items.map(([k, v, tone]) => (
        <div key={k} className="tile !p-2">
          <div className="text-xs text-muted">{k}</div>
          <div className={`font-semibold ${tone ?? ""}`}>{v}</div>
        </div>
      ))}
    </div>
  );
}

function Triggers({ t }: { t: T }) {
  if (t.triggers.length === 0) return null;
  return (
    <div className="mt-4" data-testid="turning-triggers">
      <h3 className="mb-1 font-bold">چه چیزی تصویر را عوض می‌کند؟</h3>
      <ul className="space-y-2">
        {t.triggers.map((g) => {
          const h = h120(g.state);
          return (
            <li key={g.state.key} className="tile !p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{g.state.title}</span>
                <ToneLabel s={g.state} />
              </div>
              <p className="text-sm">اگر: {faDigits(g.when)}</p>
              {h && (
                <p className="text-sm text-muted">
                  سابقهٔ آن حالت: شش ماه بعد {signedPct(h.excess_mean)} نسبت به بازار (میانه{" "}
                  {signedPct(h.excess_median)})، شانس {faPercent(0.5, 0, true)}: {pct(h.p_up50)}،
                  شانس {faPercent(-0.2, 0, true)}: {pct(h.p_dn20)}.
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Where the symbol stands in its fall or run-up, and what happened to symbols in that place. */
export function TurningCard({ t }: { t: T }) {
  const s = t.state;
  return (
    <section className="card" data-testid="turning" data-state={s.key} data-tone={s.tone}>
      <h2 className="mb-1 font-bold">کف یا سقف؟ جای این سهم در ریزش و رشد</h2>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="pill pill-lg v-none">{s.title}</span>
        <ToneLabel s={s} />
      </div>
      <p className="mb-3">{faDigits(s.meaning)}</p>
      <Now t={t} />
      <div className="mt-4">
        <Answers t={t} />
      </div>
      <HorizonTable s={s} base={t.base} />
      <Triggers t={t} />
      <details className="mt-3 text-sm text-muted">
        <summary className="cursor-pointer font-semibold">این اعداد از کجا آمده‌اند؟</summary>
        <p className="mt-1">
          همهٔ روزهای {jalali(t.history_first, "short")} تا {jalali(t.history_last, "short")} برای
          ۶۰٪ نقدشونده‌ترین نمادهای هر روز. ورود با قیمت پایانی روز بعد از دیدن نشانه، قیمت‌ها
          تعدیل‌شده، و «مازاد» یعنی بازده نماد منهای میانگین بازده همهٔ همین نمادها در همان روزها.
          حالت‌ها و آستانه‌ها پیش از دیدن نتیجهٔ هر نماد ثابت شده‌اند و برچسب «بهتر» یا «بدتر از
          بازار» فقط وقتی داده می‌شود که هر دو نیمهٔ تاریخ هم‌جهت باشند و از هزینهٔ رفت‌وبرگشت (
          {faPercent(t.round_trip_cost, 2)}) بیشتر باشند. روزهای پشت‌سرهم یک دوره هم‌پوشانی دارند،
          پس تعداد دوره‌های مستقل از تعداد روز-سهم بسیار کمتر است.
        </p>
        <p className="mt-1">
          این آمار گذشتهٔ سهم‌های مشابه است، نه پیش‌بینی همین سهم و نه توصیهٔ خرید یا فروش.
          {!t.liquid &&
            " این نماد امروز جزو ۶۰٪ نقدشونده نیست و ممکن است رفتارش با این آمار فرق کند."}
          {` آخرین داده: ${jalali(t.as_of)}.`}
        </p>
      </details>
    </section>
  );
}
