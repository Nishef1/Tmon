"use client";

import Link from "next/link";
import { useSaved } from "@/lib/portfolio";
import { useHeld } from "@/components/stock/HoldWord";
import { faNumber, faPercent } from "@/lib/format";
import { signTone } from "@/lib/ui";

/** Whether this browser's portfolios hold the symbol, with the position's profit or loss. */
export function PortfolioBadge({ instrumentId }: { instrumentId: number }) {
  const saved = useSaved();
  const held = useHeld(instrumentId);
  if (!saved) return null;
  if (held && held.length === 0) {
    return (
      <Link href="/portfolios" className="chip" data-testid="portfolio-badge" data-held="false">
        + افزودن به پرتفوی
      </Link>
    );
  }
  if (!held) return null;
  return (
    <>
      {held.map(({ portfolio, h }) => (
        <Link
          key={`${portfolio}-${h.id}`}
          href="/portfolios"
          className="chip"
          data-testid="portfolio-badge"
          data-held="true"
        >
          شما در پرتفوی «{portfolio}» {faNumber(h.shares)} سهم دارید
          {h.pnl_pct != null && (
            <span className={`ms-1 ${signTone(h.pnl_pct)}`}>
              ، سود یا زیان تا امروز {faPercent(h.pnl_pct, 1, true)}
            </span>
          )}
        </Link>
      ))}
    </>
  );
}
