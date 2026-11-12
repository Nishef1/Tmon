"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useDeferredValue, useMemo, useState, type ReactNode } from "react";
import { Gauge } from "@/components/Gauge";
import { faCount, faNumber, faPercent, faToman, jalali } from "@/lib/format";
import {
  EMPTY,
  activeCount,
  applyFilters,
  byRelevance,
  gaugeWhy,
  industries,
  norm,
  sortRows,
  type Filters,
  type Industry,
  type IndustrySort,
  type Range,
  type Row,
  type SortKey,
  type Verdict,
} from "@/lib/industry";
import { heatProps, signTone, signedPct, verdictPill } from "@/lib/ui";

const VERDICTS: [Verdict, string][] = [
  ["buy", "خرید"],
  ["hold", "نگهداری"],
  ["sell", "فروش"],
  ["none", "تصمیمی نیست"],
];

const INDUSTRY_ORDER: [IndustrySort, string][] = [
  ["value", "ارزش معاملات"],
  ["volume", "حجم معاملات"],
  ["cap", "ارزش بازار"],
  ["count", "تعداد نماد"],
  ["day", "بازده امروز"],
  ["week", "بازده هفته"],
  ["month", "بازده ماه"],
  ["year", "بازده سال"],
];

type Col = {
  key: SortKey;
  label: string;
  title: string;
  on: boolean;
  cell: (r: Row) => ReactNode;
  agg?: (i: Industry) => ReactNode;
  cls?: (r: Row) => string;
  aggCls?: (i: Industry) => string;
};

