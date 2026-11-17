import type { CSSProperties } from "react";
import { faPercent } from "@/lib/format";

/** Presentation helpers shared by every page; the looks themselves live in globals.css. */

const VERDICTS = ["buy", "candidate", "hold", "sell", "none"] as const;
export type VerdictKey = (typeof VERDICTS)[number];

const asVerdict = (v: string | null | undefined): VerdictKey =>
  (VERDICTS as readonly string[]).includes(v ?? "") ? (v as VerdictKey) : "none";

/** Solid pill for a decision (buy / candidate / hold / sell / none). */
export const verdictPill = (v: string | null | undefined) => `pill v-${asVerdict(v)}`;
/** Tinted panel for a decision. */
export const verdictTone = (v: string | null | undefined) => `tone-${asVerdict(v)}`;

/** The verdict the stock's own page shows (score zone softened by the tested month). Falls back to
 *  the zone for an older API without `verdict`; `null` when the stock has no decision. */
export const rowVerdict = (r: {
  verdict?: "buy" | "candidate" | "hold" | "sell" | null;
  zone?: string | null;
}): "buy" | "candidate" | "hold" | "sell" | null =>
  r.verdict !== undefined
    ? r.verdict
    : r.zone === "buy"
      ? "buy"
      : r.zone === "hold"
        ? "hold"
        : r.zone === "avoid"
          ? "sell"
          : null;

/** The words of each answer of the per-symbol verdict (ADR 0004 section 7), by `code`; the API
 *  sends the same words in `label`, this is for lists that only carry the code. */
export const CODE_FA: Record<string, string> = {
  buy: "خرید",
  candidate: "نامزد خرید",
  candidate_queue: "نامزد، ولی در صف خرید",
  wait: "صبر",
  with_market: "همراه بازار",
  avoid: "پرهیز",
  wait_market: "صبر: بازار",
  hold: "نگه‌دار",
  consider_sell: "فروش را بسنجید",
};

/** The word of a list row: its code's words, else the plain key's. */
export const rowWord = (r: { code?: string | null; verdict?: string | null }): string =>
  (r.code && CODE_FA[r.code]) ||
  ({ buy: "خرید", candidate: "نامزد خرید", hold: "صبر", sell: "پرهیز" } as Record<string, string>)[
    r.verdict ?? ""
  ] ||
  "—";

/** Text colour class for a signed number: up, down, or muted when missing. */
export const signTone = (n: number | null | undefined) =>
  n == null ? "text-muted" : n > 0 ? "text-up" : n < 0 ? "text-down" : "";

/** Spread onto a cell or tile: CSS colours it green or red, deeper with the size of the move. */
export function heatProps(r: number | null | undefined): {
  "data-heat"?: "up" | "down";
  style?: CSSProperties;
} {
  if (r == null) return {};
  const k = Math.round(Math.min(1, Math.abs(r) / 0.05) * 38);
  return { "data-heat": r >= 0 ? "up" : "down", style: { "--k": k } as CSSProperties };
}

/** Signed percent with a dash for a missing value. */
export const signedPct = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : faPercent(n, digits, true);

/** "یک ماه (۲۰ روز معاملاتی)" -> "یک ماه". */
export const shortLabel = (label: string) => label.split(" (")[0];
