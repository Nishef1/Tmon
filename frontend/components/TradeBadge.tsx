import { faNumber, jalali } from "@/lib/format";

type State = "active" | "idle" | "halted";

const LOOK: Record<Exclude<State, "active">, { icon: string; cls: string }> = {
  idle: { icon: "◔", cls: "bg-warn-soft text-warn" },
  halted: { icon: "⛔", cls: "bg-down-soft text-down" },
};

/** Marks a symbol that is not trading: a stop sign with red for a halt (several market days
 *  without a trade), an amber half-circle for a symbol that only skipped today. Nothing for a
 *  symbol that traded on the latest day. */
export function TradeBadge({
  state,
  idleDays,
  lastTrade,
  long = false,
}: {
  state: State;
  idleDays: number;
  lastTrade?: string | null;
  long?: boolean;
}) {
  if (state === "active") return null;
  const look = LOOK[state];
  const short = state === "halted" ? "متوقف" : "امروز معامله نشد";
  const detail =
    state === "halted"
      ? `${faNumber(idleDays)} روز کاری بدون معامله${lastTrade ? `؛ آخرین معامله ${jalali(lastTrade, "short")}` : ""}`
      : "";
  return (
    <span
      className={`chip ${look.cls}`}
      title={detail || short}
      data-testid="trade-badge"
      data-state={state}
    >
      <span aria-hidden>{look.icon}</span>
      {short}
      {state === "halted" && <span className="font-normal">· {faNumber(idleDays)} روز</span>}
      {long && detail && <span className="font-normal">· {detail}</span>}
    </span>
  );
}
