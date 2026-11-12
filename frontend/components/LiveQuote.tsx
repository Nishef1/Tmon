"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { LiveQuote as Live } from "@/lib/api";
import { faNumber } from "@/lib/format";
import { Num } from "@/components/Num";

// The browser talks to the API directly (the page itself is server-rendered).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 15_000;

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
    const load = async () => {
      try {
        const res = await fetch(`${BASE}/instruments/${instrumentId}/live`, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const live = (await res.json()) as Live;
        if (alive) setState({ kind: "ok", live });
      } catch {
        if (alive) setState({ kind: "error" });
      }
    };
    void load();
    const timer = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [instrumentId, pollMs]);

  return (
    <section className="card" data-testid="live-quote">
      <h2 className="mb-2 font-bold">قیمت لحظه‌ای</h2>
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
      </div>

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
              <tr key={r.row}>
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
