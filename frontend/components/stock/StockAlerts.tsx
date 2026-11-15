"use client";

import { useMemo, useSyncExternalStore } from "react";
import { useHeld } from "@/components/stock/HoldWord";
import { faNumber, jalali } from "@/lib/format";

export type AlertMeeting = { date: string; kind: string; title: string; days_left: number };
export type AlertEvent = { when: string; title: string };

const KEY = "tmon:ack";
const NEAR_DAYS = 7;
const RECENT_DAYS = 10;

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => void listeners.delete(cb);
};
const snapshot = (): string => {
  try {
    return localStorage.getItem(KEY) ?? "[]";
  } catch {
    return "[]";
  }
};

function parseAck(raw: string): string[] {
  try {
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** A general meeting can change the board; when the board is contested the exchange may stop
 *  the symbol for weeks, so these meetings get the stronger wording. */
function contested(m: AlertMeeting): boolean {
  const text = `${m.kind} ${m.title}`;
  return /فوق\s?العاده|هی[ئا]ت\s?مدیره|انتخاب|اساسنامه/.test(text);
}

function daysSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

/** The warnings that matter before a decision: the symbol is stopped, a meeting is a week away or
 *  less, and (for a symbol you hold) new Codal letters you have not marked as read. */
export function StockAlerts({
  instrumentId,
  halted,
  idleDays,
  meeting,
  events,
}: {
  instrumentId: number;
  halted: boolean;
  idleDays: number;
  meeting: AlertMeeting | null;
  events: AlertEvent[];
}) {
  const held = useHeld(instrumentId);
  const isHeld = !!held && held.length > 0;
  const raw = useSyncExternalStore(subscribe, snapshot, () => "[]");
  const acked = useMemo(() => parseAck(raw), [raw]);
  const ack = (sig: string) => {
    const next = [...new Set([...acked, sig])];
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* storage blocked: the notice just stays */
    }
    listeners.forEach((cb) => cb());
  };

  const out: React.ReactNode[] = [];

  if (halted) {
    out.push(
      <div key="halt" className="alert-bad flex flex-wrap items-center gap-2" role="alert">
        <span aria-hidden>⛔</span>
        <b>نماد متوقف است</b>
        <span>
          {faNumber(idleDays)} روز کاری بدون معامله.
          {isHeld && " سهم شما فعلاً قابل فروش نیست؛ تا بازگشایی چیزی را عوض نکنید."}
        </span>
      </div>,
    );
  }

  if (meeting && meeting.days_left >= 0 && meeting.days_left <= NEAR_DAYS) {
    const sig = `${instrumentId}:meeting:${meeting.date}`;
    const done = acked.includes(sig);
    const hard = contested(meeting);
    out.push(
      <div
        key="meeting"
        className={`${hard && isHeld && !done ? "alert-bad" : "alert-warn"} space-y-1`}
        role="alert"
        data-testid="meeting-alert"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden>🗓</span>
          <b>
            {meeting.days_left === 0
              ? "مجمع امروز است"
              : `مجمع ${faNumber(meeting.days_left)} روز دیگر`}
          </b>
          <span>
            {meeting.kind} · {jalali(meeting.date)}
          </span>
        </div>
        <p className="text-sm">
          {hard
            ? "این مجمع دربارهٔ هیئت‌مدیره، اساسنامه یا موضوعی فوق‌العاده است. اگر بین سهامداران اختلاف پیش بیاید، بورس ممکن است نماد را تا چند هفته ببندد. حجم سرمایه‌ای را که در این نماد نگه می‌دارید با این ریسک بسنجید."
            : "نزدیک مجمع، قیمت معمولاً با خبر سود نقدی جابه‌جا می‌شود و بعد از مجمع، به اندازهٔ سود تقسیم‌شده افت می‌کند. ماشین‌حساب «نگه داشتن یا فروش» در بخش «مجمع و سود نقدی» پایین همین صفحه است."}
        </p>
        {isHeld && (
          <button
            type="button"
            className="btn"
            onClick={() => ack(sig)}
            disabled={done}
            data-testid="meeting-ack"
          >
            {done ? "✓ بررسی کردم" : "دستور جلسه را خواندم و اثرش را سنجیدم"}
          </button>
        )}
      </div>,
    );
  }

  if (isHeld) {
    for (const e of events.filter((x) => daysSince(x.when) <= RECENT_DAYS).slice(0, 3)) {
      const sig = `${instrumentId}:event:${e.when}:${e.title}`;
      if (acked.includes(sig)) continue;
      out.push(
        <div key={sig} className="alert-warn flex flex-wrap items-center gap-2" role="status">
          <span aria-hidden>📄</span>
          <b>اطلاعیهٔ تازهٔ کدال برای سهمی که دارید</b>
          <span className="min-w-0 flex-1">
            {jalali(e.when, "short")} · {e.title}
          </span>
          <button type="button" className="btn" onClick={() => ack(sig)}>
            خواندم
          </button>
        </div>,
      );
    }
  }

  if (out.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="stock-alerts">
      {out}
    </div>
  );
}
