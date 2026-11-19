"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { IndustryCard, IndustryOverview } from "@/lib/api";
import { faNumber, faPercent, faToman, jalali } from "@/lib/format";
import { signTone } from "@/lib/ui";
import { BreadthBar, Spark } from "@/components/market/Spark";

const SORTS = [
  { key: "value", label: "ارزش معاملات", get: (c: IndustryCard) => c.value },
  { key: "day", label: "امروز", get: (c: IndustryCard) => c.day },
  { key: "week", label: "هفته", get: (c: IndustryCard) => c.week },
  { key: "month", label: "ماه", get: (c: IndustryCard) => c.month },
  { key: "flow", label: "پول حقیقی", get: (c: IndustryCard) => c.net_real_flow },
] as const;
type SortKey = (typeof SORTS)[number]["key"];

const SHORT: Record<string, string> = {
  "فراورده های نفتی، کک و سوخت هسته ای": "فراورده‌های نفتی و کک",
  "بیمه وصندوق بازنشستگی به جزتامین اجتماعی": "بیمه و بازنشستگی",
  "بیمه و صندوق بازنشستگی به جز تامین اجتماعی": "بیمه و بازنشستگی",
  "فعالیتهای کمکی به نهادهای مالی واسط": "کمکی به نهادهای مالی",
  "محصولات غذایی و آشامیدنی به جز قند و شکر": "غذایی و آشامیدنی",
};
const short = (s: string) => SHORT[s] ?? s;

function Mini({ k, v }: { k: string; v: number | null | undefined }) {
  return (
    <div className="ic-mini">
      <span>{k}</span>
      <b className={`num ${signTone(v)}`}>{v == null ? "—" : faPercent(v, 1, true)}</b>
    </div>
  );
}

function Card({ c, market }: { c: IndustryCard; market: number | null | undefined }) {
  const gap = c.day != null && market != null ? c.day - market : null;
  return (
    <Link
      href={`/industries/${encodeURIComponent(c.code)}`}
      className="card ic"
      data-testid="industry-card"
      data-code={c.code}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="ic-name">{short(c.name)}</h3>
          <p className="text-xs text-muted">
            {faNumber(c.n_traded)} از {faNumber(c.n)} نماد معامله شد
          </p>
        </div>
        <div className="text-end">
          <p className={`ic-day num ${signTone(c.day)}`}>
            {c.day == null ? "—" : faPercent(c.day, 2, true)}
          </p>
          {gap != null && (
            <p className={`text-xs ${signTone(gap)}`}>
              {Math.abs(gap) < 0.0005
                ? "هم‌پای بازار"
                : gap > 0
                  ? "بهتر از بازار"
                  : "ضعیف‌تر از بازار"}
            </p>
          )}
        </div>
      </div>

      <div className="ic-spark">
        <Spark values={c.spark} width={240} height={44} label="روند ۶۰ روز اخیر صنعت" />
      </div>

      <div className="space-y-1">
        <BreadthBar
          up={c.up}
          flat={c.flat}
          down={c.down}
          label={`${faNumber(c.up)} نماد مثبت، ${faNumber(c.down)} منفی، ${faNumber(c.flat)} بدون تغییر`}
        />
        <div className="flex justify-between text-xs font-semibold">
          <span className="text-up">{faNumber(c.up)} مثبت</span>
          <span className="text-down">{faNumber(c.down)} منفی</span>
        </div>
      </div>

      <div className="ic-minis">
        <Mini k="هفته" v={c.week} />
        <Mini k="ماه" v={c.month} />
        <Mini k="سه ماه" v={c.m3} />
      </div>

      <div className="ic-foot">
        <span>
          ارزش {faToman(c.value)}
          <i className="text-muted"> · {faPercent(c.value_share, 0)} بازار</i>
        </span>
        <span className={signTone(c.net_real_flow)}>
          {c.net_real_flow == null
            ? "—"
            : `${c.net_real_flow >= 0 ? "ورود" : "خروج"} ${faToman(Math.abs(c.net_real_flow))}`}
        </span>
      </div>
    </Link>
  );
}

/** One card per industry: how the symbols of the industry did together. Opens the industry page. */
export function IndustryCards({ doc }: { doc: IndustryOverview }) {
  const [sort, setSort] = useState<SortKey>("value");
  const rows = useMemo(() => {
    const g = SORTS.find((s) => s.key === sort)!.get;
    return [...doc.industries].sort((a, b) => (g(b) ?? -Infinity) - (g(a) ?? -Infinity));
  }, [doc.industries, sort]);
  const up = doc.industries.filter((c) => (c.day ?? 0) > 0).length;
  return (
    <section className="space-y-3" data-testid="industry-cards">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-0.5">
          <h2 className="text-lg font-black">نبض صنایع</h2>
          <p className="text-xs leading-6 text-muted">
            هر صنعت یک رأی از هر نمادش دارد: حرکت امروز، میانگین حرکت نمادهاست. {faNumber(up)} از{" "}
            {faNumber(doc.industries.length)} صنعت امروز مثبت بودند ·{" "}
            {doc.as_of ? jalali(doc.as_of, "weekday") : ""}. روی هر صنعت بزنید تا کندل‌ها و تک‌تک
            نمادها باز شود.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="مرتب‌سازی">
          <span className="text-xs text-muted">مرتب‌سازی:</span>
          {SORTS.map((s) => (
            <button
              key={s.key}
              type="button"
              className="tab tab-pill tab-sm"
              aria-pressed={sort === s.key}
              onClick={() => setSort(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="ic-grid">
        {rows.map((c) => (
          <Card key={c.code} c={c} market={doc.market_day} />
        ))}
      </div>
    </section>
  );
}
