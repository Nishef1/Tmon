"use client";

import type { ReactNode } from "react";
import { Gauge } from "@/components/Gauge";
import { HoldWord, useOwned } from "@/components/stock/HoldWord";
import type { InstrumentDashboard } from "@/lib/api";
import { faDigits, faNumber } from "@/lib/format";
import { shortLabel, verdictPill, verdictTone } from "@/lib/ui";

type D = InstrumentDashboard;
type H = NonNullable<D["decision"]["horizons"][number]> | undefined;

/** The card of the decision: its tone and `data-verdict` follow the reader. An owner sees the
 *  answer meant for an owner. Client side, because who owns the stock is known only in the browser. */
export function DecisionShell({
  d,
  h,
  id,
  children,
}: {
  d: D["decision"];
  h: H;
  id: number;
  children: ReactNode;
}) {
  const owned = useOwned(id);
  const verdict = owned ? (d.holder_verdict ?? d.verdict) : (h?.verdict ?? d.verdict);
  return (
    <section
      className={`card ${verdictTone(verdict)}`}
      data-testid="symbol-decision"
      data-verdict={verdict}
    >
      {children}
    </section>
  );
}

/** The verdict with the small gauge beside it. An owner sees the answer meant for an owner. */
export function Verdict({ d, h, id }: { d: D["decision"]; h: H; id: number }) {
  const owned = useOwned(id);
  const verdict = owned ? (d.holder_verdict ?? d.verdict) : (h?.verdict ?? d.verdict);
  const label = h?.verdict_label ?? d.label;
  const text = owned && d.holder_headline ? d.holder_headline : (h?.headline ?? d.headline);
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3" data-testid="verdict-head">
      <div className="min-w-[15rem] flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`${verdictPill(verdict)} pill-lg`} data-testid="verdict-word">
            <HoldWord label={label} holderLabel={d.holder_label} instrumentId={id} />
          </span>
          {d.grade_label && d.band !== "middle" && (
            <span className="chip text-xs" data-testid="verdict-grade">
              شواهد این ناحیه: {d.grade_label}
            </span>
          )}
          {h && <span className="text-muted">برای {shortLabel(h.label)}</span>}
        </div>
        <p className="text-base font-semibold leading-8">
          {faDigits(
            (owned ? text : text || d.summary || d.headline).replace(/^برای [^:]*:\s*/, ""),
          )}
        </p>
      </div>
      <div className="w-40 shrink-0" data-testid="gauge-box">
        <Gauge
          value={d.gauge}
          label="جایگاه امروز در بازار"
          zones={
            d.zone_hold_from != null && d.zone_buy_from != null
              ? { hold: d.zone_hold_from, buy: d.zone_buy_from }
              : undefined
          }
        />
        <p className="text-center text-xs text-muted">
          {d.gauge == null
            ? "امتیازی محاسبه نشده"
            : `جایگاه امروز در بازار${d.rank != null ? ` · رتبهٔ ${faNumber(d.rank)}` : ""}`}
        </p>
        {d.gauge != null && d.verdict !== "buy" && d.gauge >= (d.zone_buy_from ?? 90) && (
          <p className="text-center text-xs text-muted" data-testid="gauge-not-advice">
            این فقط رتبه است؛ توصیه همان کلمهٔ کنارش است.
          </p>
        )}
      </div>
    </div>
  );
}
