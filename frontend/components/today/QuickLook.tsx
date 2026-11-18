import Link from "next/link";
import type { GoldOil } from "@/lib/api";
import { faPercent } from "@/lib/format";

const STATE = { high: "گران‌تر از معمول", normal: "در محدودهٔ معمول", low: "ارزان‌تر از معمول" };

/** Short doors to the other pages, with one live number where we have one. */
export function QuickLook({ gold }: { gold: GoldOil | null }) {
  const st = gold?.gold_prem.state;
  return (
    <nav className="ql" aria-label="نمای سریع" data-testid="quick-look">
      {gold && (
        <Link href="/market#gold-oil" className="ql-item ql-gold">
          <span className="ql-k">حباب طلای ۱۸ عیار</span>
          <span className="ql-v">{faPercent(gold.gold_prem.value, 1, true)}</span>
          {st && <span className="ql-s">{STATE[st]}</span>}
        </Link>
      )}
      <Link href="/industries" className="ql-item">
        <span className="ql-k">صنایع</span>
        <span className="ql-v">صادراتی یا داخلی</span>
        <span className="ql-s">نقشهٔ گروه‌ها و همبستگی‌ها</span>
      </Link>
      <Link href="/market" className="ql-item">
        <span className="ql-k">نمای بازار</span>
        <span className="ql-v">وضع بازار</span>
        <span className="ql-s">شاخص، پول حقیقی، دلار و طلا</span>
      </Link>
      <Link href="/picks" className="ql-item">
        <span className="ql-k">خریدهای من</span>
        <span className="ql-v">پیگیری</span>
        <span className="ql-s">سود و زیان و هشدار فروش</span>
      </Link>
    </nav>
  );
}
