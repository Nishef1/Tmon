"use client";

import { useEffect, useState } from "react";
import { faNumber, faPercent, faPrice, faToman, jalali } from "@/lib/format";
import {
  call,
  type HistoryDoc,
  type MofidStatus,
  type Portfolio,
  type Trade,
} from "@/lib/portfolio";
import { signedPct, signTone } from "@/lib/ui";

const toNum = (s: string) => {
  const v = Number(
    s.replace(/[,٬\s]/g, "").replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))),
  );
  return s.trim() && Number.isFinite(v) && v > 0 ? v : null;
};

const EVENT_FA: Record<string, string> = {
  bonus: "افزایش سرمایه از اندوخته",
  rights: "افزایش سرمایه با آورده",
  dividend: "سود نقدی",
  split: "تجزیهٔ سهم",
  adjust: "تعدیل قیمت",
};

function warningFa(w: Record<string, unknown>): string {
  const pct = (x: unknown) => faPercent(Number(x ?? 0), 0);
  switch (w.kind) {
    case "concentration":
      return `${String(w.symbol)} ${pct(w.weight)} پرتفوی است؛ تمرکز روی یک نماد زیاد است.`;
    case "sector_concentration":
      return `صنعت «${String(w.sector)}» ${pct(w.weight)} پرتفوی است.`;
    case "stale_price":
      return `آخرین قیمت ${String(w.symbol)} مال ${jalali(String(w.close_date))} است (نماد معامله نشده یا بسته است).`;
    case "price_missing":
      return `برای ${String(w.symbol)} هنوز قیمتی نداریم؛ با بهای خرید حساب شده.`;
    default:
      return String(w.kind);
  }
}

