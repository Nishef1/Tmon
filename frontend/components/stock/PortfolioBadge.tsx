"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { call, useSaved, type Holding, type Portfolio } from "@/lib/portfolio";
import { faNumber, faPercent } from "@/lib/format";
import { signTone } from "@/lib/ui";

type Held = { portfolio: string; h: Holding };

/** Whether this browser's portfolios hold the symbol, with the position's profit or loss. */
export function PortfolioBadge({ instrumentId }: { instrumentId: number }) {
  const saved = useSaved();
  const [held, setHeld] = useState<Held[] | null>(null);
  useEffect(() => {
    if (!saved || saved.length === 0) return;
    let live = true;
    Promise.all(
      saved.map((s) =>
        call<Portfolio>(`/${s.id}`, s.key)
          .then((p) =>
            p.holdings
              .filter((h) => h.instrument_id === instrumentId)
              .map((h) => ({ portfolio: p.name, h })),
          )
          .catch(() => [] as Held[]),
      ),
    ).then((all) => live && setHeld(all.flat()));
    return () => {
      live = false;
    };
  }, [saved, instrumentId]);
  if (!saved) return null;
  if (saved.length === 0 || (held && held.length === 0)) {
    return (
      <Link href="/portfolios" className="chip" data-testid="portfolio-badge" data-held="false">
        در پرتفوی شما نیست · افزودن برای هشدار خروج
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
              ، سود/زیان تا الان {faPercent(h.pnl_pct, 1, true)}
            </span>
          )}
        </Link>
      ))}
    </>
  );
}
