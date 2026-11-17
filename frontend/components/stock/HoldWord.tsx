"use client";

import { useEffect, useState } from "react";
import { call, useSaved, type Holding, type Portfolio } from "@/lib/portfolio";

export type Held = { portfolio: string; h: Holding };

/** This browser's portfolio lines for the symbol: null while loading, [] when it is not held. */
export function useHeld(instrumentId: number): Held[] | null {
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
  if (saved && saved.length === 0) return [];
  return held;
}

/** True when one of this browser's portfolios holds the symbol. */
export function useOwned(instrumentId: number): boolean {
  const held = useHeld(instrumentId);
  return !!held && held.length > 0;
}

/** The verdict word for this reader: the owner's answer (hold / consider selling) when the symbol
 *  is in one of their portfolios, otherwise the one for someone who does not own it («صبر», never
 *  «نگه‌دار»). Both words come from the API; nothing is translated here. */
export function HoldWord({
  label,
  holderLabel,
  instrumentId,
}: {
  label: string;
  holderLabel?: string | null;
  instrumentId: number;
}) {
  const owned = useOwned(instrumentId);
  return <>{owned && holderLabel ? holderLabel : label}</>;
}
