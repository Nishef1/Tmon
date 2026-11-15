"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { faNumber, faPercent, faPrice, faToman, jalali } from "@/lib/format";
import {
  call,
  useNotificationPermission,
  useSaved,
  type Advice,
  type Alert,
  type Briefing,
  type BriefingDoc,
  type Forecast,
  type Portfolio,
} from "@/lib/portfolio";
import { signedPct, signTone } from "@/lib/ui";
import { ForecastCandles } from "./ForecastCandles";
import { HistoryCard, HoldingEvents, MofidCard, Summary, Trades } from "./Ledger";

const POLL_MS = 10_000;
const SEV = {
  1: { text: "اطلاع", cls: "badge" },
  2: { text: "هشدار", cls: "badge badge-warn" },
  3: { text: "فوری", cls: "badge badge-down" },
} as const;
const ANSWER_FA: Record<string, string> = {
  exit: "خارج می‌شوم",
  reduce: "نصف را می‌فروشم",
  hold: "نگه می‌دارم",
};

function sevOf(n: number) {
  return SEV[(n >= 3 ? 3 : n <= 1 ? 1 : 2) as 1 | 2 | 3];
}

// -- alerts -----------------------------------------------------------------------------------
function AlertsFeed({ id, pkey }: { id: number; pkey: string }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [perm, askPerm] = useNotificationPermission();
  const last = useRef(0);

  const poll = useCallback(async () => {
    try {
      const fresh = await call<Alert[]>(`/${id}/alerts?after=${last.current}`, pkey);
      if (!fresh.length) return;
      const first = last.current === 0;
      last.current = Math.max(last.current, ...fresh.map((a) => a.id));
      setAlerts((old) => [...fresh, ...old].slice(0, 200));
      if (!first && typeof Notification !== "undefined" && Notification.permission === "granted") {
        for (const a of fresh.filter((x) => x.severity >= 2)) {
          new Notification(a.title, {
            body: a.body,
            tag: `alert-${a.id}`,
            requireInteraction: a.severity >= 3,
          });
        }
      }
    } catch {
      /* next poll retries */
    }
  }, [id, pkey]);

  useEffect(() => {
    void poll();
    const t = setInterval(() => void poll(), POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  async function answer(a: Alert, value: string) {
    const r = await call<Alert>(`/${id}/alerts/${a.id}/answer`, pkey, {
      method: "POST",
      body: { answer: value },
    }).catch(() => null);
    if (r) setAlerts((old) => old.map((x) => (x.id === r.id ? r : x)));
  }

  return (
    <section className="card" aria-live="polite" data-testid="alerts">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold">هشدارها (هر ۱۰ ثانیه به‌روز)</h2>
        {perm === "default" && (
          <button type="button" className="btn" onClick={() => void askPerm()}>
            اعلان مرورگر را روشن کن
          </button>
        )}
      </div>
      {alerts.length === 0 ? (
        <p className="mt-2 text-muted">هشداری ثبت نشده است.</p>
      ) : (
        <ul className="mt-2 grid gap-2">
          {alerts.map((a) => {
            const s = sevOf(a.severity);
            return (
              <li
                key={a.id}
                className={a.severity >= 3 ? "card card-down" : "well"}
                data-sev={a.severity}
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className={s.cls}>{s.text}</span>
                  <b>{a.title}</b>
                  <span className="text-xs text-muted">
                    {new Date(a.created_at).toLocaleString("fa-IR")}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-line text-sm">{a.body}</p>
                {a.ask_exit &&
                  (a.answer ? (
                    <p className="mt-1 text-sm">
                      پاسخ تو: <b>{ANSWER_FA[a.answer] ?? a.answer}</b>
                    </p>
                  ) : (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(ANSWER_FA).map(([k, label]) => (
                        <button
                          key={k}
                          type="button"
                          className={k === "exit" ? "btn btn-primary" : "btn"}
                          onClick={() => void answer(a, k)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  ))}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// -- holdings ---------------------------------------------------------------------------------
function Holdings({
  p,
  pkey,
  onChange,
}: {
  p: Portfolio;
  pkey: string;
  onChange: (p: Portfolio) => void;
}) {
  const [f, setF] = useState({ symbol: "", shares: "", price: "", amount: "", date: "", stop: "" });
  const [err, setErr] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      onChange(
        await call<Portfolio>(`/${p.id}/holdings`, pkey, {
          method: "POST",
          body: {
            symbol: f.symbol.trim(),
            shares: Number(f.shares) || null,
            avg_price: Number(f.price) || null,
            amount: Number(f.amount) ? Number(f.amount) * 10 : null,
            bought_on: f.date || null,
            stop_price: f.stop ? Number(f.stop) : null,
          },
        }),
      );
      setF({ symbol: "", shares: "", price: "", amount: "", date: "", stop: "" });
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  async function remove(hid: number) {
    onChange(await call<Portfolio>(`/${p.id}/holdings/${hid}`, pkey, { method: "DELETE" }));
  }

  return (
    <section className="card">
      <h2 className="font-bold">دارایی‌ها</h2>
      <p className="mt-1 text-sm text-muted">
        ارزش {faToman(p.market_value)} تومان · سود باز{" "}
        <b className={signTone(p.pnl)}>{signedPct(p.pnl_pct)}</b> ({faToman(p.pnl)} تومان) — پس از
        کارمزد و مالیات فروش.
      </p>
      {p.holdings.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="tbl w-full min-w-[48rem] text-sm" data-testid="holdings">
            <thead>
              <tr>
                <th>نماد</th>
                <th>تعداد</th>
                <th>میانگین خرید (ریال)</th>
                <th>آخرین (ریال)</th>
                <th>ارزش (تومان)</th>
                <th>وزن</th>
                <th>حد ضرر</th>
                <th>سود باز</th>
                <th>سود کل (تومان)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {p.holdings.map((h) => (
                <tr key={h.id}>
                  <td>
                    <Link
                      href={`/instruments/${h.instrument_id}`}
                      className="font-bold hover:text-accent"
                    >
                      {h.symbol}
                    </Link>
                    {(h.size_estimated || h.price_estimated) && (
                      <span className="badge badge-warn mr-1" title="تعداد یا قیمت خرید برآورد شده">
                        برآوردی
                      </span>
                    )}
                    {h.price_missing ? (
                      <span className="badge badge-down mr-1">بی‌قیمت</span>
                    ) : (
                      h.stale && (
                        <span className="badge mr-1" title={`آخرین قیمت ${jalali(h.close_date)}`}>
                          قیمت قدیمی
                        </span>
                      )
                    )}
                  </td>
                  <td>{faNumber(h.shares)}</td>
                  <td>{faPrice(h.avg_price)}</td>
                  <td>{h.close != null ? faPrice(h.close) : "—"}</td>
                  <td>{faToman(h.market_value)}</td>
                  <td>{h.weight != null ? faPercent(h.weight, 0) : "—"}</td>
                  <td>{h.stop_price ? faPrice(h.stop_price) : "پیش‌فرض"}</td>
                  <td className={signTone(h.pnl)}>
                    {signedPct(h.pnl_pct)}
                    <div className="text-xs">{faToman(h.pnl)}</div>
                  </td>
                  <td className={signTone(h.total_pnl)}>{faToman(h.total_pnl)}</td>
                  <td>
                    <button
                      type="button"
                      className="text-muted hover:text-down"
                      onClick={() => void remove(h.id)}
                    >
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form onSubmit={add} className="mt-3 flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm">
          نماد
          <input
            className="ctl w-28"
            required
            value={f.symbol}
            onChange={(e) => setF({ ...f, symbol: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          تعداد سهم
          <input
            className="ctl w-32"
            dir="ltr"
            inputMode="numeric"
            value={f.shares}
            onChange={(e) => setF({ ...f, shares: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          قیمت خرید (ریال)
          <input
            className="ctl w-32"
            dir="ltr"
            inputMode="numeric"
            value={f.price}
            onChange={(e) => setF({ ...f, price: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          یا مبلغ خرید (تومان)
          <input
            className="ctl w-32"
            dir="ltr"
            inputMode="numeric"
            value={f.amount}
            onChange={(e) => setF({ ...f, amount: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          تاریخ خرید
          <input
            className="ctl"
            type="date"
            dir="ltr"
            value={f.date}
            onChange={(e) => setF({ ...f, date: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          حد ضرر (ریال، اختیاری)
          <input
            className="ctl w-32"
            dir="ltr"
            inputMode="numeric"
            value={f.stop}
            onChange={(e) => setF({ ...f, stop: e.target.value })}
          />
        </label>
        <button className="btn btn-primary">افزودن</button>
      </form>
      <p className="mt-1 text-xs text-muted">
        تعداد، قیمت و مبلغ را اگر نمی‌دانی خالی بگذار: بی‌قیمت، قیمت پایانی روز خرید؛ بی‌تعداد، مبلغ
        تقسیم بر قیمت یا هم‌اندازهٔ بقیهٔ دارایی‌ها. سود کل هم با همین برآورد حساب می‌شود.
      </p>
      {err && <p className="mt-1 text-sm text-down">{err}</p>}
    </section>
  );
}

// -- advice -----------------------------------------------------------------------------------
function AdviceCard({ id, pkey, version }: { id: number; pkey: string; version: number }) {
  const [a, setA] = useState<Advice | null>(null);
  useEffect(() => {
    call<Advice>(`/${id}/advice`, pkey)
      .then(setA)
      .catch(() => setA(null));
  }, [id, pkey, version]);
  if (!a) return null;
  return (
    <section className="card" data-testid="advice">
      <h2 className="font-bold">پیشنهاد: نگه‌داری، جایگزینی، خرید</h2>
      <p className={`mt-1 text-sm ${a.validated ? "text-muted" : "text-down"}`}>
        {a.note} {a.as_of && <>(رتبه‌بندی {jalali(a.as_of)})</>}
      </p>
      {a.holdings.length > 0 && (
        <ul className="mt-2 grid gap-1 text-sm">
          {a.holdings.map((h) => (
            <li key={h.holding_id}>
              <b>{h.symbol}</b>:{" "}
              <span
                className={
                  h.verdict === "sell" || h.verdict === "weak"
                    ? "text-down"
                    : h.verdict === "strong"
                      ? "text-up"
                      : ""
                }
              >
                {h.verdict_fa}
              </span>
              <span className="text-muted"> — {h.reasons.join(" ")}</span>
            </li>
          ))}
        </ul>
      )}
      {a.switches.length > 0 && (
        <>
          <h3 className="mt-3 font-bold">جایگزینی پیشنهادی</h3>
          <ul className="mt-1 grid gap-1 text-sm">
            {a.switches.map((s) => (
              <li key={s.sell.symbol}>
                <b className="text-down">{s.sell.symbol}</b> ←{" "}
                <b className="text-up">{s.buy.symbol}</b>
                <span className="text-muted"> — {s.reason}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {a.buys.length > 0 && (
        <>
          <h3 className="mt-3 font-bold">خرید با نقد آزاد</h3>
          <ul className="mt-1 grid gap-1 text-sm">
            {a.buys.map((b) => (
              <li key={b.instrument_id}>
                <Link
                  href={`/instruments/${b.instrument_id}`}
                  className="font-bold hover:text-accent"
                >
                  {b.symbol}
                </Link>{" "}
                {faNumber(b.shares ?? 0)} سهم ≈ {faToman(b.amount)} تومان (امتیاز{" "}
                {faNumber((b.score ?? 0) * 100)})
              </li>
            ))}
          </ul>
        </>
      )}
      {a.candidates.length > 0 && (
        <p className="mt-3 text-sm text-muted">
          بهترین‌های ناحیهٔ خرید (بیرون از صف): {a.candidates.map((c) => c.symbol).join("، ")}
        </p>
      )}
    </section>
  );
}

// -- forecast ---------------------------------------------------------------------------------
function ForecastCard({ id, pkey, version }: { id: number; pkey: string; version: number }) {
  const [got, setGot] = useState<{ v: number; doc: Forecast } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    call<Forecast>(`/${id}/forecast`, pkey)
      .then((doc) => setGot({ v: version, doc }))
      .catch(() =>
        setGot({ v: version, doc: { available: false, reason: "محاسبه نشد", skipped: [] } }),
      );
  }, [id, pkey, version]);
  const f = got && got.v === version ? got.doc : null;
  if (!f) return <section className="card text-muted">در حال شبیه‌سازی بازده پرتفوی…</section>;
  if (!f.available)
    return <section className="card text-muted">پیش‌بینی بازده: {f.reason}</section>;
  return (
    <section className="card" data-testid="forecast">
      <h2 className="font-bold">پیش‌بینی بازدهٔ پرتفوی</h2>
      <p className="mt-1 text-sm text-muted">
        بازهٔ ۸۰٪ یعنی در ۸ از ۱۰ حالت بازده بین این دو عدد است؛ «پوشش واقعی» همین را روی گذشتهٔ
        همین سبد آزموده (اگر ۰٫۸ نباشد بازه اصلاح شده). نوسان سالانهٔ فعلی{" "}
        {faPercent(f.annual_vol_now ?? 0)}.
      </p>
      <p className="mt-1 rounded-lg bg-warn-soft p-2 text-sm" data-testid="forecast-caveat">
        این کندل‌ها فقط از رفتار گذشتهٔ خودِ نمادها ساخته می‌شوند (نوسان و میانگین بازده قبلی) و
        سیگنال خرید یا فروش نیستند. در بازاری که سال‌هاست بالا رفته، میانهٔ سبز تقریباً برای همه
        سهم‌ها دیده می‌شود. تصمیم را حکم مدل («خرید/نگهداری/فروش» در صفحهٔ نماد) می‌دهد؛ این کندل‌ها
        فقط اندازهٔ ریسک و دامنهٔ نوسان را نشان می‌دهند. اگر حکم و کندل‌ها با هم نمی‌خوانند، به حکم
        مدل و حد ضرر تکیه کنید، نه به سبزیِ کندل.
      </p>
      <ForecastCandles
        title="بازهٔ بازدهٔ پرتفوی در هر افق"
        items={(f.horizons ?? []).map((h) => ({
          key: h.key,
          label: h.label,
          band: Object.keys(h.calibrated).length
            ? { ...h.portfolio, ...h.calibrated }
            : h.portfolio,
          sub: `سود ${faPercent(h.portfolio.p_gain_net, 0)}`,
        }))}
      />
      <div className="mt-2 overflow-x-auto">
        <table className="tbl w-full min-w-[40rem] text-sm">
          <thead>
            <tr>
              <th>افق</th>
              <th>کمینه (۵٪)</th>
              <th>بازهٔ ۸۰٪</th>
              <th>میانه</th>
              <th>بیشینه (۹۵٪)</th>
              <th>شانس سود پس از کارمزد</th>
              <th>پوشش واقعی ۸۰٪ / ۹۰٪</th>
            </tr>
          </thead>
          <tbody>
            {f.horizons?.map((h) => {
              const b = Object.keys(h.calibrated).length
                ? { ...h.portfolio, ...h.calibrated }
                : h.portfolio;
              return (
                <tr
                  key={h.key}
                  className="cursor-pointer"
                  onClick={() => setOpen(open === h.key ? null : h.key)}
                >
                  <td className="font-bold">{h.label}</td>
                  <td className="text-down">{signedPct(b.q05)}</td>
                  <td>
                    {signedPct(b.q10)} تا {signedPct(b.q90)}
                  </td>
                  <td className={signTone(b.q50)}>{signedPct(b.q50)}</td>
                  <td className="text-up">{signedPct(b.q95)}</td>
                  <td>{faPercent(h.portfolio.p_gain_net, 0)}</td>
                  <td className="text-muted">
                    {h.backtest.coverage80 != null
                      ? `${faNumber(h.backtest.coverage80, 2)} / ${faNumber(h.backtest.coverage90 ?? 0, 2)}${h.backtest.reliable ? "" : " (نمونهٔ کم)"}`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {f.horizons
        ?.filter((h) => h.key === open)
        .map((h) => (
          <div key={h.key} className="well mt-2 text-sm">
            <b>{h.label} — هر نماد</b>
            <ForecastCandles
              title={`بازهٔ بازدهٔ هر نماد در ${h.label}`}
              items={h.symbols.map((s) => ({
                key: String(s.instrument_id),
                label: s.symbol,
                band: s,
                sub: `سود ${faPercent(s.p_gain, 0)}`,
              }))}
            />
            <ul className="mt-1 grid gap-1">
              {h.symbols.map((s) => (
                <li key={s.instrument_id}>
                  {s.symbol}: {signedPct(s.q05)} …{" "}
                  <b className={signTone(s.q50)}>{signedPct(s.q50)}</b> … {signedPct(s.q95)}
                  <span className="text-muted"> (شانس سود {faPercent(s.p_gain, 0)})</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-muted">
              ارزش پرتفوی: {faToman(h.value.q05)} تا {faToman(h.value.q95)} تومان (میانه{" "}
              {faToman(h.value.q50)})
            </p>
          </div>
        ))}
      <p className="mt-2 text-xs text-muted">برای دیدن هر نماد روی سطر افق بزن. {f.method}</p>
      {f.skipped.length > 0 && (
        <p className="text-xs text-muted">بدون سابقهٔ کافی: {f.skipped.join("، ")}</p>
      )}
    </section>
  );
}

// -- briefing ---------------------------------------------------------------------------------
function BriefingCard({ id, pkey }: { id: number; pkey: string }) {
  const [b, setB] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    call<Briefing | null>(`/${id}/briefing`, pkey)
      .then(setB)
      .catch(() => null);
  }, [id, pkey]);
  const doc = b?.doc as BriefingDoc | undefined;
  return (
    <section className="card" data-testid="briefing">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold">بازبینی پیش از بازار و ساعتی</h2>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setB(await call<Briefing>(`/${id}/briefing`, pkey, { method: "POST" }).catch(() => b));
            setBusy(false);
          }}
        >
          {busy ? "در حال بازبینی…" : "همین الان بازبینی کن"}
        </button>
      </div>
      <p className="mt-1 text-sm text-muted">
        دو ساعت پیش از گشایش و هر ساعت در جلسه خودکار اجرا می‌شود: اخبار داخلی و خارجی، کدال، دلار و
        طلا و نفت و مس (با اثر اندازه‌گیری‌شده روی هر سهم) و امتیاز مدل.
      </p>
      {doc && (
        <>
          <p className="mt-2 text-sm">
            {new Date(doc.at).toLocaleString("fa-IR")} ·{" "}
            {doc.method === "llm" ? "داوری با هوش مصنوعی" : "داوری با قاعده"} — {doc.market_fa}
          </p>
          <ul className="mt-2 grid gap-2 text-sm">
            {doc.holdings.map((h) => (
              <li key={h.instrument_id} className="well">
                <b>{h.symbol}</b>:{" "}
                <b
                  className={
                    h.action === "exit" || h.action === "reduce"
                      ? "text-down"
                      : h.action === "add"
                        ? "text-up"
                        : ""
                  }
                >
                  {h.action_fa}
                </b>{" "}
                <span className="text-muted">(اطمینان {faNumber(h.confidence * 100)}٪)</span>
                {h.why.length > 0 && <p className="mt-1 text-muted">{h.why.join(" · ")}</p>}
                {h.macro && Math.abs(h.macro.total) >= 0.005 && (
                  <p className={`mt-1 ${signTone(h.macro.total)}`}>
                    فشار دلار/کالا از آخرین معامله (اندازه‌گیری‌شده): {signedPct(h.macro.total)}
                  </p>
                )}
              </li>
            ))}
          </ul>
          {doc.macro && doc.macro.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <b className="text-sm">داخلی و خارجی از آخرین روز</b>
              <table className="tbl mt-1 w-full min-w-[28rem] text-sm" data-testid="macro">
                <thead>
                  <tr>
                    <th>شاخص</th>
                    <th>تاریخ</th>
                    <th>یک روز</th>
                    <th>پنج روز</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.macro.map((m) => (
                    <tr key={m.series}>
                      <td>
                        {m.label_fa}
                        {m.domestic ? "" : " 🌐"}
                      </td>
                      <td className="text-muted">{jalali(m.date)}</td>
                      <td className={signTone(m.change_1)}>{signedPct(m.change_1)}</td>
                      <td className={signTone(m.change_5)}>{signedPct(m.change_5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {doc.foreign && doc.foreign.length > 0 && (
            <div className="mt-3 text-sm">
              <b>خبرهای خارجی اثرگذار</b>
              <ul className="mt-1 grid gap-1" dir="ltr">
                {doc.foreign.map((n) => (
                  <li key={n.url} className={n.iran ? "font-bold" : ""}>
                    <a href={n.url} target="_blank" rel="noreferrer" className="hover:text-accent">
                      {n.title}
                    </a>{" "}
                    <span className="text-xs text-muted">({n.source})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

// -- settings ---------------------------------------------------------------------------------
type Channel = {
  type: string;
  token?: string;
  chat_id?: string | number;
  url?: string;
  label?: string;
};
const TUNABLE: [string, string][] = [
  ["drop_warn_pct", "هشدار افت روزانه (٪)"],
  ["drop_urgent_pct", "فوری افت روزانه (٪)"],
  ["stop_loss_pct", "حد ضرر پیش‌فرض زیر میانگین خرید (٪)"],
  ["volume_surge_x", "جهش حجم (برابر روال)"],
  ["push_min_severity", "کمترین شدت برای پیام (۱ اطلاع، ۲ هشدار، ۳ فوری)"],
];

function SettingsCard({
  p,
  pkey,
  onChange,
}: {
  p: Portfolio;
  pkey: string;
  onChange: (p: Portfolio) => void;
}) {
  const [channels, setChannels] = useState<Channel[]>(p.channels as Channel[]);
  const [cfg, setCfg] = useState<Record<string, string>>(
    Object.fromEntries(TUNABLE.map(([k]) => [k, String(p.settings[k] ?? "")])),
  );
  const [cash, setCash] = useState(String(p.cash / 10));
  const [msg, setMsg] = useState<string | null>(null);

  async function save() {
    setMsg(null);
    const settings = Object.fromEntries(
      Object.entries(cfg)
        .filter(([, v]) => v.trim() !== "")
        .map(([k, v]) => [k, Number(v)]),
    );
    try {
      const np = await call<Portfolio>(`/${p.id}`, pkey, {
        method: "PATCH",
        body: { channels, settings: { ...p.settings, ...settings }, cash: Number(cash) * 10 || 0 },
      });
      onChange(np);
      setChannels(np.channels as Channel[]);
      setMsg("ذخیره شد.");
    } catch (x) {
      setMsg((x as Error).message);
    }
  }

  async function test() {
    const r = await call<{ type: string; ok: boolean; error?: string }[]>(
      `/${p.id}/notify-test`,
      pkey,
      {
        method: "POST",
      },
    ).catch((x: Error) => [{ type: "-", ok: false, error: x.message }]);
    setMsg(r.map((x) => `${x.type}: ${x.ok ? "رسید" : x.error}`).join(" · "));
  }

  const set = (i: number, c: Partial<Channel>) =>
    setChannels(channels.map((x, j) => (j === i ? { ...x, ...c } : x)));

  return (
    <details className="card">
      <summary className="cursor-pointer font-bold">تنظیمات هشدار و پیام‌رسان</summary>
      <p className="mt-2 text-sm text-muted">
        بله یا تلگرام: یک بات بساز (در بله از @botfather)، توکن را این‌جا بگذار، به بات «/start»
        بفرست تا شناسهٔ گفت‌وگو را برگرداند. هشدارهای فوری با دکمه‌های «خارج می‌شوم / نصف / نگه
        می‌دارم» می‌آیند. Apprise: هر آدرس پشتیبانی‌شده، مثلاً ntfy://topic برای اعلان صدادار گوشی
        یا mailto://.
      </p>
      <div className="mt-2 grid gap-2">
        {channels.map((c, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <select
              className="ctl"
              value={c.type}
              onChange={(e) => set(i, { type: e.target.value })}
            >
              <option value="bale">بله</option>
              <option value="telegram">تلگرام</option>
              <option value="apprise">Apprise</option>
            </select>
            {c.type === "apprise" ? (
              <input
                className="ctl"
                dir="ltr"
                placeholder="ntfy://my-topic"
                value={c.url ?? ""}
                onChange={(e) => set(i, { url: e.target.value })}
              />
            ) : (
              <>
                <input
                  className="ctl"
                  dir="ltr"
                  placeholder="token"
                  value={c.token ?? ""}
                  onChange={(e) => set(i, { token: e.target.value })}
                />
                <input
                  className="ctl w-36"
                  dir="ltr"
                  placeholder="chat_id"
                  value={String(c.chat_id ?? "")}
                  onChange={(e) => set(i, { chat_id: e.target.value })}
                />
              </>
            )}
            <button
              type="button"
              className="text-sm text-muted hover:text-down"
              onClick={() => setChannels(channels.filter((_, j) => j !== i))}
            >
              حذف
            </button>
          </div>
        ))}
        <div>
          <button
            type="button"
            className="btn"
            onClick={() => setChannels([...channels, { type: "bale" }])}
          >
            افزودن کانال
          </button>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {TUNABLE.map(([k, label]) => (
          <label key={k} className="grid gap-1 text-sm">
            {label}
            <input
              className="ctl"
              dir="ltr"
              placeholder={String(p.defaults[k] ?? "")}
              value={cfg[k]}
              onChange={(e) => setCfg({ ...cfg, [k]: e.target.value })}
            />
          </label>
        ))}
        <label className="grid gap-1 text-sm">
          نقد آزاد (تومان)
          <input className="ctl" dir="ltr" value={cash} onChange={(e) => setCash(e.target.value)} />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" onClick={() => void save()}>
          ذخیره
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => void test()}
          disabled={!p.channels.length}
        >
          پیام آزمایشی
        </button>
      </div>
      {msg && <p className="mt-2 text-sm">{msg}</p>}
    </details>
  );
}

// -- page -------------------------------------------------------------------------------------
export function PortfolioView({ id }: { id: number }) {
  const saved = useSaved();
  const pkey = saved === null ? undefined : (saved.find((x) => x.id === id)?.key ?? null);
  const [p, setP] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!pkey) return;
    call<Portfolio>(`/${id}`, pkey)
      .then(setP)
      .catch((e: Error) => setError(e.message));
  }, [id, pkey]);

  const changed = useCallback((np: Portfolio) => {
    setP(np);
    setVersion((v) => v + 1);
  }, []);

  if (pkey === undefined) return null;
  if (pkey === null)
    return (
      <p className="card">
        کلید این پرتفوی در این مرورگر نیست. از{" "}
        <Link href="/portfolios" className="text-accent">
          فهرست پرتفوی‌ها
        </Link>{" "}
        آن را وارد کن.
      </p>
    );
  if (error) return <p className="card text-down">{error}</p>;
  if (!p) return <p className="card text-muted">در حال بارگذاری…</p>;
  return (
    <div className="grid gap-4">
      <h1 className="page-title">{p.name}</h1>
      <Summary p={p} />
      <AlertsFeed id={id} pkey={pkey} />
      <Holdings p={p} pkey={pkey} onChange={changed} />
      <MofidCard p={p} pkey={pkey} onChange={changed} />
      <Trades p={p} pkey={pkey} version={version} onChange={changed} />
      <HistoryCard id={id} pkey={pkey} version={version} />
      <HoldingEvents p={p} />
      <BriefingCard id={id} pkey={pkey} />
      <AdviceCard id={id} pkey={pkey} version={version} />
      <ForecastCard id={id} pkey={pkey} version={version} />
      <SettingsCard p={p} pkey={pkey} onChange={changed} />
    </div>
  );
}
