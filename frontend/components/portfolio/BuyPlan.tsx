"use client";

import { useEffect, useState } from "react";
import { faPercent, faPrice } from "@/lib/format";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 30_000;

type Step = { price: number; day_fill_prob: number; vs_now: number };
type Reply = {
  available?: boolean;
  guard?: { state: string; max_price?: number | null };
  plan?: { available: boolean; mode?: "today" | "next"; recommended?: Step | null };
};

/** The limit price the entry planner recommends for one suggested purchase, read from the live
 *  entry endpoint each time (nothing is kept). Shows nothing when there is no price to suggest. */
export function BuyPlan({ instrumentId }: { instrumentId: number }) {
  const [r, setR] = useState<Reply | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const res = await fetch(`${BASE}/instruments/${instrumentId}/entry`, { cache: "no-store" });
        if (res.ok && alive) setR((await res.json()) as Reply);
      } catch {
        /* the line simply stays hidden */
      }
      if (alive) timer = setTimeout(() => void load(), POLL_MS);
    };
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [instrumentId]);
  const best = r?.plan?.available ? r.plan.recommended : null;
  if (!best) return null;
  return (
    <span className="text-muted" data-testid="buy-plan">
      {" "}
      — سفارش حدی در <b className="text-up">{faPrice(best.price)}</b> (شانس پرشدن{" "}
      {faPercent(best.day_fill_prob, 0)}؛ اگر تا پایان روز پر نشد دنبالش نروید)
    </span>
  );
}
