"use client";

import Link from "next/link";
import { useState } from "react";
import type { IndustryMap as Doc, IndustryMapRow as Row } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";

type Group = Row["group"];

const GROUPS: { key: Group; label: string; note: string }[] = [
  {
    key: "export",
    label: "صادرات‌محور",
    note: "با کالاهای جهانی و نرخ ارز هم‌جهت‌اند",
  },
  { key: "middle", label: "میانه", note: "به هیچ سو کشش روشنی ندارند" },
  { key: "domestic", label: "داخلی", note: "به فروش و تقاضای داخل کشور وابسته‌اند" },
];

const TIE: Record<Row["dollar_tie"], { label: string; tone: string; text: string }> = {
  up_steady: {
    label: "هم‌جهت با دلار",
    tone: "tie-up",
    text: "در هر دو نیمهٔ سه سال، هفته‌هایی که دلار آزاد گران شد این صنعت بیشتر از بازار بالا رفت.",
  },
  up_unsteady: {
    label: "گاهی با دلار",
    tone: "tie-up-weak",
    text: "در یک نیمه با دلار هم‌جهت بود و در نیمهٔ دیگر نه؛ پیوندش پایدار نیست.",
  },
  none: {
    label: "بی‌پیوند با دلار",
    tone: "tie-none",
    text: "حرکت اضافه بر بازارش پیوند روشنی با دلار آزاد نداشت.",
  },
  down_unsteady: {
    label: "گاهی خلاف دلار",
    tone: "tie-down-weak",
    text: "در یک نیمه با گران شدن دلار عقب ماند و در نیمهٔ دیگر نه؛ پایدار نیست.",
  },
  down_steady: {
    label: "خلاف دلار",
    tone: "tie-down",
    text: "در هر دو نیمهٔ سه سال، هفته‌هایی که دلار گران شد این صنعت از بازار عقب ماند.",
  },
};

const SHORT: Record<string, string> = {
  "فراورده های نفتی، کک و سوخت هسته ای": "فراورده‌های نفتی",
  "شرکتهای چند رشته ای صنعتی": "چندرشته‌ای صنعتی",
  "استخراج کانه های فلزی": "کانه‌های فلزی",
  "حمل ونقل، انبارداری و ارتباطات": "حمل و نقل",
  "بانکها و موسسات اعتباری": "بانک‌ها",
  "بیمه وصندوق بازنشستگی به جزتامین اجتماعی": "بیمه",
  "خودرو و ساخت قطعات": "خودرو و قطعات",
  "عرضه برق، گاز، بخاروآب گرم": "برق و گاز",
  "سیمان، آهک و گچ": "سیمان",
  "فعالیتهای کمکی به نهادهای مالی واسط": "کمکی مالی",
  "انبوه سازی، املاک و مستغلات": "انبوه‌سازی و املاک",
  "زراعت و خدمات وابسته": "زراعت",
  "رایانه و فعالیت‌های وابسته به آن": "رایانه",
  "مواد و محصولات دارویی": "دارویی",
  "ساخت محصولات فلزی": "محصولات فلزی",
  "سایر محصولات کانی غیرفلزی": "کانی غیرفلزی",
  "محصولات غذایی و آشامیدنی به جز قند و شکر": "غذایی",
  "بیمه و صندوق بازنشستگی به جز تامین اجتماعی": "بیمه",
  "لاستیک و پلاستیک": "لاستیک و پلاستیک",
  "ماشین آلات و تجهیزات": "ماشین‌آلات",
  "محصولات شیمیایی": "شیمیایی",
  سرمایه‌گذاریها: "سرمایه‌گذاری‌ها",
  "سرمایه گذاریها": "سرمایه‌گذاری‌ها",
};
const short = (s: string) => SHORT[s] ?? s;

function pct(x: number | null | undefined) {
  return x === null || x === undefined ? "—" : faPercent(x, 0, true);
}
function dir(x: number | null | undefined) {
  return x === null || x === undefined || x === 0 ? "" : x > 0 ? "text-up" : "text-down";
}

/** −1..+1 bar from the centre: export side toward the start (right), domestic toward the end. */
function AxisBar({ v, group }: { v: number | null; group: Group }) {
  const w = Math.min(Math.abs(v ?? 0), 1) * 50;
  const side = (v ?? 0) >= 0 ? { insetInlineEnd: "50%" } : { insetInlineStart: "50%" };
  return (
    <span className="axis-wrap" aria-hidden>
      <span className="axis-ends">
        <span>صادرات‌محور</span>
        <span>داخلی</span>
      </span>
      <span className="axis-track">
        <span className="axis-mid" />
        <span className={`axis-bar grp-${group}`} style={{ ...side, width: `${w}%` }} />
      </span>
    </span>
  );
}

