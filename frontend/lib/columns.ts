// Derived columns (backend `tmon.features.columns`): how each kind of value is written, and the
// table columns built from the catalog the API serves. Display only; nothing here feeds a verdict.

import type { components } from "./api-schema";
import { faCount, faNumber, faPercent, faToman, jalali } from "./format";

type S = components["schemas"];
export type ColumnCatalog = S["ColumnCatalog"];
export type ColumnDef = S["ColumnDef"];
export type InstrumentColumns = S["InstrumentColumns"];
export type ColumnItem = S["ColumnItem"];
export type MarketBlock = S["MarketBlock"];

export type ColValue = number | string | null | undefined;

const DATE_KEYS = new Set(["first_day", "fiscal_year_end"]);
/** Percent columns whose sign matters, so a plus is written for a rise. */
const SIGNED_GROUPS = new Set(["returns", "range", "flow", "growth"]);
const SIGNED_KEYS = new Set(["index_impact", "real_net_vs_avg"]);

export function isSigned(def: Pick<ColumnDef, "key" | "group" | "kind">): boolean {
  return def.kind === "percent" && (SIGNED_GROUPS.has(def.group) || SIGNED_KEYS.has(def.key));
}

/** One value as the site writes it; "—" when the data behind it is missing. */
export function fmtCol(def: Pick<ColumnDef, "key" | "group" | "kind">, v: ColValue): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return DATE_KEYS.has(def.key) ? jalali(v) : v;
  if (!Number.isFinite(v)) return "—";
  switch (def.kind) {
    case "percent":
      return faPercent(v, 1, isSigned(def));
    case "multiple":
      return faNumber(v, 2);
    case "ratio":
      return faNumber(v, 2);
    case "money":
      return faToman(v);
    case "count":
      return faCount(v);
    case "price":
      return faNumber(v, 0);
    case "score":
      return `${faNumber(v, 0)} از ۱۰۰`;
    default:
      return String(v);
  }
}

/** Text colour of a signed value: up, down or neutral. */
export function colTone(def: Pick<ColumnDef, "key" | "group" | "kind">, v: ColValue): string {
  if (typeof v !== "number" || !isSigned(def)) return "";
  return v > 0 ? "text-up" : v < 0 ? "text-down" : "";
}

/** Group label of a column key, for the picker. */
export function groupLabel(cat: ColumnCatalog, key: string): string {
  return cat.groups.find((g) => g.key === key)?.label ?? key;
}

/** Keys the screener is asked for: every number (text columns are per symbol, on its own page). */
export function numericKeys(cat: ColumnCatalog): string[] {
  return cat.columns.filter((c) => c.kind !== "text" && c.key !== "first_day").map((c) => c.key);
}