// -- summary ----------------------------------------------------------------------------------
export function Summary({ p }: { p: Portfolio }) {
  const up = p.total_pnl >= 0;
  const stat = (label: string, value: React.ReactNode, cls = "") => (
    <div className="well">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-bold ${cls}`}>{value}</div>
    </div>
  );
  return (
    <section className="card" data-testid="summary">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold">وضعیت کلی</h2>
        {p.as_of && <span className="text-xs text-muted">قیمت‌ها تا {jalali(p.as_of)}</span>}
      </div>
      <p className="mt-2 text-lg">
        پرتفوی <b className={up ? "text-up" : "text-down"}>{up ? "در سود" : "در زیان"}</b> است:{" "}
        <b className={signTone(p.total_pnl)}>
          {faToman(p.total_pnl)} تومان ({signedPct(p.total_pnl_pct)})
        </b>
      </p>
      <p className="text-xs text-muted">
        سود کل = سود باز (پس از کارمزد و مالیات فروش) + سود فروش‌های انجام‌شده + سود نقدی، نسبت به
        همهٔ پولی که وارد خرید شده.
      </p>
      {p.estimated && (
        <p className="mt-1 text-sm text-down">
          تعداد یا قیمت بعضی خریدها وارد نشده و برآورد شده است؛ عدد کل تقریبی است.
        </p>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {stat("ارزش کل (سهام + نقد)", `${faToman(p.total_value)} تومان`)}
        {stat("ارزش سهام اگر الان فروخته شود", `${faToman(p.liquidation_value)} تومان`)}
        {stat("نقد", `${faToman(p.cash)} تومان`)}
        {stat("بهای تمام‌شدهٔ دارایی‌ها", `${faToman(p.cost)} تومان`)}
        {stat("سود باز", `${faToman(p.pnl)} (${signedPct(p.pnl_pct)})`, signTone(p.pnl))}
        {stat("سود فروش‌ها", `${faToman(p.realized)} تومان`, signTone(p.realized))}
        {stat("سود نقدی دریافتی", `${faToman(p.dividends)} تومان`, signTone(p.dividends))}
        {stat("کارمزد پرداختی", `${faToman(p.fees)} تومان`)}
      </div>
      {p.warnings.length > 0 && (
        <ul className="mt-3 grid gap-1 text-sm text-down" data-testid="warnings">
          {p.warnings.map((w, i) => (
            <li key={i}>⚠ {warningFa(w)}</li>
          ))}
        </ul>
      )}
      {p.sector_weights.length > 0 && (
        <div className="mt-3">
          <b className="text-sm">وزن صنعت‌ها</b>
          <ul className="mt-1 grid gap-1 text-sm">
            {p.sector_weights.map((s) => {
              const w = Number(s.weight ?? 0);
              return (
                <li key={String(s.sector)} className="flex items-center gap-2">
                  <span className="w-40 truncate">{String(s.sector)}</span>
                  <span className="h-2 flex-1 rounded bg-[var(--line)]">
                    <span
                      className="block h-2 rounded bg-[var(--accent)]"
                      style={{ width: `${Math.min(100, w * 100)}%` }}
                    />
                  </span>
                  <span className="w-12 text-left">{faPercent(w, 0)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

// -- holding details --------------------------------------------------------------------------
export function HoldingEvents({ p }: { p: Portfolio }) {
  const rows = p.holdings.flatMap((h) =>
    (h.events as { date: string; kind: string; shares: number; amount: number }[]).map((e) => ({
      ...e,
      symbol: h.symbol,
    })),
  );
  if (!rows.length && !p.closed.length) return null;
  return (
    <section className="card text-sm">
      {rows.length > 0 && (
        <>
          <h2 className="font-bold">رویدادهای شرکتی روی دارایی‌ها</h2>
          <p className="mt-1 text-muted">
            از تعدیل‌های قیمت و تغییر تعداد سهام بازار پیدا شده و در تعداد، بهای تمام‌شده و سود حساب
            شده است.
          </p>
          <ul className="mt-2 grid gap-1">
            {rows.map((e, i) => (
              <li key={i}>
                {jalali(e.date)} · <b>{e.symbol}</b>: {EVENT_FA[e.kind] ?? e.kind}
                {e.shares > 0 && <> (+{faNumber(e.shares)} سهم)</>}
                {e.amount > 0 && (
                  <>
                    {" "}
                    · {e.kind === "dividend" ? "دریافتی" : "پرداختی"} {faToman(e.amount)} تومان
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {p.closed.length > 0 && (
        <>
          <h2 className="mt-3 font-bold">نمادهای فروخته‌شده</h2>
          <ul className="mt-1 grid gap-1">
            {p.closed.map((c) => (
              <li key={String(c.instrument_id)}>
                <b>{String(c.symbol)}</b>: سود فروش{" "}
                <span className={signTone(Number(c.realized))}>
                  {faToman(Number(c.realized))} تومان
                </span>
                {Number(c.dividends) > 0 && <> · سود نقدی {faToman(Number(c.dividends))} تومان</>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// -- Mofid ------------------------------------------------------------------------------------
/** The API stores UTC without a zone mark. */
const utc = (s: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
const fa = (s: string) =>
  utc(s).toLocaleString("fa-IR", {
    timeZone: "Asia/Tehran",
    dateStyle: "short",
    timeStyle: "short",
  });

/** Top of the page: the Mofid copy can no longer refresh, so the numbers below are old. */
export function MofidBanner({ s }: { s: MofidStatus | null }) {
  if (!s?.stale) return null;
  return (
    <div role="alert" className="card border-2 border-down" data-testid="mofid-stale">
      <p className="font-bold text-down">اتصال به مفید قطع است</p>
      <p className="mt-1 text-sm">
        {s.message ?? "ورود به مفید تمام شده است"}.{" "}
        {s.last_sync_at
          ? `دارایی‌ها و نقد این صفحه همان آخرین دریافت در ${fa(s.last_sync_at)} است و خرید و فروش بعد از آن را نشان نمی‌دهد.`
          : "هنوز چیزی از مفید دریافت نشده است."}
      </p>
      <p className="mt-1 text-sm text-muted">
        برای وصل دوباره، روی رایانهٔ خانه در بخش «اتصال به کارگزاری مفید» دکمهٔ اتصال را بزن.
      </p>
    </div>
  );
}

export function MofidCard({
  p,
  pkey,
  onChange,
  onStatus,
}: {
  p: Portfolio;
  pkey: string;
  onChange: (p: Portfolio) => void;
  onStatus?: (s: MofidStatus) => void;
}) {
  const [s, setS] = useState<MofidStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    let alive = true;
    let wasBusy = false;
    const tick = async () => {
      const st = await call<MofidStatus>(`/${p.id}/mofid`, pkey).catch(() => null);
      if (!alive || !st) return;
      setS(st);
      onStatus?.(st);
      if (wasBusy && !st.busy && st.status === "linked") {
        onChange(await call<Portfolio>(`/${p.id}`, pkey));
      }
      wasBusy = st.busy;
    };
    void tick();
    const t = setInterval(() => void tick(), 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [p.id, pkey, onChange, onStatus]);

  async function connect() {
    setMsg(null);
    setS(await call<MofidStatus>(`/${p.id}/mofid/connect`, pkey, { method: "POST" }));
  }
  async function sync() {
    setMsg(null);
    setSyncing(true);
    try {
      onChange(await call<Portfolio>(`/${p.id}/mofid/sync`, pkey, { method: "POST" }));
      setMsg("از مفید به‌روز شد.");
      setS(await call<MofidStatus>(`/${p.id}/mofid`, pkey));
    } catch (x) {
      setMsg((x as Error).message);
    }
    setSyncing(false);
  }
  async function unlink() {
    await call(`/${p.id}/mofid`, pkey, { method: "DELETE" });
    setS(await call<MofidStatus>(`/${p.id}/mofid`, pkey));
  }

  const linked = s?.linked;
  const r = s?.last_result;
  return (
    <section className="card" data-testid="mofid">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold">اتصال به کارگزاری مفید (ایزی‌تریدر)</h2>
        <div className="flex flex-wrap gap-2">
          {linked ? (
            <>
              <button
                type="button"
                className="btn btn-primary"
                disabled={syncing || s?.busy}
                onClick={() => void sync()}
              >
                {syncing ? "در حال دریافت…" : "به‌روزرسانی از مفید"}
              </button>
              <button type="button" className="btn" onClick={() => void unlink()}>
                قطع اتصال
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={s?.busy}
              onClick={() => void connect()}
            >
              {s?.busy ? "منتظر ورود…" : "اتصال به مفید"}
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-sm text-muted">
        با زدن «اتصال» کروم روی همین رایانه باز می‌شود و خودت در سایت مفید وارد می‌شوی؛ Tmon رمز را
        نمی‌بیند و فقط دسترسی‌ای را که سایت مفید پس از ورود می‌دهد نگه می‌دارد. دارایی‌ها و قدرت
        خرید هر ساعت در جلسهٔ بازار خودکار به‌روز می‌شوند، تا وقتی ورود به مفید برقرار است. هر ورود
        حدود ۱۲ ساعت می‌ماند و رایانهٔ خانه هر صبح پیش از بازار آن را تازه می‌کند؛ اگر قطع شود، بالای
        صفحه و در پیام‌رسان خبر می‌دهد.
      </p>
      {s?.busy && s.status === "login" && (
        <p className="mt-2 text-sm font-bold">پنجرهٔ کروم باز شد؛ در آن وارد حساب مفید شو.</p>
      )}
      {s?.status === "error" && s.message && <p className="mt-2 text-sm text-down">{s.message}</p>}
      {linked && s?.last_sync_at && (
        <p className="mt-2 text-sm">
          آخرین دریافت: {fa(s.last_sync_at)}
          {r && (
            <>
              {" "}
              · {faNumber(r.positions.length)} نماد · قدرت خرید {faToman(r.cash)} تومان
              {r.unknown.length > 0 && (
                <span className="text-down"> · ناشناخته: {r.unknown.join("، ")}</span>
              )}
            </>
          )}
        </p>
      )}
      {linked && r && r.positions.some((x) => x.isin) && (
        <MofidCosts p={p} pkey={pkey} positions={r.positions} onChange={onChange} />
      )}
      {msg && <p className="mt-1 text-sm">{msg}</p>}
    </section>
  );
}

type MofidPosition = NonNullable<MofidStatus["last_result"]>["positions"][number];

function MofidCosts({
  p,
  pkey,
  positions,
  onChange,
}: {
  p: Portfolio;
  pkey: string;
  positions: MofidPosition[];
  onChange: (p: Portfolio) => void;
}) {
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);

  async function save(isin: string, toman: string) {
    setErr(null);
    const n = toNum(toman);
    try {
      onChange(
        await call<Portfolio>(`/${p.id}/mofid/cost`, pkey, {
          method: "PUT",
          body: JSON.stringify({ isin, amount: n ? n * 10 : null }),
        }),
      );
      setEdit((e) => ({ ...e, [isin]: "" }));
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  return (
    <div className="mt-3 border-t border-line pt-3">
      <h3 className="text-sm font-bold">بهای خرید دارایی‌های مفید</h3>
      <p className="mt-1 text-xs text-muted">
        اگر میانگین خرید مفید درست نیست (مثلاً پس از تجزیهٔ سهام)، کل مبلغی را که برای این دارایی
        پرداخته‌ای بنویس؛ از این به بعد همین در حساب سود به کار می‌رود.
      </p>
      <ul className="mt-2 space-y-2">
        {positions
          .filter((x) => x.isin)
          .map((x) => {
            const isin = x.isin as string;
            return (
              <li key={isin} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-bold">{x.symbol}</span>
                <span>{faNumber(x.shares)} واحد</span>
                {x.cost_source === "owner" && x.owner_cost ? (
                  <span>بهای خرید: {faToman(x.owner_cost)} تومان (وارد شده توسط تو)</span>
                ) : x.cost_source === "doubtful" ? (
                  <span className="text-down">
                    میانگین مفید ({faNumber(Math.round(x.mofid_avg_price ?? 0))} ریال) با قیمت‌های
                    واقعی جور نیست و کنار گذاشته شد؛ تا بهای خرید را ننویسی، سود این دارایی صفر
                    برآورد می‌شود.
                  </span>
                ) : (
                  <span className="text-muted">
                    میانگین مفید: {faNumber(Math.round(x.avg_price ?? 0))} ریال
                  </span>
                )}
                <input
                  className="ctl w-44"
                  inputMode="numeric"
                  placeholder="کل مبلغ خرید (تومان)"
                  aria-label={`کل مبلغ خرید ${x.symbol} به تومان`}
                  value={edit[isin] ?? ""}
                  onChange={(e) => setEdit((s) => ({ ...s, [isin]: e.target.value }))}
                />
                <button
                  type="button"
                  className="btn"
                  disabled={!(edit[isin] ?? "").trim()}
                  onClick={() => void save(isin, edit[isin] ?? "")}
                >
                  ثبت
                </button>
                {x.cost_source === "owner" && (
                  <button type="button" className="btn" onClick={() => void save(isin, "")}>
                    برگشت به عدد مفید
                  </button>
                )}
              </li>
            );
          })}
      </ul>
      {err && <p className="mt-1 text-sm text-down">{err}</p>}
    </div>
  );
}

// -- trades -----------------------------------------------------------------------------------
const SOURCE_FA: Record<string, string> = {
  manual: "دستی",
  mofid: "مفید",
  legacy: "اولیه",
  import: "ورودی",
};

export function Trades({
  p,
  pkey,
  version,
  onChange,
}: {
  p: Portfolio;
  pkey: string;
  version: number;
  onChange: (p: Portfolio) => void;
}) {
  const [rows, setRows] = useState<Trade[]>([]);
  const [f, setF] = useState({
    side: "buy",
    symbol: "",
    shares: "",
    price: "",
    amount: "",
    date: "",
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    call<Trade[]>(`/${p.id}/trades`, pkey)
      .then(setRows)
      .catch(() => setRows([]));
  }, [p.id, pkey, version]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const amount = toNum(f.amount);
    try {
      onChange(
        await call<Portfolio>(`/${p.id}/trades`, pkey, {
          method: "POST",
          body: {
            side: f.side,
            symbol: f.symbol.trim(),
            shares: toNum(f.shares),
            price: toNum(f.price),
            amount: amount ? amount * 10 : null,
            date: f.date || null,
          },
        }),
      );
      setF({ ...f, symbol: "", shares: "", price: "", amount: "" });
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  async function remove(tid: number) {
    onChange(await call<Portfolio>(`/${p.id}/trades/${tid}`, pkey, { method: "DELETE" }));
  }

  return (
    <details className="card" data-testid="trades">
      <summary className="cursor-pointer font-bold">
        دفتر معاملات ({faNumber(rows.length)} ردیف) — ثبت خرید و فروش
      </summary>
      <p className="mt-2 text-sm text-muted">
        هر خرید یا فروش یک ردیف است؛ دارایی، میانگین، سود فروش و نقد از همین ردیف‌ها ساخته می‌شود.
        تعداد، قیمت و مبلغ هر کدام اختیاری است: بی‌قیمت، قیمت پایانی آن روز؛ بی‌تعداد، مبلغ تقسیم بر
        قیمت (یا اندازهٔ میانگین خریدهای دیگر) گذاشته می‌شود. فروش بی‌تعداد یعنی همه.
      </p>
      <form onSubmit={add} className="mt-2 flex flex-wrap items-end gap-2">
        <select
          className="ctl"
          value={f.side}
          onChange={(e) => setF({ ...f, side: e.target.value })}
        >
          <option value="buy">خرید</option>
          <option value="sell">فروش</option>
        </select>
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
          تعداد
          <input
            className="ctl w-28"
            dir="ltr"
            inputMode="numeric"
            value={f.shares}
            onChange={(e) => setF({ ...f, shares: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          قیمت (ریال)
          <input
            className="ctl w-28"
            dir="ltr"
            inputMode="numeric"
            value={f.price}
            onChange={(e) => setF({ ...f, price: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          یا مبلغ (تومان)
          <input
            className="ctl w-32"
            dir="ltr"
            inputMode="numeric"
            value={f.amount}
            onChange={(e) => setF({ ...f, amount: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          تاریخ (میلادی)
          <input
            className="ctl"
            type="date"
            dir="ltr"
            value={f.date}
            onChange={(e) => setF({ ...f, date: e.target.value })}
          />
        </label>
        <button className="btn btn-primary">ثبت</button>
      </form>
      {err && <p className="mt-1 text-sm text-down">{err}</p>}
      {rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="tbl w-full min-w-[40rem] text-sm">
            <thead>
              <tr>
                <th>تاریخ</th>
                <th>نوع</th>
                <th>نماد</th>
                <th>تعداد</th>
                <th>قیمت (ریال)</th>
                <th>اثر روی نقد (تومان)</th>
                <th>منبع</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>{jalali(t.date)}</td>
                  <td className={t.side === "buy" ? "text-up" : "text-down"}>
                    {t.side === "buy" ? "خرید" : "فروش"}
                  </td>
                  <td className="font-bold">{t.symbol}</td>
                  <td>
                    {t.shares != null ? faNumber(t.shares) : t.side === "sell" ? "همه" : "برآوردی"}
                  </td>
                  <td>{t.price != null ? faPrice(t.price) : "پایانی روز"}</td>
                  <td className={signTone(t.cash_delta)}>
                    {t.cash_delta ? faToman(t.cash_delta) : "—"}
                  </td>
                  <td className="text-muted">{SOURCE_FA[t.source] ?? t.source}</td>
                  <td>
                    <button
                      type="button"
                      className="text-muted hover:text-down"
                      onClick={() => void remove(t.id)}
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
    </details>
  );
}

// -- history ----------------------------------------------------------------------------------
export function HistoryCard({ id, pkey, version }: { id: number; pkey: string; version: number }) {
  const [h, setH] = useState<HistoryDoc | null>(null);
  useEffect(() => {
    call<HistoryDoc>(`/${id}/history`, pkey)
      .then(setH)
      .catch(() => setH(null));
  }, [id, pkey, version]);
  if (!h || h.points.length < 2) return null;
  const W = 640;
  const H = 180;
  const pts = h.points;
  const vals = pts.flatMap((x) => [x.return, x.index_return ?? x.return]);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const xy = (i: number, v: number) =>
    `${((i / (pts.length - 1)) * W).toFixed(1)},${(H - ((v - lo) / span) * H).toFixed(1)}`;
  const line = (get: (x: (typeof pts)[number]) => number | null) =>
    pts
      .map((x, i) => [i, get(x)] as const)
      .filter(([, v]) => v != null)
      .map(([i, v]) => xy(i, v as number))
      .join(" ");
  const zero = H - ((0 - lo) / span) * H;
  return (
    <section className="card" data-testid="history">
      <h2 className="font-bold">بازده پرتفوی در برابر شاخص کل</h2>
      <p className="mt-1 text-sm">
        از {jalali(pts[0].date)}: پرتفوی <b className={signTone(h.return)}>{signedPct(h.return)}</b>
        {h.index_return != null && (
          <>
            {" "}
            · شاخص کل <b className={signTone(h.index_return)}>{signedPct(h.index_return)}</b>
          </>
        )}
      </p>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="mt-2 h-44 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="نمودار بازده پرتفوی و شاخص کل"
      >
        <line x1="0" x2={W} y1={zero} y2={zero} stroke="var(--line)" strokeDasharray="4 4" />
        <polyline
          points={line((x) => x.index_return)}
          fill="none"
          stroke="var(--muted)"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
        <polyline
          points={line((x) => x.return)}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <p className="text-xs text-muted">
        <span className="text-accent">━</span> پرتفوی (با سود فروش و نقدی، نسبت به پول واردشده) ·{" "}
        <span>━</span> شاخص کل در همان روزها
      </p>
    </section>
  );
}
