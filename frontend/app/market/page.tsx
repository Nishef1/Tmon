import type { Metadata } from "next";
import { apiGet, type MarketOverview, type MarketMover } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";

export const metadata: Metadata = { title: "نمای بازار" };
export const dynamic = "force-dynamic";

/** Rial -> billion toman (1 toman = 10 rial). */
function bt(rial: number, digits = 0): string {
  const sign = rial < 0 ? "−" : "";
  const toman = Math.abs(rial) / 10;
  if (toman >= 1e9) return `${sign}${faNumber(toman / 1e9, digits)} میلیارد تومان`;
  return `${sign}${faNumber(toman / 1e6, toman < 1e8 ? 1 : 0)} میلیون تومان`;
}

export default async function MarketPage() {
  const res = await apiGet<MarketOverview>("/market/overview");
  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">نمای بازار</h1>
        <p className="mt-1 text-sm text-muted">
          خلاصهٔ پایان روز از دادهٔ روزانه: دامنهٔ بازار، پول حقیقی و حقوقی، برترین‌ها. دادهٔ
          لحظه‌ای (پول هوشمند آنی، سفارش‌های درشت، اختیار معامله) در دست ما نیست و نمایش داده
          نمی‌شود.
        </p>
      </div>
      <Disclaimer />
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : !res.data.available ? (
        <p className="text-sm text-muted" data-testid="market-unavailable">
          داده‌ای برای نمای بازار نیست.
        </p>
      ) : (
        <Body d={res.data} />
      )}
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-lg font-bold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function Body({ d }: { d: MarketOverview }) {
  const maxBand = Math.max(1, ...d.bands.map((b) => b.count));
  const f = d.flow;
  return (
    <>
      <section className="space-y-2" data-testid="market-breadth">
        <h2 className="text-lg font-bold">دامنهٔ بازار — {jalali(d.price_date)}</h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="سهم‌های مثبت" value={faNumber(d.up)} tone="text-good" />
          <Stat label="سهم‌های منفی" value={faNumber(d.down)} tone="text-bad" />
          <Stat label="بدون تغییر" value={faNumber(d.flat)} />
          <Stat
            label="میانهٔ تغییر"
            value={d.median_change == null ? "—" : faPercent(d.median_change, 2, true)}
          />
          <Stat label="رشد ≥ ۲٫۹٪ (نزدیک سقف ±۳٪)" value={faNumber(d.at_limit_up)} />
          <Stat label="افت ≥ ۲٫۹٪ (نزدیک کف)" value={faNumber(d.at_limit_down)} />
          <Stat label="ارزش معاملات سهام" value={bt(d.total_value)} />
          {d.indices.map((i) => (
            <Stat
              key={i.code}
              label={`${i.code} — ${jalali(i.date)}`}
              value={`${faNumber(i.close, 0)}${i.change == null ? "" : ` · ${faPercent(i.change, 2, true)}`}`}
            />
          ))}
        </div>
        <p className="text-xs text-muted">
          تغییر = قیمت پایانی نسبت به پایانی روز قبل. سهم‌های متوقف و {faNumber(d.n_outliers)} سهم
          با تغییر بیش از ۵۰٪ (قیمت مرجع قدیمی پس از بازگشایی) در شمارش نیامده‌اند.
        </p>
        <div className="space-y-1" data-testid="market-bands">
          <h3 className="pt-2 text-sm font-semibold">توزیع تغییر قیمت پایانی نسبت به دیروز</h3>
          {d.bands.map((b) => (
            <div key={b.label} className="flex items-center gap-2 text-xs">
              <span className="w-28 shrink-0">{b.label}</span>
              <div className="h-3 flex-1 rounded bg-accent-soft">
                <div
                  className="h-3 rounded bg-accent"
                  style={{ width: `${(100 * b.count) / maxBand}%` }}
                />
              </div>
              <span className="w-10 text-left">{faNumber(b.count)}</span>
            </div>
          ))}
        </div>
      </section>

      {f && (
        <section className="space-y-2" data-testid="market-flow">
          <h2 className="text-lg font-bold">پول حقیقی و حقوقی — {jalali(f.date)}</h2>
          <p className="text-xs text-muted">
            آخرین روزی که دادهٔ خریدار/فروشنده برای تقریباً همهٔ نمادها ({faNumber(f.n_symbols)}{" "}
            سهم) ثبت شده است؛ ممکن است یک روز عقب‌تر از قیمت‌ها باشد.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="خرید حقیقی" value={bt(f.real_buy_value)} />
            <Stat label="فروش حقیقی" value={bt(f.real_sell_value)} />
            <Stat
              label="خالص ورود پول حقیقی (منفی = خروج)"
              value={bt(f.real_net)}
              tone={f.real_net >= 0 ? "text-good" : "text-bad"}
            />
            <Stat label="خرید حقوقی" value={bt(f.legal_buy_value)} />
            <Stat label="فروش حقوقی" value={bt(f.legal_sell_value)} />
            <Stat
              label="سرانهٔ خرید حقیقی"
              value={f.per_capita_buy == null ? "—" : bt(f.per_capita_buy)}
            />
            <Stat
              label="سرانهٔ فروش حقیقی"
              value={f.per_capita_sell == null ? "—" : bt(f.per_capita_sell)}
            />
            <Stat
              label="قدرت خریدار (سرانه خرید ÷ فروش)"
              value={f.power == null ? "—" : faNumber(f.power, 2)}
            />
          </div>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Movers title="بیشترین رشد" rows={d.gainers} testid="market-gainers" />
        <Movers title="بیشترین افت" rows={d.losers} testid="market-losers" />
        <Movers title="بیشترین ارزش معاملات" rows={d.by_value} testid="market-value" />
        <Movers title="بیشترین ورود پول حقیقی" rows={d.inflow} testid="market-inflow" flow />
        <Movers title="بیشترین خروج پول حقیقی" rows={d.outflow} testid="market-outflow" flow />
      </div>

      <section className="space-y-2" data-testid="market-sectors">
        <h2 className="text-lg font-bold">گروه‌های پرمعامله</h2>
        <p className="text-xs text-muted">
          «تغییر میانگین» میانگین ساده تغییر سهم‌های گروه است، نه وزن‌دار با ارزش بازار. اگر نام
          گروهی هنوز در جدول نام‌ها نیامده باشد، فقط کد گروه بورس نشان داده می‌شود.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-sm">
            <thead className="text-xs text-muted">
              <tr className="text-right">
                <th className="py-1">گروه</th>
                <th>سهام</th>
                <th>ارزش معاملات</th>
                <th>تغییر میانگین</th>
                <th>خالص پول حقیقی</th>
              </tr>
            </thead>
            <tbody>
              {d.sectors.map((s) => (
                <tr key={s.sector_code} className="border-t border-line">
                  <td className="py-1">{s.name ?? `کد ${faNumber(Number(s.sector_code))}`}</td>
                  <td>{faNumber(s.n)}</td>
                  <td>{bt(s.value)}</td>
                  <td>{s.avg_change == null ? "—" : faPercent(s.avg_change, 2, true)}</td>
                  <td>{s.net_real_flow == null ? "—" : bt(s.net_real_flow)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Movers({
  title,
  rows,
  testid,
  flow,
}: {
  title: string;
  rows: MarketMover[];
  testid: string;
  flow?: boolean;
}) {
  return (
    <section className="space-y-1" data-testid={testid}>
      <h2 className="font-bold">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">موردی نیست.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs text-muted">
            <tr className="text-right">
              <th className="py-1">نماد</th>
              <th>تغییر</th>
              <th>{flow ? "خالص پول حقیقی" : "ارزش"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} className="border-t border-line">
                <td className="py-1 font-semibold">{r.symbol}</td>
                <td>{r.change == null ? "—" : faPercent(r.change, 2, true)}</td>
                <td>
                  {flow
                    ? r.net_real_flow == null
                      ? "—"
                      : bt(r.net_real_flow)
                    : r.value == null
                      ? "—"
                      : bt(r.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
