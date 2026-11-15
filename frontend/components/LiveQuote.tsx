"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { LiveQuote as Live } from "@/lib/api";
import { faNumber } from "@/lib/format";
import { Num } from "@/components/Num";

// The browser talks to the API directly (the page itself is server-rendered).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 15_000;
const LIVE_POLL_MS = 1_500; // Mofid pushes every change; the page reads it this often

const SOURCE_FA: Record<string, string> = {
  mofid: "زنده از مفید",
  tsetmc: "از TSETMC، همین الان",
  stored: "آخرین دریافت ذخیره‌شده",
};

const clock = new Intl.DateTimeFormat("fa-IR", {
  timeZone: "Asia/Tehran",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function ageText(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 60) return "چند ثانیه پیش";
  if (seconds < 3600) return `${faNumber(Math.round(seconds / 60))} دقیقه پیش`;
  if (seconds < 86_400) return `${faNumber(Math.round(seconds / 3600))} ساعت پیش`;
  return `${faNumber(Math.round(seconds / 86_400))} روز پیش`;
}

type State = { kind: "loading" } | { kind: "error" } | { kind: "ok"; live: Live };

export function LiveQuote({
  instrumentId,
  pollMs = POLL_MS,
}: {
  instrumentId: number;
  pollMs?: number;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      let next = pollMs;
      try {
        const res = await fetch(`${BASE}/instruments/${instrumentId}/live`, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const live = (await res.json()) as Live;
        if (alive) setState({ kind: "ok", live });
        if (live.source === "mofid" && !live.stale) next = LIVE_POLL_MS;
      } catch {
        if (alive) setState({ kind: "error" });
      }
      if (alive) timer = setTimeout(() => void load(), document.hidden ? pollMs : next);
    };
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [instrumentId, pollMs]);

  return (
    <section className="card" data-testid="live-quote">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold">قیمت لحظه‌ای و عمق بازار</h2>
        {state.kind === "ok" && state.live.available && (
          <span
            className={`text-xs ${state.live.source === "mofid" && !state.live.stale ? "font-bold text-up" : "text-muted"}`}
            data-testid="live-source"
          >
            {state.live.source === "mofid" && !state.live.stale && "● "}
            {SOURCE_FA[state.live.source ?? "stored"] ?? state.live.source}
          </span>
        )}
      </div>
      <Body state={state} />
    </section>
  );
}

function Body({ state }: { state: State }) {
  if (state.kind === "loading") return <p className="text-sm text-muted">در حال دریافت…</p>;
  if (state.kind === "error") {
    return (
      <p className="text-sm text-muted" data-testid="live-error">
        دریافت قیمت لحظه‌ای ممکن نشد. کمی بعد دوباره تلاش می‌شود.
      </p>
    );
  }
  const l = state.live;
  if (!l.available) {
    return (
      <p className="text-sm text-muted" data-testid="live-unavailable">
        {l.message ?? "داده‌ٔ لحظه‌ای برای این نماد ذخیره نشده است."}
      </p>
    );
  }
  const up = (l.change_pct ?? 0) > 0;
  const down = (l.change_pct ?? 0) < 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <div className="text-xs text-muted">آخرین قیمت</div>
          <div className="text-2xl font-extrabold">
            <Num term="last_price" value={l.last_price} kind="price" />
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">تغییر نسبت به دیروز</div>
          <div className={up ? "text-up" : down ? "text-down" : ""}>
            <Num term="change_pct" value={l.change_pct} kind="percent" signed />
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">حجم امروز</div>
          <Num term="cum_volume" value={l.cum_volume} kind="count" />
        </div>
        {l.low_allowed != null && l.high_allowed != null && (
          <div>
            <div className="text-xs text-muted">دامنهٔ مجاز امروز</div>
            <span>
              {faNumber(l.low_allowed)} تا {faNumber(l.high_allowed)}
            </span>
          </div>
        )}
        {l.day_low != null && l.day_high != null && (
          <div>
            <div className="text-xs text-muted">کمترین و بیشترین معامله</div>
            <span>
              {faNumber(l.day_low)} تا {faNumber(l.day_high)}
            </span>
          </div>
        )}
      </div>

      <Queue l={l} />

      {l.book.length > 0 && (
        <table className="w-full text-center text-sm" data-testid="order-book">
          <caption className="mb-1 text-start text-xs text-muted">
            <Link href="/glossary/order_book" className="underline">
              صف‌های خرید و فروش
            </Link>
          </caption>
          <thead>
            <tr>
              <th>تعداد</th>
              <th>حجم</th>
              <th>قیمت خرید</th>
              <th>قیمت فروش</th>
              <th>حجم</th>
              <th>تعداد</th>
            </tr>
          </thead>
          <tbody>
            {l.book.map((r) => (
              <tr key={r.row} style={depthStyle(r, maxVol(l.book))}>
                <td>
                  <Num term="order_book" value={r.bid_count} kind="count" />
                </td>
                <td>
                  <Num term="order_book" value={r.bid_volume} kind="count" />
                </td>
                <td className="text-up">
                  <Num term="order_book" value={r.bid_price} kind="price" />
                </td>
                <td className="text-down">
                  <Num term="order_book" value={r.ask_price} kind="price" />
                </td>
                <td>
                  <Num term="order_book" value={r.ask_volume} kind="count" />
                </td>
                <td>
                  <Num term="order_book" value={r.ask_count} kind="count" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {l.book.length > 0 && <Pressure book={l.book} />}
      {l.flow && <Flow f={l.flow} />}

      <p
        className={`text-xs ${l.stale ? "font-bold text-down" : "text-muted"}`}
        data-testid="live-age"
      >
        آخرین به‌روزرسانی: {l.as_of ? clock.format(new Date(l.as_of)) : "—"} (
        {ageText(l.age_seconds)})
        {l.stale && " — داده قدیمی است (خارج از ساعت معاملات یا قطع دریافت)."}
      </p>
    </div>
  );
}

type Level = Live["book"][number];

const maxVol = (book: Level[]) => Math.max(1, ...book.flatMap((r) => [r.bid_volume, r.ask_volume]));

// a faint bar behind each row: green from the start for buyers, red from the end for sellers
function depthStyle(r: Level, max: number): React.CSSProperties {
  const b = Math.round((r.bid_volume / max) * 50);
  const a = Math.round((r.ask_volume / max) * 50);
  return {
    backgroundImage: `linear-gradient(to left, color-mix(in srgb, var(--color-up, #16a34a) 14%, transparent) ${b}%, transparent ${b}%, transparent ${100 - a}%, color-mix(in srgb, var(--color-down, #dc2626) 14%, transparent) ${100 - a}%)`,
  };
}

function Queue({ l }: { l: Live }) {
  const top = l.book[0];
  if (!top || l.high_allowed == null || l.low_allowed == null) return null;
  const buyQueue = top.bid_price >= l.high_allowed && !top.ask_volume;
  const sellQueue = top.ask_price > 0 && top.ask_price <= l.low_allowed && !top.bid_volume;
  if (!buyQueue && !sellQueue) return null;
  const vol = buyQueue ? top.bid_volume : top.ask_volume;
  const n = buyQueue ? top.bid_count : top.ask_count;
  const traded = l.cum_volume ?? 0;
  return (
    <p
      className={`rounded-lg px-3 py-2 text-sm font-bold ${buyQueue ? "bg-up/10 text-up" : "bg-down/10 text-down"}`}
      data-testid="live-queue"
    >
      {buyQueue ? "صف خرید" : "صف فروش"}: {faNumber(vol)} سهم از {faNumber(n)} سفارش
      {traded > 0 &&
        (vol >= traded
          ? ` (بیشتر از کل معاملات امروز؛ صف سنگین است)`
          : ` (حدود ${faNumber(Math.round((vol / traded) * 100))}٪ معاملات امروز)`)}
    </p>
  );
}

function Pressure({ book }: { book: Level[] }) {
  const bid = book.reduce((t, r) => t + r.bid_volume, 0);
  const ask = book.reduce((t, r) => t + r.ask_volume, 0);
  if (!bid && !ask) return null;
  const share = bid / (bid + ask);
  return (
    <div className="text-xs" data-testid="live-pressure">
      <div className="mb-1 flex justify-between text-muted">
        <span>تقاضا در ۵ ردیف: {faNumber(bid)}</span>
        <span>عرضه در ۵ ردیف: {faNumber(ask)}</span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-down/40" aria-hidden>
        <div className="bg-up" style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  );
}

function Flow({ f }: { f: NonNullable<Live["flow"]> }) {
  const bp = f.buy_volume_person ?? 0;
  const sp = f.sell_volume_person ?? 0;
  const bc = f.buy_count_person ?? 0;
  const sc = f.sell_count_person ?? 0;
  // buying power of individuals: average buy per buyer over average sale per seller
  const power = bc && sc && sp ? bp / bc / (sp / sc) : null;
  const net = bp - sp;
  return (
    <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" data-testid="live-flow">
      <div>
        <div className="text-xs text-muted">خرید حقیقی</div>
        {faNumber(bp)}
      </div>
      <div>
        <div className="text-xs text-muted">فروش حقیقی</div>
        {faNumber(sp)}
      </div>
      <div>
        <div className="text-xs text-muted">ورود پول حقیقی (حجم)</div>
        <span className={net > 0 ? "text-up" : net < 0 ? "text-down" : ""}>
          {net > 0 ? "+" : ""}
          {faNumber(net)}
        </span>
      </div>
      <div>
        <div className="text-xs text-muted">قدرت خریدار حقیقی</div>
        <span className={power && power > 1 ? "text-up" : power && power < 1 ? "text-down" : ""}>
          {power
            ? power > 1.05
              ? "خریداران قوی‌ترند"
              : power < 0.95
                ? "فروشندگان قوی‌ترند"
                : "برابر"
            : "—"}
        </span>
      </div>
    </div>
  );
}