const COLS: Col[] = [
  {
    key: "gauge",
    label: "تصمیم و امتیاز",
    title: "تصمیم مدل و امتیاز ترکیبی ۰ تا ۱۰۰ (قرمز ضعیف، سبز قوی)",
    on: true,
    cell: (r) => (
      <div className="flex items-center gap-2">
        <Gauge value={r.gauge} size="sm" label="امتیاز ترکیبی مدل" />
        <div className="leading-tight">
          <span className={`${verdictPill(r.verdict)}`} data-verdict={r.verdict}>
            {r.verdictLabel || "—"}
          </span>
          <div className="text-xs text-muted">
            {r.gauge == null ? gaugeWhy(r.gaugeNote) : faNumber(r.gauge)}
          </div>
        </div>
      </div>
    ),
    agg: (i) => (
      <span className="text-xs">
        {i.verdicts.buy > 0 && <span className="text-up">{faNumber(i.verdicts.buy)} خرید </span>}
        {i.verdicts.hold > 0 && <span className="text-hold">{faNumber(i.verdicts.hold)} نگه </span>}
        {i.verdicts.sell > 0 && <span className="text-down">{faNumber(i.verdicts.sell)} فروش</span>}
        {i.gauge != null && <div className="text-muted">میانگین {faNumber(i.gauge)}</div>}
      </span>
    ),
  },
  {
    key: "close",
    label: "قیمت پایانی",
    title: "قیمت پایانی آخرین روز معاملاتی (ریال)",
    on: true,
    cell: (r) => (r.close == null ? "—" : faNumber(r.close)),
  },
  {
    key: "day",
    label: "امروز",
    title: "بازده روز: قیمت پایانی نسبت به پایانی روز قبل",
    on: true,
    cell: (r) => signedPct(r.day, 2),
    cls: (r) => signTone(r.day),
    agg: (i) => signedPct(i.day, 2),
    aggCls: (i) => signTone(i.day),
  },
  {
    key: "week",
    label: "هفته",
    title: "بازده ۷ روز گذشته (قیمت تعدیل‌شده برای مجمع و افزایش سرمایه)",
    on: true,
    cell: (r) => signedPct(r.week),
    cls: (r) => signTone(r.week),
    agg: (i) => signedPct(i.week),
    aggCls: (i) => signTone(i.week),
  },
  {
    key: "month",
    label: "ماه",
    title: "بازده ۳۰ روز گذشته (تعدیل‌شده)",
    on: true,
    cell: (r) => signedPct(r.month),
    cls: (r) => signTone(r.month),
    agg: (i) => signedPct(i.month),
    aggCls: (i) => signTone(i.month),
  },
  {
    key: "m3",
    label: "۳ ماه",
    title: "بازده ۹۰ روز گذشته (تعدیل‌شده)",
    on: false,
    cell: (r) => signedPct(r.m3),
    cls: (r) => signTone(r.m3),
    agg: (i) => signedPct(i.m3),
    aggCls: (i) => signTone(i.m3),
  },
  {
    key: "year",
    label: "سال",
    title: "بازده ۳۶۵ روز گذشته (تعدیل‌شده)؛ برای نمادهای کمتر از یک سال سابقه خالی است",
    on: true,
    cell: (r) => signedPct(r.year, 0),
    cls: (r) => signTone(r.year),
    agg: (i) => signedPct(i.year, 0),
    aggCls: (i) => signTone(i.year),
  },
  {
    key: "value",
    label: "ارزش معاملات",
    title: "ارزش معاملات آخرین روز (تومان)",
    on: true,
    cell: (r) => faToman(r.value),
    agg: (i) => faToman(i.value),
  },
  {
    key: "volume",
    label: "حجم",
    title: "تعداد سهم معامله‌شده در آخرین روز",
    on: true,
    cell: (r) => faCount(r.volume),
    agg: (i) => faCount(i.volume),
  },
  {
    key: "cap",
    label: "ارزش بازار",
    title: "قیمت پایانی × تعداد سهام (تومان)",
    on: true,
    cell: (r) => faToman(r.cap),
    agg: (i) => faToman(i.cap),
  },
  {
    key: "pe",
    label: "P/E",
    title: "قیمت به سود هر سهم؛ برای نمادهای زیان‌ده یا بدون EPS خالی است",
    on: true,
    cell: (r) =>
      r.pe == null ? (
        "—"
      ) : (
        <span title={r.sectorPe == null ? undefined : `میانگین گروه: ${faNumber(r.sectorPe, 1)}`}>
          {faNumber(r.pe, 1)}
        </span>
      ),
  },
  {
    key: "eps",
    label: "EPS",
    title: "سود (زیان) هر سهم (ریال)",
    on: false,
    cell: (r) => (r.eps == null ? "—" : faNumber(r.eps)),
    cls: (r) => (r.eps != null && r.eps < 0 ? "text-down" : ""),
  },
  {
    key: "fromHigh",
    label: "تا سقف سال",
    title: "فاصلهٔ قیمت پایانی تا بالاترین قیمت تعدیل‌شدهٔ یک سال اخیر",
    on: false,
    cell: (r) => signedPct(r.fromHigh, 0),
    cls: (r) => signTone(r.fromHigh),
  },
  {
    key: "power",
    label: "قدرت خریدار",
    title: "سرانهٔ خرید حقیقی تقسیم بر سرانهٔ فروش حقیقی؛ بالای ۱ یعنی خریدار قوی‌تر است",
    on: true,
    cell: (r) => (r.power == null ? "—" : faNumber(r.power, 2)),
    cls: (r) => (r.power == null ? "" : r.power >= 1 ? "text-up" : "text-down"),
  },
  {
    key: "netReal",
    label: "خالص ورود حقیقی",
    title: "خرید حقیقی منهای فروش حقیقی (تومان)؛ مثبت یعنی ورود پول",
    on: true,
    cell: (r) => faToman(r.netReal),
    cls: (r) => signTone(r.netReal),
    agg: (i) => faToman(i.netReal),
    aggCls: (i) => signTone(i.netReal),
  },
  {
    key: "volRatio",
    label: "نسبت حجم",
    title: "حجم امروز نسبت به میانگین ۳۰ روز؛ بالای ۱ یعنی پرمعامله‌تر از عادت",
    on: false,
    cell: (r) => (r.volRatio == null ? "—" : faNumber(r.volRatio, 2)),
  },
  {
    key: "rsi",
    label: "RSI",
    title: "شاخص قدرت نسبی ۱۴ روزه؛ بالای ۷۰ اشباع خرید، زیر ۳۰ اشباع فروش",
    on: false,
    cell: (r) => (r.rsi == null ? "—" : faNumber(r.rsi, 0)),
  },
  {
    key: "rank",
    label: "رتبهٔ سبد پرمعامله",
    title: "رتبهٔ نماد میان ۱۰۰ نمادِ پرنقدشوندهٔ مدل رتبه‌بندی؛ ۱ بهترین است",
    on: false,
    cell: (r) => (r.rank == null ? "—" : faNumber(r.rank)),
  },
  {
    key: "perBuy",
    label: "سرانهٔ خرید",
    title: "میانگین ارزش خرید هر خریدار حقیقی (تومان)",
    on: false,
    cell: (r) => faToman(r.perBuy),
  },
  {
    key: "perSell",
    label: "سرانهٔ فروش",
    title: "میانگین ارزش فروش هر فروشندهٔ حقیقی (تومان)",
    on: false,
    cell: (r) => faToman(r.perSell),
  },
  {
    key: "meeting",
    label: "مجمع بعدی",
    title: "تاریخ برگزاری مجمع بعدی بر پایهٔ آگهی دعوت در کدال",
    on: true,
    cell: (r) => (r.meeting ? jalali(r.meeting, "short") : "—"),
  },
];

