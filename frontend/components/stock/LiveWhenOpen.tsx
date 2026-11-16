"use client";

import { useEffect, useState } from "react";
import { LiveQuote } from "@/components/LiveQuote";
import { EntryGuard } from "./EntryGuard";

const tehran = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Tehran",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** Tehran's exchange trades Saturday to Wednesday, about 08:45 (pre-open) to 12:45. */
function marketOpen(now: Date): boolean {
  const parts = Object.fromEntries(tehran.formatToParts(now).map((p) => [p.type, p.value]));
  if (parts.weekday === "Thu" || parts.weekday === "Fri") return false;
  const minutes = Number(parts.hour) * 60 + Number(parts.minute);
  return minutes >= 8 * 60 + 45 && minutes <= 12 * 60 + 45;
}

/** The live price and order book, shown only while the market is open; outside the session the
 *  header already holds the closing numbers, so a second price would only confuse. */
export function LiveWhenOpen({ instrumentId }: { instrumentId: number }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const tick = () => setOpen(marketOpen(new Date()));
    tick();
    const t = setInterval(tick, 30_000);
    return () => clearInterval(t);
  }, []);
  return open ? (
    <>
      <EntryGuard instrumentId={instrumentId} />
      <LiveQuote instrumentId={instrumentId} />
    </>
  ) : null;
}
