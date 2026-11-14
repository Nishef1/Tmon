import Link from "next/link";
import type { Adapt, AdaptCandidate, AdaptHorizon, AdaptReplayHorizon, Deep } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { Num } from "@/components/Num";
import { DeepStudy } from "@/components/model/DeepStudy";
import { methodLabel } from "@/components/model/methods";

export { methodLabel };

/** Persian names of the four production signals, in the order of the weight columns. */
const SIGNALS: [string, string][] = [
  ["ind_buy_power", "قدرت خریدار"],
  ["rv_20", "نوسان کم"],
  ["dist_high_52w", "نزدیکی به سقف"],
  ["mom_12_1", "مومنتوم"],
];
const STROKES = ["stroke-accent", "stroke-up", "stroke-down", "stroke-muted"];
const DASHES = [undefined, "6 3", "2 3", "10 3 2 3"];

const horizonLabel = (h: number) => `${faNumber(h)} روز`;

function Weights({ w }: { w: Record<string, number> }) {
  return (
    <>
      {SIGNALS.map(([k]) => (
        <td key={k} className="whitespace-nowrap">
          {faPercent(w[k] ?? 0, 0)}
        </td>
      ))}
    </>
  );
}

function DriftChart({ n, series }: { n: number; series: Record<string, number[]> }) {
  const W = 320;
  const H = 110;
  const P = { l: 6, r: 6, t: 6, b: 6 };
  const all = Object.values(series).flat();
  const lo = Math.min(0, ...all);
  const hi = Math.max(0.01, ...all);
  const X = (i: number) => P.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - P.l - P.r));
  const Y = (v: number) => H - P.b - ((v - lo) / (hi - lo)) * (H - P.t - P.b);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full"
      style={{ direction: "ltr" }}
      role="img"
      aria-label="رانش وزن مرجع چهار سیگنال در طول زمان"
    >
      <line
        x1={P.l}
        x2={W - P.r}
        y1={Y(0)}
        y2={Y(0)}
        className="stroke-faint"
        strokeDasharray="3 3"
      />
      {SIGNALS.map(([k], i) => (
        <polyline
          key={k}
          fill="none"
          className={STROKES[i]}
          strokeWidth={2}
          strokeDasharray={DASHES[i]}
          points={(series[k] ?? [])
            .map((v, j) => `${X(j).toFixed(1)},${Y(v).toFixed(1)}`)
            .join(" ")}
        />
      ))}
    </svg>
  );
}