// ------------------------------------------------------------------------------ form pieces

function parse(text: string, scale: number): number | undefined {
  const t = norm(text).replace(/[٫,]/g, ".").replace(/−/g, "-");
  if (t === "") return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n / scale : undefined;
}

/** Two boxes (from / to). ``scale`` converts what the reader types to the stored unit. */
function RangeField({
  label,
  unit,
  scale = 1,
  onChange,
}: {
  label: string;
  unit: string;
  scale?: number;
  onChange: (r: Range) => void;
}) {
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  const send = (a: string, b: string) => onChange({ min: parse(a, scale), max: parse(b, scale) });
  const box = "ctl w-20";
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-xs text-muted">
        {label} <span className="opacity-80">({unit})</span>
      </legend>
      <div className="flex items-center gap-1">
        <input
          aria-label={`${label}: از`}
          inputMode="decimal"
          placeholder="از"
          value={lo}
          onChange={(e) => {
            setLo(e.target.value);
            send(e.target.value, hi);
          }}
          className={box}
        />
        <span aria-hidden>–</span>
        <input
          aria-label={`${label}: تا`}
          inputMode="decimal"
          placeholder="تا"
          value={hi}
          onChange={(e) => {
            setHi(e.target.value);
            send(lo, e.target.value);
          }}
          className={box}
        />
      </div>
    </fieldset>
  );
}

function SingleField({
  label,
  unit,
  scale,
  onChange,
}: {
  label: string;
  unit: string;
  scale: number;
  onChange: (n: number | undefined) => void;
}) {
  const [v, setV] = useState("");
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">
        {label} <span className="opacity-80">({unit})</span>
      </span>
      <input
        aria-label={label}
        inputMode="decimal"
        placeholder="حداقل"
        value={v}
        onChange={(e) => {
          setV(e.target.value);
          onChange(parse(e.target.value, scale));
        }}
        className="ctl w-28"
      />
    </label>
  );
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="tab tab-pill">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-[var(--accent)]"
      />
      {label}
    </label>
  );
}

// ------------------------------------------------------------------------------------ page

