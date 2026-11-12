import Link from "next/link";
import type { Metadata } from "next";
import { apiGet, type Ranking, type RankingRow } from "@/lib/api";
import { faDigits, faNumber, jalali } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { ErrorState } from "@/components/ErrorState";
import { Num } from "@/components/Num";

export const metadata: Metadata = { title: "خرید، نگهداری، پرهیز" };
export const dynamic = "force-dynamic";

const ZONES = [
  ["buy", "ناحیهٔ خرید مدل", "بالاترین ۱۰٪ امتیاز"],
  ["hold", "ناحیهٔ نگهداری", "امتیاز بین ۷۰٪ و ۹۰٪ بالا"],
  ["avoid", "ناحیهٔ پرهیز", "امتیاز در ۷۰٪ پایین"],
] as const;

const QUEUE: Record<string, string> = {
  buy_queue: "صف خرید: عملاً نمی‌شود خرید",
  sell_queue: "صف فروش",
};

const SIGNALS: Record<string, string> = {
  ind_buy_power: "قدرت خریدار",
  rv_20: "نوسان کم",
  dist_high_52w: "نزدیکی به سقف",
  mom_12_1: "مومنتوم",
};

const GATE_NAMES: Record<string, string> = {
  G1: "بازده بهتر از شاخص",
  G2: "افت کمتر از شاخص",
  G3: "گردش ماهانه",
  G4: "معناداری آماری",
  G5: "پایداری",
  G6: "بازمانده‌سوگیری",
};

export default async function RankingPage() {
  const res = await apiGet<Ranking>("/v2/ranking");
  return (
    <main className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">کدام نمادها را بخرم، کدام را نه؟</h1>
        <p className="mt-1 text-sm text-muted">
          رتبه‌بندی ۱۰۰ نمادِ پرنقدشوندهٔ امروز با چهار سیگنال قیمتی، بدون هیچ تنظیمی. هر عدد با
          سابقهٔ آزمونش آمده است.
        </p>
      </div>
      <Disclaimer />
      {!res.ok ? (
        <ErrorState message={res.error} />
      ) : !res.data.available ? (
        <p className="text-sm text-muted" data-testid="ranking-unavailable">
          رتبه‌بندی هنوز ساخته نشده است. با «python -m tmon.tools.v2_ranking» ساخته می‌شود.
        </p>
      ) : (
        <Body d={res.data} />
      )}
    </main>
  );
}

