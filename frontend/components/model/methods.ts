/** Plain Persian names of the methods the living ranking and the deep study test. */

import { faNumber } from "@/lib/format";

const KINDS: Record<string, string> = {
  ridge4: "ریج روی ۴ سیگنال",
  ridgeall: "ریج روی ۱۸ سیگنال",
  icw: "وزن به‌نسبت IC",
};

/** The methods of ``tmon.backtest.deep_study`` (no transformer). */
const DEEP: Record<string, string> = {
  mlp: "شبکهٔ ساده (MLP sklearn)",
  dmlp: "شبکهٔ عمیق MLP (dropout و وزن‌کاهی)",
  gru: "خودبازگشتی GRU",
  tcn: "خودبازگشتی TCN (کانولوشن علّی)",
  diff: "دیفیوژن شرطی",
  resid: "یادگیری باقیمانده روی وزن مساوی",
  gbm_gru: "ترکیب GBM و GRU",
  deep_avg: "میانگین مدل‌های عمیق",
  hedge_all: "Hedge روی همهٔ روش‌ها",
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
  const deep = DEEP[key];
  if (deep) return deep;
  return key;
}