function Meter({ v, max }: { v: number | null; max: number }) {
  const w = Math.max(0, Math.min((v ?? 0) / max, 1)) * 100;
  return (
    <span className="meter" aria-hidden>
      <span style={{ width: `${w}%` }} />
    </span>
  );
}

function SectorRow({ r, open, onToggle }: { r: Row; open: boolean; onToggle: () => void }) {
  const tie = TIE[r.dollar_tie];
  return (
    <li className="imap-row" data-open={open}>
      <button
        type="button"
        className="imap-head"
        aria-expanded={open}
        onClick={onToggle}
        data-testid="imap-row"
      >
        <span className="imap-name">
          <span className="font-bold">{short(r.sector)}</span>
          <span className="text-xs text-faint">{faNumber(r.n_stocks)} سهم</span>
        </span>
        <AxisBar v={r.axis} group={r.group} />
        <span className={`tie ${tie.tone}`}>{tie.label}</span>
        <span className="imap-stat">
          <span className="imap-k">شدت با بازار</span>
          <span className="tabular-nums">{r.beta === null ? "—" : faNumber(r.beta, 2)}</span>
        </span>
        <span className="imap-stat">
          <span className="imap-k">هم‌حرکتی</span>
          <Meter v={r.cohesion} max={0.4} />
        </span>
        <span className="imap-stat">
          <span className="imap-k">۳ ماه</span>
          <span className={`font-bold tabular-nums ${dir(r.ret_13w)}`}>{pct(r.ret_13w)}</span>
        </span>
      </button>
      {open && (
        <div className="imap-more">
          <p>{tie.text}</p>
          <dl className="imap-facts">
            <div>
              <dt>پیوند با دلار (از −۱ تا +۱)</dt>
              <dd className="tabular-nums">
                نیمهٔ اول {r.usd_corr_h1 === null ? "—" : faNumber(r.usd_corr_h1, 2)}، نیمهٔ دوم{" "}
                {r.usd_corr_h2 === null ? "—" : faNumber(r.usd_corr_h2, 2)}
              </dd>
            </div>
            <div>
              <dt>بازده</dt>
              <dd className="tabular-nums">
                یک ماه <span className={dir(r.ret_4w)}>{pct(r.ret_4w)}</span>، یک سال{" "}
                <span className={dir(r.ret_52w)}>{pct(r.ret_52w)}</span>
              </dd>
            </div>
            <div>
              <dt>نزدیک‌ترین صنعت‌ها</dt>
              <dd>{r.closest.map((c) => short(c.sector)).join("، ") || "—"}</dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-1.5">
            {r.symbols.map((s) => (
              <Link
                key={s}
                href={`/industries?q=${encodeURIComponent(s)}`}
                className="chip"
                prefetch={false}
              >
                {s}
              </Link>
            ))}
          </div>
        </div>
      )}
    </li>
  );
}

