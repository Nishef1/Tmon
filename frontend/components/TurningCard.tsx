import { NEAR_HIGH, nearHighNote, toneWord } from "@/components/stock/nearHigh";
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

const per100 = (n: number | null | undefined) => (n == null ? "—" : faNumber(Math.round(n * 100)));
/** "X% more/less than the market" with one positive number, so a minus never sits next to "profit". */
const vsMarket = (x: number | null | undefined) =>
  x == null ? "—" : `${faPercent(Math.abs(x), 1)} ${x >= 0 ? "بیشتر" : "کمتر"} از بازار`;
const pct = (n: number | null | undefined, d = 0) => (n == null ? "—" : faPercent(n, d));
const h120 = (s: S) => s.horizons.find((h) => h.horizon_days === 120) ?? null;

function ToneLabel({ s }: { s: S }) {
  const t = TONE[s.tone];
  return <span className={`pill ${t.cls}`}>{toneWord(s) ?? t.label}</span>;
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
          سهم‌هایی که در همین حالت بودند، در شش ماه بعد به‌طور میانگین{" "}
          <b className={signTone(h.excess_mean)}>{vsMarket(h.excess_mean)}</b> سود کردند و{" "}
          <b>{per100(h.beat)}</b> بار از هر ۱۰۰ بار از بازار جلو زدند
          {b?.beat != null && <> (برای همهٔ سهم‌ها {per100(b.beat)} بار)</>}.
          {h1 != null && h2 != null && Math.sign(h1) !== Math.sign(h2) && (
            <> این نتیجه در همهٔ سال‌ها یکسان نبوده و قابل اتکا نیست.</>
          )}
        </>
      ),
    },
    {
      q: "شانس جهش بزرگ یا ریزش سنگین در شش ماه",
      a: (
        <>
          از هر ۱۰۰ بار، <b className="text-up">{per100(h.p_up50)}</b> بار قیمت دست‌کم ۵۰٪ بالا رفت
          و <b className="text-down">{per100(h.p_dn20)}</b> بار دست‌کم ۲۰٪ پایین آمد
          {b && (
            <>
              {" "}
              (برای همهٔ سهم‌ها: {per100(b.p_up50)} بار جهش، {per100(b.p_dn20)} بار ریزش)
            </>
          )}
          .
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
          این میانگین را چند سهم با سود خیلی بزرگ بالا برده‌اند؛ بیشتر سهم‌ها سود چشمگیری نداشتند.
        </p>
      )}
    </dl>
  );
}

function HorizonTable({ s }: { s: S; base: S }) {
  if (s.horizons.length === 0) return null;
  return (
    <ul className="mt-3 space-y-1 text-sm" data-testid="turning-horizons">
      {s.horizons.map((h) => (
        <li key={h.horizon_days}>
          بعد از <b>{HORIZON_FA[h.horizon_days] ?? `${faNumber(h.horizon_days)} روز`}</b>:{" "}
          <b className={signTone(h.excess_mean)}>{vsMarket(h.excess_mean)}</b> سود، و{" "}
          {per100(h.beat)} بار از ۱۰۰ بار جلوتر از بازار.
        </li>
      ))}
    </ul>
  );
}

