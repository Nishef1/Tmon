import type { GoldOil as Doc, GoldRatio } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

/** Rial -> million toman. */
function mt(rial: number, digits = 1): string {
  return `${faNumber(rial / 1e7, digits)} میلیون تومان`;
}

/** Rial -> toman. */
function toman(rial: number): string {
  return `${faNumber(rial / 10)} تومان`;
}

function points(x: number): string {
  const v = Math.abs(x * 100);
  return `${faNumber(v, 1)} واحد ${x >= 0 ? "بالاتر" : "پایین‌تر"}`;
}

const STATE = {
  high: { label: "گران‌تر از معمول", cls: "gx-high" },
  normal: { label: "در محدودهٔ معمول", cls: "gx-normal" },
  low: { label: "ارزان‌تر از معمول", cls: "gx-low" },
} as const;

/** Where the deviation from the yearly mean sits between the two cuts, on a -2x..+2x scale. */
function Gauge({ r, cuts }: { r: GoldRatio; cuts: [number, number] }) {
  if (r.deviation == null) return null;
  const span = 2 * Math.max(Math.abs(cuts[0]), Math.abs(cuts[1]));
  const pos = (x: number) => 50 + (50 * Math.max(-span, Math.min(span, x))) / span;
  return (
    <div aria-hidden>
      <div className="gx-gauge">
        <span
          className="gx-band"
          style={{ left: `${pos(cuts[0])}%`, right: `${100 - pos(cuts[1])}%` }}
        />
        <span className="gx-zero" />
        <span className="gx-dot" style={{ left: `${pos(r.deviation)}%` }} />
      </div>
      <div className="gx-ends">
        <span>ارزان‌تر از معمول</span>
        <span>میانگین سال</span>
        <span>گران‌تر از معمول</span>
      </div>
    </div>
  );
}

function Bubble({
  title,
  testid,
  r,
  cuts,
  price,
  fair,
  thing,
}: {
  title: string;
  testid: string;
  r: GoldRatio;
  cuts: [number, number];
  price: number;
  fair: number;
  thing: string;
}) {
  const st = r.state ? STATE[r.state] : null;
  return (
    <article className="gx-card" data-testid={testid}>
      <header className="flex items-start justify-between gap-2">
        <h3 className="font-bold">{title}</h3>
        {st && <span className={`gx-pill ${st.cls}`}>{st.label}</span>}
      </header>
      <p className="gx-big">{faPercent(r.value, 1, true)}</p>
      <p className="text-sm text-muted">
        {thing} {mt(price)}؛ ارزش طلایش به نرخ انس و دلار آزاد {mt(fair)}.
      </p>
      <Gauge r={r} cuts={cuts} />
      <dl className="gx-facts">
        <div>
          <dt>میانگین یک سال گذشته</dt>
          <dd>{r.mean_52w == null ? "—" : faPercent(r.mean_52w, 1, true)}</dd>
        </div>
        <div>
          <dt>فاصله با میانگین</dt>
          <dd>{r.deviation == null ? "—" : points(r.deviation)}</dd>
        </div>
      </dl>
      {r.state === "high" && (
        <p className="gx-note">
          در گذشته، چهار هفته پس از چنین هفته‌هایی، {thing} معمولاً کمتر از انس ضرب در دلار بالا رفت
          و این فاصله کوچک شد.
        </p>
      )}
      {r.state === "low" && (
        <p className="gx-note">
          در گذشته، چهار هفته پس از چنین هفته‌هایی، {thing} معمولاً بیشتر از انس ضرب در دلار بالا
          رفت.
        </p>
      )}
    </article>
  );
}

/** The API labels a Thursday-to-Wednesday week by its Monday; show the Wednesday it ends on. */
function weekEnd(monday: string): string {
  const t = new Date(`${monday}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + 2);
  return t.toISOString().slice(0, 10);
}

export function GoldOil({ d }: { d: Doc }) {
  const oilRank = Math.round(d.oil_gold.pct_rank_3y * 100);
  return (
    <section id="gold-oil" className="gx card scroll-mt-20" data-testid="gold-oil">
      <div className="gx-glow" aria-hidden />
      <div className="space-y-1">
        <h2 className="text-lg font-bold">طلا، دلار و نفت</h2>
        <p className="text-sm text-muted">
          آخرین قیمت‌های هفتهٔ منتهی به {jalali(weekEnd(d.week))}. «حباب» یعنی قیمت داخلی چقدر از
          ارزش طلایش به نرخ انس جهانی ({faNumber(d.gold_usd, 0)} دلار) و دلار آزاد (
          {toman(d.usd_free)}) بیشتر است.
        </p>
      </div>
      <div className="gx-grid">
        <Bubble
          title="حباب طلای ۱۸ عیار"
          testid="gold-prem"
          r={d.gold_prem}
          cuts={d.gold_prem_cuts}
          price={d.gold_18k}
          fair={d.gold_18k_fair}
          thing="یک گرم طلای ۱۸ عیار"
        />
        <Bubble
          title="حباب سکهٔ امامی"
          testid="coin-bubble"
          r={d.coin_bubble}
          cuts={d.coin_bubble_cuts}
          price={d.coin_emami}
          fair={d.coin_fair}
          thing="سکهٔ امامی"
        />
        <article className="gx-card" data-testid="oil-gold">
          <h3 className="font-bold">نفت به طلا</h3>
          <p className="gx-big">{faNumber(d.oil_gold.value, 3)} انس</p>
          <p className="text-sm text-muted">
            یک بشکه برنت ({faNumber(d.brent_usd, 1)} دلار) به اندازهٔ این مقدار طلا می‌ارزد.
          </p>
          <div className="meter" aria-hidden>
            <span style={{ width: `${oilRank}%` }} />
          </div>
          <p className="text-sm">
            بالاتر از {faNumber(oilRank)}٪ هفته‌های سه سال اخیر. در ۱۳۹۲ حدود ۰٫۰۸۵ انس بود.
          </p>
          <p className="gx-note">این نسبت در آزمون‌ها هیچ پیش‌بینی‌ای برای بورس نداشت.</p>
        </article>
      </div>
      <p className="text-sm">
        دلاری که طلای ۱۸ عیار و انس با هم نشان می‌دهند: <b>{toman(d.usd_implied)}</b>. در گذشته دلار
        آزاد به دنبال آن نرفت؛ این طلای داخلی بود که برگشت.
      </p>
      <p className="imap-foot">
        توصیف است، نه توصیه. در سه سال اخیر هفته‌ای که طلا، سکه و دلار بالا رفتند معمولاً هفتهٔ بد
        بورس بود، ولی هیچ‌کدام بورس هفتهٔ بعد را پیش‌بینی نکردند. نفت و انس با هیچ صنعتی پیوند پایدار
        نداشتند. مرزهای «گران‌تر» و «ارزان‌تر» از نیمهٔ اول ۱۳۹۲ تا ۱۳۹۹ آمده‌اند و هنوز برای خرید یا
        فروش با کارمزد آزموده نشده‌اند (مورد ۱۲۷).
      </p>
    </section>
  );
}
