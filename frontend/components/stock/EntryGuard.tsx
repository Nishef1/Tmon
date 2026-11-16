"use client";

import { useEffect, useState } from "react";
import { faNumber, faPercent, faPrice } from "@/lib/format";
import { signTone } from "@/lib/ui";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 20_000;

type Flag = { key: string; text: string };
type Review = {
  paid: number;
  premium: number | null;
  range_pos: number | null;
  pnl_last: number | null;
  grade: "good" | "fair" | "poor";
  flags: Flag[];
};
type Guard = {
  state: "ok" | "wait" | "avoid" | "unknown";
  headline: string;
  reasons: string[];
  price?: number;
  premium?: number;
  range_pos?: number | null;
  net_edge?: number | null;
  edge_left?: number | null;
  max_price?: number | null;
  gap?: number | null;
};
type Step = {
  fill_prob: number;
  day_fill_prob: number;
  price: number;
  vs_now: number;
  vs_ref: number;
  touched_today: boolean;
  ev: number | null;
};
type Plan =
  | { available: false; message?: string }
  | {
      available: true;
      mode: "today" | "next";
      reference: number;
      now: number;
      headline: string;
      ladder: Step[];
      recommended: Step | null;
      market_now: { price: number; ev: number } | null;
      basis: { market_days: number; own_days: number; gap_bucket: string | null };
      notes: string[];
    };
type Entry =
  | { available: false; message?: string }
  | {
      available: true;
      live: boolean;
      verdict: "buy" | "hold" | "sell" | null;
      bar: { last: number | null; close: number | null; yesterday: number | null };
      guard: Guard;
      plan?: Plan;
      review: Review | null;
    };

const TONE: Record<Guard["state"], string> = {
  ok: "text-up",
  wait: "text-warn",
  avoid: "text-down",
  unknown: "text-muted",
};
const MARK: Record<Guard["state"], string> = {
  ok: "مناسب",
  wait: "صبر",
  avoid: "نخرید",
  unknown: "نامعلوم",
};
const GRADE: Record<Review["grade"], string> = {
  good: "ورود خوب",
  fair: "ورود متوسط",
  poor: "ورود ضعیف",
};

/** Is now a sensible moment and price to buy? Read from today's live range, never from a stored
 *  copy; the price the buyer would pay is compared with what the model's score assumed (the
 *  previous official close). */
