import type { RankingRow } from "@/lib/api";
import { faNumber } from "@/lib/format";

const LEVEL = {
  weak: { word: "ضعیف", cls: "bg-up-soft text-up" },
  medium: { word: "متوسط", cls: "bg-warn-soft text-warn" },
  heavy: { word: "سنگین", cls: "bg-down-soft text-down" },
} as const;

type Queue = Partial<
  Pick<RankingRow, "queue_state" | "queue_ratio" | "queue_level" | "queue_orders">
>;

/** «صف خرید سنگین (۲٫۴)»: how heavy the buy line is, with the ratio of the line to a usual day's
 *  volume in parentheses. Under 0.3 the line is weak, up to 1 medium, above 1 heavy. A symbol that
 *  closed in a buy line but has no stored book shows the plain «صف خرید». */
export function QueueBadge({ r, className = "" }: { r: Queue; className?: string }) {
  const lvl = r.queue_level ? LEVEL[r.queue_level] : null;
  if (r.queue_ratio != null && lvl) {
    const orders = r.queue_orders ? ` و ${faNumber(r.queue_orders)} سفارش` : "";
    return (
      <span
        className={`rounded px-1 text-[10px] ${lvl.cls} ${className}`}
        data-testid="queue-badge"
        title={`حجم صف ${faNumber(r.queue_ratio, 2)} برابر حجم معمول یک روز${orders}`}
      >
        صف خرید {lvl.word} ({faNumber(r.queue_ratio, 1)})
      </span>
    );
  }
  if (r.queue_state !== "buy_queue") return null;
  return (
    <span className={`rounded bg-up-soft px-1 text-[10px] text-up ${className}`}>صف خرید</span>
  );
}
