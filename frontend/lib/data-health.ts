/** Shapes of GET /data-health (backend/src/tmon/api/routers/data_health.py). */
export type HealthIssue = {
  kind: "prices_partial" | "flows_partial" | "today_pending";
  date: string;
  have: number | null;
  expected: number | null;
  first_seen: string | null;
};

export type RefillStep = { name: string; status: "ok" | "skipped" | "failed"; detail: string };

export type Refill = {
  state: "running" | "done" | "failed" | "blocked";
  started_at: string | null;
  finished_at: string | null;
  message: string;
  steps: RefillStep[];
  open_gaps: number | null;
};

export type Health = {
  checked_at: string;
  newest: string | null;
  complete: boolean;
  issues: HealthIssue[];
  refill: Refill | null;
};

/** One gap in plain words, with the exact numbers. */
export function describe(i: HealthIssue, day: string, n: (x: number) => string): string {
  const missing = i.have != null && i.expected != null ? Math.max(i.expected - i.have, 0) : null;
  const counts =
    i.have != null && i.expected != null
      ? `فقط ${n(i.have)} ردیف دریافت شده، در حالی که روزهای کنارش حدود ${n(i.expected)} ردیف دارند (${n(missing ?? 0)} کمبود)`
      : "";
  if (i.kind === "prices_partial") return `قیمت ${day}: ${counts}.`;
  if (i.kind === "flows_partial") return `حقیقی و حقوقی ${day}: ${counts}.`;
  return `قیمت ${day} هنوز دریافت نشده است (اگر امروز تعطیل بوده، نادیده بگیرید).`;
}

export const STEP_NAME: Record<string, string> = {
  history: "قیمت و حقیقی/حقوقی همهٔ نمادها",
  indices: "شاخص‌ها",
};
