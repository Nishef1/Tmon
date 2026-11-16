/** Plain Persian names of the methods the living ranking tests. */

import { faNumber } from "@/lib/format";

const KINDS: Record<string, string> = {
  ridge4: "ریج روی ۴ سیگنال",
  ridgeall: "ریج روی ۱۸ سیگنال",
  icw: "وزن به‌نسبت IC",
};

/** Plain name of a method key of ``tmon.backtest.adaptive_study`` (the number is the half-life in days). */
export function methodLabel(key: string): string {
  if (key === "equal") return "وزن مساوی";
  const m = /^(ridge4|ridgeall|icw)_x(\d+)$/.exec(key);
  if (m) return `${KINDS[m[1]]} (نیمه‌عمر ${faNumber(Number(m[2]))} روز)`;
  const h = /^hedge_k(\d+)$/.exec(key);
  if (h) return `Hedge (κ=${faNumber(Number(h[1]))})`;
  if (key === "gbm") return "درخت تقویتی (GBM)";
  if (key === "step6") return "پلهٔ شش‌ماهه";
  return key;
}