export function EntryGuard({ instrumentId }: { instrumentId: number }) {
  const [entry, setEntry] = useState<Entry | null>(null);
  const [failed, setFailed] = useState(false);
  const [paid, setPaid] = useState("");
  const paidNum = Number(paid.replace(/[^\d]/g, ""));

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const q = paidNum > 0 ? `?paid=${paidNum}` : "";
        const res = await fetch(`${BASE}/instruments/${instrumentId}/entry${q}`, {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as Entry;
        if (alive) {
          setEntry(data);
          setFailed(false);
        }
      } catch {
        if (alive) setFailed(true);
      }
      if (alive) timer = setTimeout(() => void load(), POLL_MS);
    };
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [instrumentId, paidNum]);

  if (failed && !entry) return null;
  if (!entry || !entry.available) return null;
  const g = entry.guard;
  const rev = entry.review;
  return (
    <section className="card" data-testid="entry-guard">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold">ورود: زمان و قیمت</h2>
        <span className={`text-sm font-bold ${TONE[g.state]}`}>
          {MARK[g.state]}
          {!entry.live && <span className="font-normal text-muted"> (قیمت زنده نبود)</span>}
        </span>
      </div>
      <p className={`mt-1 font-bold ${TONE[g.state]}`}>{g.headline}</p>
      {g.reasons.length > 0 && (
        <ul className="mt-1 list-disc pr-5 text-sm">
          {g.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        {g.price != null && (
          <div>
            <dt className="text-muted">آخرین معامله</dt>
            <dd>{faPrice(g.price)}</dd>
          </div>
        )}
        {entry.bar.close != null && (
          <div>
            <dt className="text-muted">پایانی (میانگین وزنی)</dt>
            <dd>{faPrice(entry.bar.close)}</dd>
          </div>
        )}
        {g.premium != null && (
          <div>
            <dt className="text-muted">بالاتر از پایانی دیروز</dt>
            <dd>{faPercent(g.premium, 1, true)}</dd>
          </div>
        )}
        {g.range_pos != null && (
          <div>
            <dt className="text-muted">جای قیمت در بازهٔ امروز</dt>
            <dd>{faPercent(g.range_pos, 0)} از پایین</dd>
          </div>
        )}
        {g.max_price != null && (
          <div>
            <dt className="text-muted">بالاترین قیمت منطقی خرید</dt>
            <dd>{faPrice(g.max_price)}</dd>
          </div>
        )}
        {g.edge_left != null && (
          <div>
            <dt className="text-muted">برتری باقی‌مانده پس از کارمزد</dt>
            <dd>{faPercent(g.edge_left, 1, true)}</dd>
          </div>
        )}
      </dl>
      {entry.plan?.available && <PlanBlock plan={entry.plan} />}
      <p className="mt-2 text-xs text-muted">
        امتیاز مدل از پایانی دیروز شروع می‌شود؛ هر ریالی که بالاتر از آن بخرید از سود پیش‌بینی‌شده
        کم می‌شود. برای خرید، سفارش حدی در قیمت بالا نبرید و دقایق اول بازگشایی را کنار بگذارید.
      </p>
      <label className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span>اگر امروز با این قیمت خریده‌ام (ریال):</span>
        <input
          inputMode="numeric"
          className="w-32 rounded border border-line bg-transparent px-2 py-1"
          value={paid}
          onChange={(e) => setPaid(e.target.value)}
          aria-label="قیمت خرید من"
        />
      </label>
      {rev && (
        <div className="mt-2 text-sm" data-testid="entry-review">
          <b>
            {GRADE[rev.grade]}
            {rev.pnl_last != null && (
              <> — اکنون {faPercent(rev.pnl_last, 1, true)} با آخرین معامله</>
            )}
          </b>
          {rev.flags.length > 0 && (
            <ul className="mt-1 list-disc pr-5">
              {rev.flags.map((f) => (
                <li key={f.key}>{f.text}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

/** The cheapest entry the history supports: prices to leave a limit order at, how often the
 *  day's low reached each one, and the one worth most after fees. Independent of the candle's
 *  colour; an order that is not filled by the close is cancelled, not chased. */
function PlanBlock({ plan }: { plan: Extract<Plan, { available: true }> }) {
  const best = plan.recommended;
  return (
    <div className="mt-3 rounded-lg bg-surface-2 p-3" data-testid="entry-plan">
      <h3 className="font-bold">
        بهترین ورود {plan.mode === "next" ? "(برای جلسهٔ بعد)" : "(امروز)"}
      </h3>
      <p className={`mt-1 text-sm font-bold ${best ? "text-up" : "text-muted"}`}>{plan.headline}</p>
      {plan.ladder.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="tbl w-full min-w-[22rem] text-sm">
            <thead>
              <tr>
                <th>قیمت سفارش حدی</th>
                <th>ارزان‌تر از {plan.mode === "next" ? "پایانی" : "قیمت فعلی"}</th>
                <th>شانس پرشدن</th>
                <th>ارزش مورد انتظار پس از کارمزد</th>
              </tr>
            </thead>
            <tbody>
              {plan.ladder.map((st) => (
                <tr key={st.price} className={best?.price === st.price ? "font-bold" : ""}>
                  <td>
                    {faPrice(st.price)}
                    {best?.price === st.price && <span className="text-up"> ← پیشنهاد</span>}
                    {st.touched_today && <span className="text-muted"> (امروز لمس شده)</span>}
                  </td>
                  <td>{faPercent(-st.vs_now, 1)}</td>
                  <td>{faPercent(st.fill_prob, 0)}</td>
                  <td className={st.ev != null ? signTone(st.ev) : "text-muted"}>
                    {st.ev == null ? "—" : faPercent(st.ev, 2, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="mt-2 list-disc pr-5 text-xs text-muted">
        {plan.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
        <li>
          مبنا: {faNumber(plan.basis.market_days)} روز مشابه بازار
          {plan.basis.own_days >= 25 ? ` و ${faNumber(plan.basis.own_days)} روز خودِ این نماد` : ""}
          {plan.basis.gap_bucket ? ` (بازگشایی: ${plan.basis.gap_bucket})` : ""}.
        </li>
      </ul>
    </div>
  );
}