function Heatmap({ doc }: { doc: Doc }) {
  const [hover, setHover] = useState<[number, number] | null>(null);
  const { order, values } = doc.corr;
  const read =
    hover && hover[0] !== hover[1]
      ? `${short(order[hover[0]])} و ${short(order[hover[1]])}: ${faNumber(values[hover[0]][hover[1]] ?? 0, 2)}`
      : "روی یک خانه بروید یا بزنید. عدد هم‌حرکتی دو صنعت جدا از بازار است.";
  return (
    <div>
      <p className="heat-read" aria-live="polite">
        {read}
      </p>
      <div className="heat-scroll">
        <div
          aria-hidden
          className="heat"
          style={{
            gridTemplateColumns: `max-content repeat(${order.length}, minmax(1.2rem, 1fr))`,
          }}
          onPointerLeave={() => {
            setHover(null);
          }}
        >
          <span />
          {order.map((s, j) => (
            <span key={s} className="heat-col" data-on={hover?.[1] === j}>
              {faNumber(j + 1)}
            </span>
          ))}
          {order.map((a, i) => (
            <div key={a} className="contents">
              <span className="heat-row" data-on={hover?.[0] === i}>
                <span className="text-faint">{faNumber(i + 1)}</span> {short(a)}
              </span>
              {values[i].map((v, j) => {
                const x = i === j ? null : v;
                const a2 = x === null ? 0 : Math.min(Math.abs(x) / 0.5, 1) * 85;
                const col = x !== null && x < 0 ? "var(--down)" : "var(--accent)";
                return (
                  <span
                    key={order[j]}
                    className="heat-cell"
                    data-on={hover?.[0] === i && hover[1] === j}
                    style={{
                      background:
                        i === j
                          ? "var(--line-soft)"
                          : `color-mix(in srgb, ${col} ${a2.toFixed(0)}%, var(--surface))`,
                    }}
                    onPointerEnter={() => {
                      setHover([i, j]);
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
        <span className="heat-key" style={{ background: "var(--accent)" }} /> با هم بیشتر از بازار
        <span className="heat-key" style={{ background: "var(--down)" }} /> وارون هم
        <span>ترتیب از صادرات‌محور به داخلی است؛ بلوک‌های پررنگ گوشه‌ها همان دو گروه‌اند.</span>
      </p>
    </div>
  );
}

export function IndustryMap({ doc }: { doc: Doc }) {
  const [only, setOnly] = useState<Group | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const rows = doc.sectors.filter((r) => !only || r.group === only);
  return (
    <section className="card card-pad-lg imap" aria-labelledby="imap-title" data-testid="imap">
      <div className="imap-glow" aria-hidden />
      <p className="eyebrow">گروه‌بندی صنایع از روی حرکت سه سال اخیر</p>
      <h2 id="imap-title" className="mt-1 text-2xl font-black tracking-tight">
        صادرات‌محور یا داخلی؟
      </h2>
      <p className="lead">
        هر صنعت را از روی اینکه حرکتش جدا از کل بازار با کدام صنعت‌ها همراه است روی یک محور گذاشتیم:
        سر راست صنعت‌های کالایی و صادراتی، سر چپ صنعت‌های وابسته به بازار داخل. طول نوار شدت آن است.
        پیوند با دلار جدا آزموده شده و فقط وقتی «هم‌جهت» یا «خلاف» آمده که در هر دو نیمهٔ دوره دیده
        شده باشد.
      </p>

      <div className="mt-4 grid gap-2 sm:grid-cols-3" role="group" aria-label="فیلتر گروه">
        {GROUPS.map((g) => {
          const list = doc.sectors.filter((r) => r.group === g.key);
          return (
            <button
              type="button"
              key={g.key}
              className={`grp-card grp-${g.key}`}
              aria-pressed={only === g.key}
              onClick={() => {
                setOnly(only === g.key ? null : g.key);
              }}
              data-testid={`grp-${g.key}`}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="text-lg font-black">{g.label}</span>
                <span className="text-sm font-bold tabular-nums">{faNumber(list.length)} صنعت</span>
              </span>
              <span className="text-xs text-muted">{g.note}</span>
              <span className="mt-1 line-clamp-2 text-sm">
                {list.map((r) => short(r.sector)).join("، ")}
              </span>
            </button>
          );
        })}
      </div>

      <ul className="imap-list">
        {rows.map((r) => (
          <SectorRow
            key={r.sector}
            r={r}
            open={open === r.sector}
            onToggle={() => {
              setOpen(open === r.sector ? null : r.sector);
            }}
          />
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">
        «شدت با بازار» ۱٫۲ یعنی وقتی کل بازار ۱۰ درصد بالا یا پایین می‌رود، این صنعت به‌طور میانگین
        ۱۲ درصد می‌رود. «هم‌حرکتی»: سهم‌های یک صنعت جدا از بازار چقدر با هم حرکت می‌کنند. بازده سه
        ماههٔ همهٔ بازار (هم‌وزن) {pct(doc.market.ret_13w)} بود. روی هر صنعت بزنید تا نمادها و جزئیاتش
        باز شود.
      </p>

      <details className="imap-details">
        <summary>کدام صنعت‌ها با هم حرکت می‌کنند؟</summary>
        <Heatmap doc={doc} />
      </details>

      <p className="imap-foot">
        {faNumber(doc.n_stocks)} سهم پرمعامله، {faNumber(doc.n_weeks)} هفته از {jalali(doc.start)}{" "}
        تا {jalali(doc.as_of)}. این گروه‌بندی توصیف گذشته است، نه نشانهٔ خرید یا فروش: در آزمون هیچ
        پیش‌افتادنی از دلار یا از صنعت دیگر در هر دو نیمه و پس از کارمزد پایدار نماند. مرز سه گروه
        (یک‌سوم محور) فقط برای نمایش است و آزموده نشده. بیشتر این سه سال بازار صعودی بوده است.
      </p>
    </section>
  );
}