function Now({ t }: { t: T }) {
  const note = nearHighNote(t);
  const items: [string, ReactNode, string?][] = [
    ["فاصله از سقف ۵۲ هفته", t.dd != null && t.dd >= NEAR_HIGH ? "نزدیک سقف" : pct(t.dd, 0)],
    ["بازده ۲۰ روز", signedPct(t.ret20, 0), signTone(t.ret20)],
    ["بازده ۶۰ روز", signedPct(t.ret60, 0), signTone(t.ret60)],
    [
      "خالص خرید حقیقی (۵ روز)",
      t.net5 == null ? "هنوز نیامده" : signedPct(t.net5, 1),
      signTone(t.net5),
    ],
    [
      "قدرت خریدار حقیقی (۵ روز)",
      t.power5 == null
        ? "هنوز نیامده"
        : t.power5 > 1.05
          ? "خریداران قوی‌ترند"
          : t.power5 < 0.95
            ? "فروشندگان قوی‌ترند"
            : "برابر",
    ],
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
      {note && (
        <p className="col-span-full text-sm text-muted" data-testid="near-high-note">
          {note}
        </p>
      )}
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
                  در گذشته بعد از آن حالت: شش ماه بعد {signedPct(h.excess_mean)} نسبت به بازار؛ از
                  هر ۱۰۰ بار {per100(h.p_up50)} بار جهش ۵۰٪ و {per100(h.p_dn20)} بار ریزش ۲۰٪.
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The one sell warning that held in both halves of the history, when it fired lately. */
function Warning({ w }: { w: NonNullable<T["warning"]> }) {
  const h = w.horizons.find((x) => x.horizon_days === 60);
  const [a, b] = w.halves_excess_60;
  return (
    <div className="tile mb-3 !p-3" data-testid="turning-warning">
      <div className="flex flex-wrap items-center gap-2">
        <span className="pill v-sell">هشدار آزموده‌شده</span>
        <span className="font-semibold">{w.title}</span>
      </div>
      <p className="mt-1 text-sm">
        {faDigits(w.meaning)} آخرین بار:{" "}
        {w.days_ago === 0 ? "آخرین روز معامله" : `${faNumber(w.days_ago)} روز معاملاتی پیش`} (
        {jalali(w.date, "short")}).
      </p>
      {h && (
        <p className="mt-1 text-sm">
          در {faNumber(w.n)} بار مشابه در گذشته، سهم در سه ماه بعد به‌طور میانگین{" "}
          <b className={signTone(h.excess_mean)}>{signedPct(h.excess_mean)}</b> نسبت به بازار ماند
          {a != null && b != null && (
            <>
              {" "}
              (نیمهٔ اول تاریخ {signedPct(a)}، نیمهٔ دوم {signedPct(b)})
            </>
          )}{" "}
          و فقط {per100(h.beat)} بار از ۱۰۰ بار از بازار جلو زدند. یعنی خریدن در این روزها در گذشته
          بدتر از بازار بوده؛ ولی اثر کوچک و پراکنده است و این نشانه به‌تنهایی برای فروش کافی نیست.
        </p>
      )}
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
      {t.warning && <Warning w={t.warning} />}
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
          ۶۰٪ پرمعامله‌ترین نمادهای هر روز. ورود با قیمت پایانی روز بعد از دیدن نشانه، قیمت‌ها
          تعدیل‌شده (یعنی افزایش سرمایه و سود نقدی افت حساب نمی‌شود)، و «سود اضافه» یعنی بازده نماد
          منهای میانگین بازده همهٔ همین نمادها در همان روزها. «سهم وسط» (میانه) یعنی اگر همهٔ موردها
          را از بد به خوب بچینیم، وسطی؛ میانگین را چند برندهٔ بزرگ بالا می‌کشند، میانه نه. حالت‌ها و
          آستانه‌ها پیش از دیدن نتیجهٔ هر نماد ثابت شده‌اند و برچسب «بهتر» یا «بدتر از بازار» فقط
          وقتی داده می‌شود که هر دو نیمهٔ تاریخ هم‌جهت باشند و از کارمزد و مالیات خرید و فروش (
          {faPercent(t.round_trip_cost, 2)}) بیشتر باشند. روزهای پشت‌سرهم یک دوره هم‌پوشانی دارند،
          پس تعداد دوره‌های مستقل از تعداد روز-سهم بسیار کمتر است.
        </p>
        <p className="mt-1">
          این آمار گذشتهٔ سهم‌های مشابه است، نه پیش‌بینی همین سهم و نه توصیهٔ خرید یا فروش.
          {!t.liquid &&
            " این نماد امروز جزو ۶۰٪ پرمعامله نیست و ممکن است رفتارش با این آمار فرق کند."}
          {` آخرین داده: ${jalali(t.as_of)}.`}
        </p>
      </details>
    </section>
  );
}