export function IndustryTable({ rows, initialQuery = "" }: { rows: Row[]; initialQuery?: string }) {
  const router = useRouter();
  const [f, setF] = useState<Filters>({ ...EMPTY, q: initialQuery });
  const [reset, setReset] = useState(0);
  const [grouped, setGrouped] = useState(true);
  const [order, setOrder] = useState<IndustrySort>("value");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);
  const [shown, setShown] = useState<Set<SortKey>>(
    () => new Set(COLS.filter((c) => c.on).map((c) => c.key)),
  );
  const [closed, setClosed] = useState<Set<string>>(new Set());

  const q = useDeferredValue(f.q);
  const filtered = useMemo(() => applyFilters(rows, { ...f, q }, new Date()), [rows, f, q]);
  const all = useMemo(() => industries(rows, order), [rows, order]);
  const groups = useMemo(() => industries(filtered, order), [filtered, order]);
  const totalValue = useMemo(() => all.reduce((a, i) => a + i.value, 0), [all]);

  const set = (p: Partial<Filters>) => setF((cur) => ({ ...cur, ...p }));
  const cols = COLS.filter((c) => shown.has(c.key));

  const ordered = useCallback(
    (rs: Row[]): Row[] => {
      if (sort) return sortRows(rs, sort.key, sort.dir);
      if (q.trim()) return byRelevance(rs, q);
      return sortRows(rs, "value", -1);
    },
    [sort, q],
  );
  const flat = useMemo(() => ordered(filtered), [ordered, filtered]);

  function toggle<T>(list: T[], v: T): T[] {
    return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
  }

  function head(key: SortKey) {
    setSort((s) =>
      s?.key === key
        ? s.dir === -1
          ? { key, dir: 1 }
          : null
        : { key, dir: key === "symbol" || key === "meeting" ? 1 : -1 },
    );
  }

  const nActive = activeCount(f);
  const colCount = cols.length + 1;

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------------ industry heat map */}
      <section aria-labelledby="map" className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="map" className="text-lg font-bold">
            نقشهٔ صنایع
          </h2>
          <p className="text-xs text-muted">
            ترتیب: بیشترین {INDUSTRY_ORDER.find(([k]) => k === order)?.[1]} · رنگ: بازدهٔ امروز
            (وزن‌دار با ارزش بازار) · روی هر صنعت بزنید تا فقط همان نمایش داده شود
          </p>
        </div>
        <ul
          className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
          data-testid="industry-map"
        >
          {all.map((i) => {
            const on = f.sectors.includes(i.name);
            const share = totalValue > 0 ? i.value / totalValue : 0;
            return (
              <li key={i.name}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => set({ sectors: toggle(f.sectors, i.name) })}
                  {...heatProps(i.day)}
                  className="tile tile-toggle flex h-full w-full flex-col gap-1 text-start"
                >
                  <span className="font-bold leading-snug">{i.name}</span>
                  <span className="flex items-baseline justify-between gap-2 text-sm">
                    <span className={`font-bold ${signTone(i.day)}`}>{signedPct(i.day, 2)}</span>
                    <span className="text-xs text-muted">{faNumber(i.count)} نماد</span>
                  </span>
                  <span className="text-xs text-muted">
                    {faToman(i.value)} · {faPercent(share, 1)} از کل بازار
                  </span>
                  <span aria-hidden className="mt-auto block h-1.5 rounded-full bg-line">
                    <span
                      className="block h-1.5 rounded-full bg-accent"
                      style={{
                        width: `${Math.max(2, share * 100 * 2.5).toFixed(1)}%`,
                        maxWidth: "100%",
                      }}
                    />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* ------------------------------------------------------------------- filters */}
      <section aria-labelledby="filters" className="card space-y-3 text-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="filters" className="text-lg font-bold">
            جست‌وجو و فیلتر
          </h2>
          <button
            type="button"
            disabled={nActive === 0}
            onClick={() => {
              setF(EMPTY);
              setReset((n) => n + 1);
            }}
            className="btn"
          >
            حذف همهٔ فیلترها {nActive > 0 && `(${faNumber(nActive)})`}
          </button>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">
            نماد، نام کامل شرکت یا صنعت؛ نمادهای مشابه هم نشان داده می‌شوند (مثلاً «فول» یا «خودرو
            ایران»)
          </span>
          <input
            type="search"
            value={f.q}
            onChange={(e) => set({ q: e.target.value })}
            placeholder="جست‌وجو…"
            aria-label="جست‌وجوی نماد"
            className="ctl w-full"
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">تصمیم:</span>
          {VERDICTS.map(([v, label]) => {
            const on = f.verdicts.includes(v);
            return (
              <button
                key={v}
                type="button"
                aria-pressed={on}
                onClick={() => set({ verdicts: toggle(f.verdicts, v) })}
                className="tab tab-pill"
              >
                <span className={`me-1 inline-block size-2 rounded-full v-${v}`} />
                {label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-end gap-x-4 gap-y-3" key={reset}>
          <RangeField label="بازده امروز" unit="٪" scale={0.01} onChange={(day) => set({ day })} />
          <RangeField label="بازده هفته" unit="٪" scale={0.01} onChange={(week) => set({ week })} />
          <RangeField
            label="بازده ماه"
            unit="٪"
            scale={0.01}
            onChange={(month) => set({ month })}
          />
          <RangeField label="بازده سال" unit="٪" scale={0.01} onChange={(year) => set({ year })} />
          <RangeField label="P/E" unit="برابر" onChange={(pe) => set({ pe })} />
          <RangeField label="امتیاز مدل" unit="۰ تا ۱۰۰" onChange={(gauge) => set({ gauge })} />
          <SingleField
            label="حداقل ارزش معاملات"
            unit="میلیارد تومان"
            scale={1e10}
            onChange={(minValue) => set({ minValue })}
          />
          <SingleField
            label="حداقل ارزش بازار"
            unit="همت"
            scale={1e13}
            onChange={(minCap) => set({ minCap })}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <Check
            label="قدرت خریدار بالای ۱"
            checked={f.powerAbove1}
            onChange={(powerAbove1) => set({ powerAbove1 })}
          />
          <Check
            label="ورود خالص پول حقیقی"
            checked={f.netBuyers}
            onChange={(netBuyers) => set({ netBuyers })}
          />
          <Check
            label="نزدیک سقف سال (تا ۱۰٪)"
            checked={f.nearHigh}
            onChange={(nearHigh) => set({ nearHigh })}
          />
          <Check
            label="مجمع تا ۳۰ روز آینده"
            checked={f.meetingSoon}
            onChange={(meetingSoon) => set({ meetingSoon })}
          />
        </div>
      </section>

      {/* ------------------------------------------------------------------- controls */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3 text-sm">
          <h2 className="text-lg font-bold" data-testid="result-count">
            {faNumber(filtered.length)} نماد از {faNumber(rows.length)}
            {grouped && ` در ${faNumber(groups.length)} صنعت`}
          </h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted">ترتیب صنایع</span>
              <select
                value={order}
                onChange={(e) => setOrder(e.target.value as IndustrySort)}
                className="ctl"
              >
                {INDUSTRY_ORDER.map(([k, l]) => (
                  <option key={k} value={k}>
                    بیشترین {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="tab">
              <input
                type="checkbox"
                checked={grouped}
                onChange={(e) => setGrouped(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              دسته‌بندی بر پایهٔ صنعت
            </label>
            <details className="relative">
              <summary className="btn">ستون‌ها ({faNumber(shown.size)})</summary>
              <ul className="absolute end-0 z-30 mt-1 max-h-80 w-56 space-y-1 overflow-auto popover p-3">
                {COLS.map((c) => (
                  <li key={c.key}>
                    <label className="flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={shown.has(c.key)}
                        onChange={() =>
                          setShown((cur) => {
                            const next = new Set(cur);
                            if (next.has(c.key)) next.delete(c.key);
                            else next.add(c.key);
                            return next;
                          })
                        }
                        className="accent-[var(--accent)]"
                      />
                      {c.label}
                    </label>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </div>

        {filtered.length === 0 ? (
          <p className="card card-pad-lg text-center" role="status">
            هیچ نمادی با این فیلترها پیدا نشد. فیلترها را کم کنید یا همه را حذف کنید.
          </p>
        ) : (
          <div className="card card-flush max-h-[78vh] overflow-auto">
            <table
              className="w-full min-w-[64rem] border-separate border-spacing-0 text-sm"
              data-testid="industry-table"
            >
              <caption className="sr-only">نمادها به تفکیک صنعت</caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="sticky start-0 top-0 z-30 border-b border-line bg-surface px-3 py-2 text-start font-medium"
                  >
                    <button
                      type="button"
                      onClick={() => head("symbol")}
                      className="font-medium hover:text-accent"
                    >
                      نماد{sort?.key === "symbol" ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                    </button>
                  </th>
                  {cols.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      title={c.title}
                      aria-sort={
                        sort?.key === c.key
                          ? sort.dir === 1
                            ? "ascending"
                            : "descending"
                          : undefined
                      }
                      className="sticky top-0 z-20 whitespace-nowrap border-b border-line bg-surface px-2 py-2 text-start font-medium"
                    >
                      <button
                        type="button"
                        onClick={() => head(c.key)}
                        className="font-medium hover:text-accent"
                      >
                        {c.label}
                        {sort?.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              {grouped ? (
                groups.map((i) => {
                  const shut = closed.has(i.name);
                  return (
                    <tbody key={i.name} data-industry={i.name}>
                      <tr className="bg-accent-soft font-semibold">
                        <th
                          scope="rowgroup"
                          className="sticky start-0 z-10 border-b border-line bg-accent-soft px-3 py-2 text-start"
                        >
                          <button
                            type="button"
                            aria-expanded={!shut}
                            onClick={() =>
                              setClosed((cur) => {
                                const next = new Set(cur);
                                if (next.has(i.name)) next.delete(i.name);
                                else next.add(i.name);
                                return next;
                              })
                            }
                            className="flex items-center gap-2 text-start"
                          >
                            <span aria-hidden className="text-xs">
                              {shut ? "◀" : "▼"}
                            </span>
                            <span>
                              {i.name}
                              <span className="block text-xs font-normal text-muted">
                                {faNumber(i.count)} نماد
                              </span>
                            </span>
                          </button>
                        </th>
                        {cols.map((c) => (
                          <td
                            key={c.key}
                            className={`whitespace-nowrap border-b border-line px-2 py-2 ${c.aggCls?.(i) ?? ""}`}
                          >
                            {c.agg ? c.agg(i) : ""}
                          </td>
                        ))}
                      </tr>
                      {!shut &&
                        ordered(i.rows).map((r) => (
                          <DataRow
                            key={r.id}
                            r={r}
                            cols={cols}
                            go={(id) => router.push(`/instruments/${id}`)}
                          />
                        ))}
                    </tbody>
                  );
                })
              ) : (
                <tbody>
                  {flat.map((r) => (
                    <DataRow
                      key={r.id}
                      r={r}
                      cols={cols}
                      flat
                      go={(id) => router.push(`/instruments/${id}`)}
                    />
                  ))}
                </tbody>
              )}
              <tfoot>
                <tr>
                  <td colSpan={colCount} className="px-3 py-2 text-xs text-muted">
                    بازدهٔ صنعت میانگین وزنی بازدهٔ نمادها با وزن ارزش بازار است. بازده‌ها روی قیمت
                    تعدیل‌شده برای مجمع و افزایش سرمایه محاسبه می‌شوند؛ خانهٔ خالی یعنی داده یا
                    سابقهٔ کافی وجود ندارد.
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function DataRow({
  r,
  cols,
  go,
  flat = false,
}: {
  r: Row;
  cols: Col[];
  go: (id: number) => void;
  flat?: boolean;
}) {
  return (
    <tr
      onClick={() => go(r.id)}
      className="group cursor-pointer hover:bg-accent-soft"
      data-symbol={r.symbol}
    >
      <th
        scope="row"
        className="sticky start-0 z-10 border-b border-line bg-surface px-3 py-1.5 text-start font-normal group-hover:bg-accent-soft"
      >
        <Link
          href={`/instruments/${r.id}`}
          onClick={(e) => e.stopPropagation()}
          className="font-bold hover:text-accent"
        >
          {r.symbol}
        </Link>
        <div className="max-w-44 truncate text-xs text-muted" title={r.name}>
          {flat ? `${r.sector} · ` : ""}
          {r.name}
        </div>
      </th>
      {cols.map((c) => (
        <td
          key={c.key}
          className={`whitespace-nowrap border-b border-line px-2 py-1.5 ${c.cls?.(r) ?? ""}`}
          {...(c.key === "day" ? heatProps(r.day) : {})}
        >
          {c.cell(r)}
        </td>
      ))}
    </tr>
  );
}
