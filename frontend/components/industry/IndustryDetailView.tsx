"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { Candle, IndustryDetail, IndustryMember } from "@/lib/api";
import { faNumber, faPercent, faPrice, faToman, jalali } from "@/lib/format";
import { memberPath } from "@/lib/slug";
import { signTone, verdictPill } from "@/lib/ui";
import type { ColumnCatalog } from "@/lib/columns";
import { CandleChart } from "@/components/CandleChart";
import { IndustryColumns } from "@/components/industry/IndustryColumns";
import { BreadthBar, Spark } from "@/components/market/Spark";

type Weight = "equal" | "value";

/** Net real-investor money of the last days: a bar up for money in, down for money out. */
function FlowBars({ d }: { d: IndustryDetail }) {
  const days = d.flow;
  if (days.length < 2) return null;
  const max = Math.max(...days.map((x) => Math.abs(x.net_real)), 1);
  return (
    <div className="space-y-1.5" data-testid="industry-flow">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-extrabold">پول حقیقی در {faNumber(days.length)} روز اخیر</h3>
        <span className="text-xs text-muted">بالا: ورود · پایین: خروج</span>
      </div>
      <div className="id-flow" dir="ltr">
        {days.map((x) => (
          <div
            key={x.date}
            className="id-fcol"
            title={`${jalali(x.date, "short")}: ${x.net_real >= 0 ? "ورود" : "خروج"} ${faToman(Math.abs(x.net_real))}`}
          >
            <span
              className={x.net_real >= 0 ? "bg-up" : "bg-down"}
              style={{
                height: `${(Math.abs(x.net_real) / max) * 50}%`,
                [x.net_real >= 0 ? "bottom" : "top"]: "50%",
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function Meter({ k, n, of, hint }: { k: string; n: number; of: number; hint: string }) {
  const share = of > 0 ? n / of : 0;
  return (
    <div className="id-meter" title={hint}>
      <div className="flex justify-between text-xs">
        <span className="text-muted">{k}</span>
        <b className="num">
          {faNumber(n)} از {faNumber(of)}
        </b>
      </div>
      <div className="id-meter-track">
        <span style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  );
}

type Col = {
  key: string;
  label: string;
  get: (m: IndustryMember) => number | string | null | undefined;
  hint?: string;
};
const COLS: Col[] = [
  { key: "symbol", label: "نماد", get: (m) => m.symbol },
  { key: "day", label: "امروز", get: (m) => m.day },
  {
    key: "contrib",
    label: "اثر امروز",
    get: (m) => m.contrib,
    hint: "چند واحد درصد از حرکت امروز صنعت به این نماد برمی‌گردد (صنعت میانگین ساده است)",
  },
  { key: "week", label: "هفته", get: (m) => m.week },
  { key: "month", label: "ماه", get: (m) => m.month },
  { key: "m3", label: "سه ماه", get: (m) => m.m3 },
  { key: "year", label: "سال", get: (m) => m.year },
  { key: "value", label: "ارزش معامله", get: (m) => m.value },
  { key: "flow", label: "پول حقیقی", get: (m) => m.net_real_flow },
];

/** The member's own candles, fetched when its row is opened. */
function MemberChart({ id }: { id: number }) {
  const [state, setState] = useState<{ id: number; candles: Candle[] | null } | null>(null);
  useEffect(() => {
    let live = true;
    fetch(`/api/candles/${id}?days=250`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { candles: [] }))
      .then((j: { candles: Candle[] }) => live && setState({ id, candles: j.candles }))
      .catch(() => live && setState({ id, candles: [] }));
    return () => {
      live = false;
    };
  }, [id]);
  if (state?.id !== id) return <p className="text-sm text-muted">در حال بارگذاری نمودار…</p>;
  if (!state.candles?.length)
    return <p className="text-sm text-muted">نمودار این نماد در دسترس نیست.</p>;
  return <CandleChart candles={state.candles} />;
}

function MemberDetail({
  d,
  m,
  colSpan,
}: {
  d: IndustryDetail;
  m: IndustryMember;
  colSpan: number;
}) {
  return (
    <tr className="id-open" data-testid="member-detail">
      <td colSpan={colSpan}>
        <div className="id-open-body">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <span>
              قیمت پایانی: <b className="num">{m.close == null ? "—" : faPrice(m.close)}</b>
            </span>
            <span>
              از بیشترین یک سال:{" "}
              <b className={`num ${signTone(m.from_year_high)}`}>
                {m.from_year_high == null ? "—" : faPercent(m.from_year_high, 1)}
              </b>
            </span>
            <span>
              میانگین ۲۰ روزه:{" "}
              <b>{m.above_sma20 == null ? "کم‌سابقه" : m.above_sma20 ? "بالای آن" : "زیر آن"}</b>
            </span>
            <span>
              سهم از ارزش صنعت:{" "}
              <b className="num">{m.value_share == null ? "—" : faPercent(m.value_share, 0)}</b>
            </span>
            <span className={verdictPill(m.verdict)}>{m.verdict_label}</span>
            <Link href={memberPath(d, m)} className="text-accent underline">
              صفحهٔ کامل {m.symbol}
            </Link>
          </div>
          <MemberChart id={m.instrument_id} />
        </div>
      </td>
    </tr>
  );
}

function Members({ d }: { d: IndustryDetail }) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "value", dir: -1 });
  const [open, setOpen] = useState<number | null>(null);
  const rows = useMemo(() => {
    const col = COLS.find((c) => c.key === sort.key) ?? COLS[0];
    return [...d.members].sort((a, b) => {
      const x = col.get(a);
      const y = col.get(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1; // a missing value goes last either way
      if (y == null) return -1;
      if (typeof x === "string" || typeof y === "string")
        return sort.dir * String(x).localeCompare(String(y), "fa");
      return sort.dir * (x - y);
    });
  }, [d.members, sort]);
  const maxContrib = Math.max(...d.members.map((m) => Math.abs(m.contrib ?? 0)), 1e-9);
  const colSpan = COLS.length + 2;
  const th = (c: Col) => (
    <th
      key={c.key}
      aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      title={c.hint}
    >
      <button
        type="button"
        className="id-th"
        onClick={() =>
          setSort((s) =>
            s.key === c.key
              ? { key: c.key, dir: s.dir === 1 ? -1 : 1 }
              : { key: c.key, dir: c.key === "symbol" ? 1 : -1 },
          )
        }
      >
        {c.label}
        {sort.key === c.key && <span aria-hidden>{sort.dir === 1 ? " ▲" : " ▼"}</span>}
      </button>
    </th>
  );
  return (
    <section className="card card-flush" data-testid="industry-members">
      <div className="px-4 pt-4">
        <h2 className="text-lg font-black">تک‌تک نمادهای صنعت</h2>
        <p className="text-xs leading-6 text-muted">
          {faNumber(d.n_traded)} نماد امروز معامله شدند (از {faNumber(d.n_members)}). روی سرستون
          بزنید تا مرتب شود و روی هر نماد بزنید تا نمودار خودش باز شود.
        </p>
      </div>
      <div className="id-scroll">
        <table className="tbl id-tbl">
          <thead>
            <tr>
              {COLS.map(th)}
              <th>روند ۶۰ روز</th>
              <th>تصمیم مدل</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const on = open === m.instrument_id;
              return [
                <tr
                  key={m.instrument_id}
                  className={on ? "id-row is-open" : "id-row"}
                  data-testid="member-row"
                  onClick={() => setOpen(on ? null : m.instrument_id)}
                >
                  <td>
                    <button
                      type="button"
                      className="id-sym"
                      aria-expanded={on}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpen(on ? null : m.instrument_id);
                      }}
                    >
                      <b>{m.symbol}</b>
                      <small>{m.name}</small>
                    </button>
                  </td>
                  <td className={`num font-bold ${signTone(m.day)}`}>
                    {m.day == null ? "—" : faPercent(m.day, 2, true)}
                  </td>
                  <td>
                    <div className="id-contrib" dir="ltr">
                      <span
                        className={(m.contrib ?? 0) >= 0 ? "bg-up" : "bg-down"}
                        style={{
                          width: `${(Math.abs(m.contrib ?? 0) / maxContrib) * 50}%`,
                          [(m.contrib ?? 0) >= 0 ? "left" : "right"]: "50%",
                        }}
                      />
                    </div>
                    <span className={`text-xs num ${signTone(m.contrib)}`}>
                      {m.contrib == null ? "—" : faPercent(m.contrib, 2, true)}
                    </span>
                  </td>
                  {[m.week, m.month, m.m3, m.year].map((v, i) => (
                    <td key={i} className={`num ${signTone(v)}`}>
                      {v == null ? "—" : faPercent(v, 1, true)}
                    </td>
                  ))}
                  <td className="num">{m.value == null ? "—" : faToman(m.value)}</td>
                  <td className={`num ${signTone(m.net_real_flow)}`}>
                    {m.net_real_flow == null
                      ? "—"
                      : `${m.net_real_flow >= 0 ? "+" : "−"}${faToman(Math.abs(m.net_real_flow))}`}
                  </td>
                  <td>
                    <Spark values={m.spark} width={84} height={26} />
                  </td>
                  <td>
                    <span className={verdictPill(m.verdict)}>{m.verdict_label}</span>
                  </td>
                </tr>,
                on && <MemberDetail key={`${m.instrument_id}-d`} d={d} m={m} colSpan={colSpan} />,
              ];
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** One industry as the consensus of its symbols, and then each symbol. */
export function IndustryDetailView({
  d,
  catalog = null,
}: {
  d: IndustryDetail;
  catalog?: ColumnCatalog | null;
}) {
  const [weight, setWeight] = useState<Weight>("equal");
  const candles = weight === "equal" ? d.candles : d.candles_value;
  const day = weight === "equal" ? d.day : d.day_value;
  const b = d.breadth;
  return (
    <div className="space-y-5">
      <section className="card id-hero" data-testid="industry-hero">
        <div className="ix-glow" aria-hidden />
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <p className="eyebrow">
              اجماع {faNumber(d.n_traded)} نماد · {jalali(d.as_of, "weekday")}
            </p>
            <p className={`ix-level num ${signTone(day)}`} data-testid="industry-day">
              {day == null ? "—" : faPercent(day, 2, true)}
            </p>
            <p className="text-xs text-muted">
              حرکت امروز صنعت (
              {weight === "equal" ? "هر نماد یک رأی" : "به نسبت ارزش معامله‌های دیروز"})
            </p>
          </div>
          <dl className="id-facts">
            <div>
              <dt>ارزش معاملهٔ امروز</dt>
              <dd className="num">{faToman(d.value)}</dd>
              <small>{faPercent(d.value_share, 1)} از کل بازار</small>
            </div>
            <div>
              <dt>پول حقیقی</dt>
              <dd className={`num ${signTone(d.net_real_flow)}`}>
                {d.net_real_flow == null
                  ? "—"
                  : `${d.net_real_flow >= 0 ? "ورود " : "خروج "}${faToman(Math.abs(d.net_real_flow))}`}
              </dd>
              <small>{d.flow_date ? jalali(d.flow_date, "short") : ""}</small>
            </div>
            <div>
              <dt>نمادهای مثبت / منفی</dt>
              <dd className="num">
                <span className="text-up">{faNumber(b.up)}</span> /{" "}
                <span className="text-down">{faNumber(b.down)}</span>
              </dd>
              <small>{b.flat > 0 ? `${faNumber(b.flat)} بدون تغییر` : " "}</small>
            </div>
          </dl>
        </div>
        <BreadthBar
          up={b.up}
          flat={b.flat}
          down={b.down}
          label={`${faNumber(b.up)} نماد مثبت، ${faNumber(b.down)} منفی`}
        />
      </section>

      <section className="card min-w-0 space-y-3" data-testid="industry-chart">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-black">کندل صنعت</h2>
          <div className="flex gap-1.5" role="group" aria-label="وزن نمادها">
            <button
              type="button"
              className="tab tab-pill"
              aria-pressed={weight === "equal"}
              onClick={() => setWeight("equal")}
            >
              هر نماد یک رأی
            </button>
            <button
              type="button"
              className="tab tab-pill"
              aria-pressed={weight === "value"}
              onClick={() => setWeight("value")}
            >
              به نسبت ارزش معامله
            </button>
          </div>
        </div>
        {candles.length === 0 ? (
          <p className="text-sm text-muted">برای این صنعت کندلی ساخته نشد.</p>
        ) : (
          <CandleChart key={weight} candles={candles} />
        )}
        <p className="text-xs leading-6 text-muted">
          هر کندل میانگین کندل نمادهای صنعت است، هر کدام نسبت به پایانی تعدیل‌شدهٔ دیروز خودش؛ سطح از
          ۱۰۰ شروع می‌شود. بیشینه و کمینه تقریبی‌اند (نمادها هم‌زمان به سقف و کفشان نمی‌رسند) و
          بازگشایی لزوماً با پایانی دیروز برابر نیست. این یک شاخص قابل خرید نیست و فقط حال صنعت را
          نشان می‌دهد. جهش‌های بیش از ۵۰٪ در یک روز (خطای تعدیل) کنار گذاشته می‌شوند.
        </p>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card space-y-3" data-testid="industry-returns">
          <h2 className="text-lg font-black">بازده صنعت و فاصله با بازار</h2>
          <div className="id-rets">
            {d.returns.map((r) => (
              <div key={r.label} className="id-ret">
                <span className="text-xs text-muted">{r.label}</span>
                <b className={`num ${signTone(r.value)}`}>
                  {r.value == null ? "—" : faPercent(r.value, 1, true)}
                </b>
                <small className={signTone(r.vs_market)}>
                  {r.vs_market == null
                    ? "—"
                    : `${r.vs_market >= 0 ? "جلوتر" : "عقب‌تر"} از بازار ${faPercent(Math.abs(r.vs_market), 1)}`}
                </small>
              </div>
            ))}
          </div>
          <p className="text-xs leading-6 text-muted">
            بازار یعنی شاخص کل هم‌وزن بورس. تفاوت‌ها با «واحد درصد» سنجیده شده‌اند، نه درصدِ درصد.
          </p>
        </section>

        <section className="card space-y-3" data-testid="industry-breadth">
          <h2 className="text-lg font-black">وضعیت نمادها</h2>
          <Meter
            k="بالای میانگین ۲۰ روزه"
            n={b.above_sma20}
            of={b.n_trend}
            hint="نمادهایی که قیمت پایانی‌شان بالاتر از میانگین ۲۰ روز اخیر خودشان است"
          />
          <Meter
            k="بالای میانگین ۵۰ روزه"
            n={b.above_sma50}
            of={b.n_trend}
            hint="نمادهایی که قیمت پایانی‌شان بالاتر از میانگین ۵۰ روز اخیر خودشان است"
          />
          <Meter
            k="نزدیک بیشترین یک سال (تا ۳٪)"
            n={b.near_year_high}
            of={b.n_trend}
            hint="نمادهایی که تا ۳٪ با بیشترین قیمت یک سال اخیرشان فاصله دارند"
          />
          <FlowBars d={d} />
        </section>
      </div>

      <Members d={d} />
      {catalog && <IndustryColumns d={d} catalog={catalog} />}
    </div>
  );
}