function CandidateRows({ rows, round }: { rows: [string, AdaptCandidate][]; round: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl min-w-[44rem]">
        <thead>
          <tr>
            <th>روش</th>
            <th>بهبود IC نسبت به مساوی</th>
            <th>نیمهٔ اول ← دوم</th>
            <th>مازاد دهک بالا نسبت به مساوی</th>
            <th>نتیجه</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, c]) => (
            <tr key={k} data-passed={c.passed}>
              <td>{methodLabel(k)}</td>
              <td>
                <Num value={c.d_ic} digits={4} signed term="ic" />{" "}
                <span className="text-xs text-muted">
                  (t=
                  <Num value={c.t} digits={1} term="t_stat" />)
                </span>
              </td>
              <td>
                <Num value={c.early} digits={3} signed term="ic" /> ←{" "}
                <Num value={c.late} digits={3} signed term="ic" />
              </td>
              <td>
                <Num value={c.d_top_excess} kind="percent" digits={2} signed term="adapt_gate" />{" "}
                <span className="text-xs text-muted">
                  (هزینهٔ رفت‌وبرگشت {faPercent(round, 2)})
                </span>
              </td>
              <td className="text-sm">
                {c.passed ? (
                  <b className="text-up">از دروازه گذشت</b>
                ) : (
                  <span className="text-muted">{c.reasons.join("؛ ") || "—"}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReplayRow({ r }: { r: AdaptReplayHorizon }) {
  const changed = r.timeline.filter((p, i) => i > 0 && p.champion !== r.timeline[i - 1].champion);
  return (
    <tr>
      <td>{horizonLabel(r.horizon_days)}</td>
      <td>{faNumber(r.n_cycles)}</td>
      <td>{faPercent(r.share_equal, 0)}</td>
      <td>
        <Num value={r.meta_ic.mean} digits={4} term="ic" /> /{" "}
        <Num value={r.equal_ic.mean} digits={4} term="ic" />
      </td>
      <td>
        <Num value={r.d_ic_early.mean} digits={4} signed term="ic" /> ←{" "}
        <Num value={r.d_ic_late.mean} digits={4} signed term="ic" />
      </td>
      <td>{changed.length === 0 ? "هرگز" : `${faNumber(changed.length)} بار`}</td>
    </tr>
  );
}

function HorizonCard({ h, d }: { h: AdaptHorizon; d: Adapt }) {
  const rows = Object.entries(h.candidates).sort((a, b) => (b[1].t ?? -99) - (a[1].t ?? -99));
  return (
    <details className="card" data-testid={`adapt-candidates-${h.horizon_days}`}>
      <summary className="cursor-pointer font-bold">
        نامزدها در افق {horizonLabel(h.horizon_days)} ({faNumber(rows.length)} روش)
      </summary>
      <div className="mt-3">
        <CandidateRows rows={rows} round={d.round_trip_cost ?? 0} />
      </div>
    </details>
  );
}

/** The living ranking: champion per horizon behind the promotion gate, weights against equal
 *  weights, how the reference weights drift, the cycle history and the replay on the past. */
export function AdaptSection({ d, deep }: { d: Adapt; deep?: Deep | null }) {
  const replay = d.replay;
  const allEqual = d.horizons.every((h) => h.champion === "equal");
  const h5 = d.horizons.find((h) => h.horizon_days === 5);
  const drift5 = d.drift["5"];
  return (
    <section id="adapt" className="scroll-mt-20 space-y-6" data-testid="adapt-section">
      <div className="space-y-2">
        <h2 className="text-xl font-extrabold">
          الگوریتم زنده: روش و وزن‌ها با بازار هماهنگ می‌شوند
        </h2>
        <p className="text-sm leading-7">
          هر چرخه (اکنون تا {jalali(d.as_of)}) چند روش وزن‌دهی را روی{" "}
          {faNumber(d.config?.window_dates ?? 0)} روز اخیر با وزن مساوی مقایسه می‌کند؛ هر روش در هر
          روز آزمون فقط از داده‌ای استفاده کرده که همان روز معلوم بود. روشی جای وزن مساوی را می‌گیرد
          که از <Link href="/glossary/adapt_gate">دروازهٔ ارتقا</Link> بگذرد: بهبود پایدار در هر دو
          نیمهٔ پنجره، t حداقل {faNumber(d.config?.min_t ?? 2)} و مازاد بیشتر از هزینهٔ یک
          رفت‌وبرگشت. وگرنه همان وزن مساوی می‌ماند. اینجا نتیجهٔ گذشته است، نه پیش‌بینی و نه توصیه؛
          ما مشاور سرمایه‌گذاری دارای مجوز نیستیم.
        </p>
        <p className="alert-warn text-sm leading-7 text-ink" data-testid="adapt-caveat">
          داده فقط یک رژیم صعودی را دارد و هر دو نیمهٔ آزمون در همان رژیم‌اند؛ برتری‌ای که اینجا
          دیده شود تا بازار عوض نشود ثابت نشده است.
          {allEqual && (
            <>
              {" "}
              <b>فعلاً در هیچ افقی هیچ روشی از دروازه نگذشته است؛ وزن مساوی همه‌جا قهرمان است.</b>
            </>
          )}
        </p>
      </div>

      <div className="overflow-x-auto" data-testid="adapt-champions">
        <table className="tbl min-w-[44rem]">
          <thead>
            <tr>
              <th>
                افق / <Link href="/glossary/champion">قهرمان</Link>
              </th>
              <th>روش</th>
              {SIGNALS.map(([k, l]) => (
                <th key={k}>وزن {l}</th>
              ))}
              <th>دلیل</th>
            </tr>
          </thead>
          <tbody>
            {d.horizons.map((h) => (
              <tr key={h.horizon_days}>
                <td>{horizonLabel(h.horizon_days)}</td>
                <td className="font-bold">
                  {methodLabel(h.champion)}
                  {h.champion !== "equal" && !h.production_expressible && (
                    <span className="mr-1 text-xs font-normal text-muted">(فقط سایه)</span>
                  )}
                </td>
                <Weights w={h.weights} />
                <td className="text-sm text-muted">{h.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {drift5 && h5 && (
        <section className="space-y-2" data-testid="adapt-drift">
          <h3 className="text-lg font-bold">
            <Link href="/glossary/weight_drift">رانش وزن‌ها</Link> در طول زمان (افق ۵ روز)
          </h3>
          <p className="text-sm leading-7 text-muted">
            وزنی که ریج روی چهار سیگنال با داده‌ی معلوم همان روز می‌دهد (وزن مرجع). تا از دروازه
            نگذرد در امتیاز اصلی به‌کار نمی‌رود؛ فقط نشان می‌دهد بازار به کدام سیگنال بیشتر پاداش
            داده است. وزن مرجع امروز:{" "}
            {SIGNALS.map(([k, l]) => (
              <span key={k} className="ml-2 whitespace-nowrap">
                {l} {faPercent(h5.reference_weights[k] ?? 0, 0)}
              </span>
            ))}
          </p>
          <DriftChart n={drift5.dates.length} series={drift5.series} />
          <ul className="flex flex-wrap gap-4 text-xs text-muted" aria-label="راهنمای نمودار">
            {SIGNALS.map(([k, l], i) => (
              <li key={k} className="flex items-center gap-1">
                <svg width="26" height="8" aria-hidden="true">
                  <line
                    x1="0"
                    x2="26"
                    y1="4"
                    y2="4"
                    className={STROKES[i]}
                    strokeWidth="2"
                    strokeDasharray={DASHES[i]}
                  />
                </svg>
                {l}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2" data-testid="adapt-replay">
        <h3 className="text-lg font-bold">
          <Link href="/glossary/adapt_replay">بازپخش دروازه</Link> روی گذشته: زنده بودن بهتر از ثابت
          ماندن است؟
        </h3>
        {replay ? (
          <>
            <p className="text-sm leading-7 text-muted">
              دروازه هر {faNumber(replay.every)} روز روی گذشته دوباره اجرا شد، فقط با داده‌ای که در
              آن روز معلوم بود. ستون «IC زنده / مساوی» میانگین IC روش انتخاب‌شده در برابر وزن مساوی
              است؛ «تفاوت نیمه‌ها» تفاوت این دو در نیمهٔ اول و دوم. اگر قهرمان همیشه وزن مساوی بوده،
              تفاوت دقیقاً صفر است: یعنی الگوریتم زنده به وزن مساوی آسیب نزده، ولی برتری هم نشان
              نداده.
            </p>
            <div className="overflow-x-auto">
              <table className="tbl min-w-[40rem]">
                <thead>
                  <tr>
                    <th>افق</th>
                    <th>تعداد چرخه</th>
                    <th>سهم وزن مساوی</th>
                    <th>IC زنده / مساوی</th>
                    <th>تفاوت نیمهٔ اول ← دوم</th>
                    <th>تغییر قهرمان</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(replay.horizons)
                    .sort((a, b) => a.horizon_days - b.horizon_days)
                    .map((r) => (
                      <ReplayRow key={r.horizon_days} r={r} />
                    ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted">بازپخش هنوز اجرا نشده است.</p>
        )}
      </section>

      <section className="space-y-3" data-testid="adapt-candidates">
        <h3 className="text-lg font-bold">همهٔ نامزدها و دلیل رد یا پذیرش</h3>
        {d.horizons.map((h) => (
          <HorizonCard key={h.horizon_days} h={h} d={d} />
        ))}
      </section>

      <section className="space-y-2" data-testid="adapt-history">
        <h3 className="text-lg font-bold">سابقهٔ چرخه‌ها</h3>
        <div className="overflow-x-auto">
          <table className="tbl min-w-[36rem]">
            <thead>
              <tr>
                <th>تاریخ</th>
                {d.horizons.map((h) => (
                  <th key={h.horizon_days}>{horizonLabel(h.horizon_days)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...d.history]
                .reverse()
                .slice(0, 12)
                .map((r) => (
                  <tr key={r.as_of}>
                    <td>{jalali(r.as_of)}</td>
                    {d.horizons.map((h) => (
                      <td key={h.horizon_days}>
                        {methodLabel(r.champions[String(h.horizon_days)] ?? "equal")}
                      </td>
                    ))}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      {deep?.available && <DeepStudy d={deep} />}
    </section>
  );
}
