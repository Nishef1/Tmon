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

/** The verdict word: "hold" only makes sense for a stock you own; otherwise it means wait. A
 *  "hold" that exists only because the past does not back a sell (`weak`: the score itself is
 *  low) reads «نخرید» to someone who does not own the stock and «فروش را بسنجید» to an owner. */
export function HoldWord({
  verdict,
  label,
  instrumentId,
  weak = false,
}: {
  verdict: string;
  label: string;
  instrumentId: number;
  weak?: boolean;
}) {
  const held = useHeld(instrumentId);
  if (verdict !== "hold") return <>{label}</>;
  const owned = !!held && held.length > 0;
  if (weak) return <>{owned ? "فروش را بسنجید" : "نخرید"}</>;
  return <>{owned ? "نگهداری" : "صبر"}</>;
}