function Body({ d }: { d: Ranking }) {
  const by = (z: string) => d.rows.filter((r) => r.zone === z);
  const other = d.rows.filter((r) => r.zone === "no_data" || r.zone === "excluded");
  return (
    <>
      <section
        className="space-y-2 rounded-2xl border border-warn/30 bg-warn-soft p-5 text-sm"
        data-testid="ranking-status"
      >
        <h2 className="text-lg font-bold">
          {d.recommendation_allowed
            ? "همهٔ دروازه‌های آزمون گذشته‌اند"
            : "این فهرست رتبه‌بندی مدل است، توصیهٔ خرید نیست"}
        </h2>
        <p>
          تاریخ داده: {jalali(d.as_of)}. طبق ADR 0003 تا وقتی همهٔ دروازه‌ها (G1 تا G6) نگذرند،
          خروجی v2 نباید توصیه نامیده شود. وضعیت آزمون روی داده‌های واقعی:
        </p>
        <ul className="list-inside list-disc space-y-1">
          {d.gates.map((c) => (
            <li key={c.candidate}>
              <strong>{c.candidate === "v2" ? "v2 کامل" : "انتخاب سهام تنها"}</strong> (
              {jalali(c.first)} تا {jalali(c.last)}، {faNumber(c.days)} روز): بازده سالانه{" "}
              <Num value={c.annual} kind="percent" term="realized_return" digits={1} /> در برابر
              شاخص سبد{" "}
              <Num value={c.annual_bench} kind="percent" term="realized_return" digits={1} /> ·
              حداکثر افت{" "}
              <Num value={c.max_drawdown} kind="percent" term="max_drawdown" digits={1} /> در برابر{" "}
              <Num value={c.max_drawdown_bench} kind="percent" term="max_drawdown" digits={1} />.{" "}
              <span className="font-semibold">{faDigits(c.verdict)}</span>
              <ul className="mr-5 list-inside list-disc text-xs text-muted">
                {c.gates
                  .filter((g) => g.passed !== true)
                  .map((g) => (
                    <li key={g.key}>
                      {g.key} ({GATE_NAMES[g.key] ?? ""}): {faDigits(g.text)}
                    </li>
                  ))}
              </ul>
            </li>
          ))}
        </ul>
        <p className="text-muted">
          معنی‌اش: هیچ‌یک از این نمادها «پیشنهاد خرید» نیست. اگر مالک تصمیم بگیرد با همین شرایط آن
          را توصیه حساب کند، آن تصمیم جداگانه و صریح است.
        </p>
      </section>

      {d.exposure && (
        <section className="rounded-2xl border border-line bg-surface p-4 text-sm">
          <h2 className="font-bold">چند درصد سرمایه در سهام باشد؟</h2>
          <p className="mt-1">
            سطح مواجههٔ مدل در {jalali(d.exposure_date)}:{" "}
            <Num value={d.exposure.exposure} kind="percent" term="exposure_level" digits={1} />؛
            روند <Num value={d.exposure.trend} term="exposure_level" digits={2} />، مومنتوم{" "}
            <Num value={d.exposure.abs_mom} term="exposure_level" digits={2} />، سقف نوسان{" "}
            <Num value={d.exposure.vol_cap} term="exposure_level" digits={2} />، فشار صف فروش{" "}
            <Num value={d.exposure.stress} term="exposure_level" digits={3} />. باقی در اوراق با
            درآمد ثابت فرض می‌شود.
          </p>
        </section>
      )}

      {ZONES.map(([z, title, rule]) => (
        <Zone key={z} zone={z} title={title} rule={rule} rows={by(z)} />
      ))}
      {other.length > 0 && (
        <section className="space-y-2 text-sm" data-testid="zone-other">
          <h2 className="text-lg font-bold">بدون امتیاز ({faNumber(other.length)} نماد)</h2>
          <p className="text-muted">
            این نمادها در سبد پرنقدشوندگی‌اند ولی امروز یکی از سیگنال‌هایشان محاسبه‌پذیر نیست
            (سابقهٔ کم) یا در صف فروش‌اند؛ پس نه خرید و نه پرهیز برایشان گفته نمی‌شود:{" "}
            {other.map((r) => r.symbol).join("، ")}.
          </p>
        </section>
      )}

      <section className="space-y-2" data-testid="ranking-evidence">
        <h2 className="text-lg font-bold">این رتبه‌بندی در گذشته چقدر کار کرده؟</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-xs text-muted">
              <tr className="text-right">
                <th className="py-1">افق</th>
                <th>
                  <Link href="/glossary/ic">IC</Link>
                </th>
                <th>
                  <Link href="/glossary/t_stat">t</Link> (IC)
                </th>
                <th>۱۰٪ بالا نسبت به بازار</th>
                <th>۱۰٪ پایین نسبت به بازار</th>
                <th>روز</th>
              </tr>
            </thead>
            <tbody>
              {d.evidence.map((e) => (
                <tr key={e.horizon_days} className="border-t border-line">
                  <td className="py-1">{faNumber(e.horizon_days)} روز کاری</td>
                  <td>
                    <Num value={e.ic} term="ic" digits={3} signed />
                  </td>
                  <td>
                    <Num value={e.ic_t} term="t_stat" digits={1} />
                  </td>
                  <td>
                    <Num value={e.top_excess} kind="percent" term="ic" digits={2} signed />
                  </td>
                  <td>
                    <Num value={e.bottom_excess} kind="percent" term="ic" digits={2} signed />
                  </td>
                  <td>{faNumber(e.n_days)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">
          افق روزانه (۱ روز) و سالانه (۲۵۲ روز) سنجیده نشده‌اند و برای آن‌ها هیچ ادعایی نمی‌شود.
          اعداد جدول پیش از هزینهٔ معامله‌اند؛ هزینهٔ رفت‌وبرگشت حدود ۱٫۷۵٪ است و نتیجهٔ پس از هزینه
          در بخش دروازه‌ها بالا آمده است.
          {d.book && (
            <>
              {" "}
              سبد آزمون: {faNumber(d.book.n_buys)} خرید، {faNumber(d.book.cancelled_buys)} خرید
              لغوشده به دلیل صف، {faNumber(d.book.postponed_sells)} فروش عقب‌افتاده، میانگین{" "}
              {faNumber(d.book.avg_held, 1)} نماد در سبد.
            </>
          )}{" "}
          بخش بزرگی از برتری سبد ما بر شاخص سبد، کمتر معامله‌کردن است نه پیش‌بینی بهتر.
        </p>
      </section>
    </>
  );
}

function Zone({
  zone,
  title,
  rule,
  rows,
}: {
  zone: string;
  title: string;
  rule: string;
  rows: RankingRow[];
}) {
  return (
    <section className="space-y-2" data-testid={`zone-${zone}`}>
      <h2 className="text-lg font-bold">
        {title} ({faNumber(rows.length)} نماد)
      </h2>
      <p className="text-xs text-muted">{rule}. امتیاز رتبه‌بندی بین ۰ و ۱ است.</p>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">امروز نمادی در این ناحیه نیست.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[38rem] text-sm">
            <thead className="text-xs text-muted">
              <tr className="text-right">
                <th className="py-1">#</th>
                <th>نماد</th>
                <th>امتیاز</th>
                {Object.values(SIGNALS).map((l) => (
                  <th key={l}>{l}</th>
                ))}
                <th>وضعیت صف</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} className="border-t border-line">
                  <td className="py-1">{faNumber(r.rank)}</td>
                  <td>
                    <span className="font-semibold">{r.symbol}</span>
                    <span className="mr-1 text-xs text-muted">{r.name}</span>
                    {r.name?.startsWith("صندوق") && (
                      <span className="mr-1 rounded border border-line px-1 text-xs">صندوق</span>
                    )}
                  </td>
                  <td>
                    <Num value={r.score} term="rank_score" digits={2} />
                  </td>
                  {Object.keys(SIGNALS).map((k) => (
                    <td key={k}>
                      <Num value={r.signals[k]} term="rank_score" digits={2} />
                    </td>
                  ))}
                  <td className="text-xs">{QUEUE[r.queue_state ?? ""] ?? "عادی"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {zone === "buy" && rows.some((r) => r.queue_state === "buy_queue") && (
        <p className="text-xs text-muted">
          نمادهای در صف خرید را معمولاً نمی‌شود به قیمت آخر خرید؛ مدل خرید آن‌ها را در آزمون لغو
          می‌کند.
        </p>
      )}
    </section>
  );
}
