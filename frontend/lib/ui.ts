import type { CSSProperties } from "react";
import { faPercent } from "@/lib/format";

/** Presentation helpers shared by every page; the looks themselves live in globals.css. */

const VERDICTS = ["buy", "hold", "sell", "none"] as const;
export type VerdictKey = (typeof VERDICTS)[number];

const asVerdict = (v: string | null | undefined): VerdictKey =>
  (VERDICTS as readonly string[]).includes(v ?? "") ? (v as VerdictKey) : "none";

/** Solid pill for a decision (buy / hold / sell / none). */
export const verdictPill = (v: string | null | undefined) => `pill v-${asVerdict(v)}`;
/** Tinted panel for a decision. */
export const verdictTone = (v: string | null | undefined) => `tone-${asVerdict(v)}`;

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
