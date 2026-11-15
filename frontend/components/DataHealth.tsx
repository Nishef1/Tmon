"use client";

import { useEffect, useState } from "react";
import { describe, STEP_NAME, type Health } from "@/lib/data-health";
import { faNumber, jalali } from "@/lib/format";

const POLL_MS = 3000;

async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/data-health", { cache: "no-store" });
  if (!res.ok) throw new Error(String(res.status));
  return (await res.json()) as Health;
}

/** Says exactly which stored days are incomplete (with the row counts) and starts the refill.
 *  Shows nothing while the data is complete. Polls only while a refill is running. */
export function DataHealth() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    fetchHealth()
      .then((data) => {
        if (!live) return;
        setH(data);
        setErr(null);
      })
      .catch(() => live && setErr("وضعیت داده‌ها خوانده نشد."));
    return () => {
      live = false;
    };
  }, [tick]);

  const running = h?.refill?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = setTimeout(() => setTick((x) => x + 1), POLL_MS);
    return () => clearTimeout(t);
  }, [running, h]);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/data-health", { method: "POST", cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setTick((x) => x + 1);
    } catch {
      setErr("شروع تکمیل ممکن نشد.");
    } finally {
      setBusy(false);
    }
  };

  if (!h) return null;
  const finished = h.refill && h.refill.state !== "running" ? h.refill : null;
  if (h.complete && !running && !(finished && finished.steps.length > 0)) return null;

  return (
    <section
      className="mb-4 rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm"
      data-testid="data-health"
      data-complete={h.complete}
    >
      {!h.complete && (
        <>
          <p className="font-bold">داده‌های ذخیره‌شده کامل نیستند</p>
          <ul className="mt-1 list-disc space-y-1 ps-5" data-testid="data-gaps">
            {h.issues.map((i) => (
              <li key={`${i.kind}-${i.date}`}>
                {describe(i, jalali(i.date), faNumber)}
                {i.first_seen && i.first_seen !== i.date && (
                  <span className="text-muted"> (از {jalali(i.first_seen)} باز است)</span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-muted">
            تا تکمیل شدن، رتبه‌بندی و حکم‌ها روی بخشی از بازار حساب می‌شوند و ممکن است جابه‌جا شوند.
            هر دورهٔ روزانه این خلأها را در یادداشت داده ثبت و دوباره بررسی می‌کند.
          </p>
        </>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="tab tab-pill text-sm"
          onClick={start}
          disabled={busy || running}
          data-testid="refill-button"
        >
          {running ? "در حال دریافت…" : "دریافت و ذخیرهٔ داده‌های ناقص"}
        </button>
        {running && <span className="text-muted">{h.refill?.message}</span>}
        {err && <span className="text-down">{err}</span>}
      </div>
      {finished && (
        <div className="mt-2" data-testid="refill-result" data-state={finished.state}>
          <p className="font-semibold">
            آخرین تلاش
            {finished.finished_at ? ` (${jalali(finished.finished_at.slice(0, 10))})` : ""}:{" "}
            {finished.message}
          </p>
          <ul className="mt-1 list-disc space-y-1 ps-5 text-muted">
            {finished.steps.map((s) => (
              <li key={s.name}>
                {STEP_NAME[s.name] ?? s.name}:{" "}
                {s.status === "ok" ? "انجام شد" : s.status === "skipped" ? "انجام نشد" : "خطا"}
                {s.status !== "ok" && ` — ${s.detail}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
