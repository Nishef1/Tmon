// Server-side client for the Tmon API. Pages call it from server components only,
// so the browser never needs to reach the API host directly.

import { unstable_rethrow } from "next/navigation";
import type { components } from "./api-schema";

// Response types are generated from the backend's OpenAPI schema (`pnpm gen:api`); the
// Pydantic models in `backend/src/tmon/api/schemas.py` are the single source of truth.
type S = components["schemas"];

export type InstrumentDashboard = S["InstrumentDashboard"];
export type Signal = S["SignalOut"];
export type Gate = S["GateOut"];
export type Diagnosis = S["DiagnosisOut"];
export type Recommendations = S["RecommendationsOut"];
export type Candle = S["Candle"];
export type InstrumentDetail = S["InstrumentDetail"];
export type History = S["HistoryOut"];
export type CalibrationBlock = S["CalibrationBlock"];
export type Calibration = S["CalibrationOut"];
export type AgmDecision = S["AgmDecisionOut"];
export type Compare = S["CompareOut"];
export type Funds = S["FundsOut"];
export type LiveAccuracy = S["LiveAccuracyOut"];
export type Screener = S["ScreenerOut"];
export type ScreenerRow = S["ScreenerRow"];
export type SymbolSearch = S["SearchOut"];
export type SearchHit = S["SearchHit"];
export type Ranking = S["RankingOut"];
export type RankingRow = S["RankingRow"];
export type MarketOverview = S["MarketOverviewOut"];
export type MarketMover = S["MarketMover"];
export type Pick = S["PickOut"];

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; error: string };

export const API_BASE =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Params = Record<string, string | number | undefined>;

export async function apiGet<T>(path: string, params: Params = {}): Promise<ApiResult<T>> {
  const url = new URL(path, API_BASE);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  }
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: res.status === 404 ? "مورد پیدا نشد." : `پاسخ ناموفق از سرور (${res.status}).`,
      };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, status: 0, error: "ارتباط با سرور برقرار نشد. کمی بعد دوباره تلاش کنید." };
  }
}

export type TaSignals = S["TaSignalsOut"];
export type TaSignal = S["TaSignal"];

/** The glossary signals' tested history. Always read fresh; null when the API cannot be reached. */
export async function taSignals(): Promise<TaSignals | null> {
  try {
    const res = await fetch(new URL("/research/ta-signals", API_BASE), {
      cache: "no-store",
    });
    return res.ok ? ((await res.json()) as TaSignals) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}

/** Latest stored intraday snapshot + order book (what the poller last wrote). */
export type LiveQuote = S["LiveOut"];

export type EntryOdds = S["EntryOddsOut"];
export type EntrySetup = S["EntrySetup"];
export type EntryHorizon = S["EntryHorizon"];
export type DashEntry = S["DashEntry"];

/** After which candles the next ones were green, tested on the whole exchange history. Always read
 *  fresh; null when the API cannot be reached. */
export async function entryOdds(): Promise<EntryOdds | null> {
  try {
    const res = await fetch(new URL("/research/entry-odds", API_BASE), {
      cache: "no-store",
    });
    return res.ok ? ((await res.json()) as EntryOdds) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}

export type OrderbookResearch = S["OrderbookResearchOut"];
export type BookFeatureRow = S["BookFeature"];
export type BookPoint = S["BookPoint"];
export type InstrumentBook = S["InstrumentBookOut"];

/** What the order book and the queues add to the score and what a realistic portfolio earned in
 *  the tested history. Always read fresh; null when unreachable. */
export async function orderbookResearch(): Promise<OrderbookResearch | null> {
  try {
    const res = await fetch(new URL("/research/orderbook-queue", API_BASE), {
      cache: "no-store",
    });
    return res.ok ? ((await res.json()) as OrderbookResearch) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}

export type Adapt = S["AdaptOut"];
export type AdaptHorizon = S["AdaptHorizon"];
export type AdaptCandidate = S["AdaptCandidate"];
export type AdaptReplayHorizon = S["AdaptReplayHorizon"];

/** The living ranking: champion per horizon, weights, drift, history and the replay.
 *  Always read fresh; null when unreachable. */
export async function adaptState(): Promise<Adapt | null> {
  try {
    const res = await fetch(new URL("/research/adapt", API_BASE), { cache: "no-store" });
    return res.ok ? ((await res.json()) as Adapt) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}

export type RegimePaper = S["RegimePaperOut"];

/** The market-state plan's paper test. Always read fresh; null when unreachable. */
export async function regimePaper(): Promise<RegimePaper | null> {
  try {
    const res = await fetch(new URL("/research/regime-paper", API_BASE), { cache: "no-store" });
    return res.ok ? ((await res.json()) as RegimePaper) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}

export type Autopilot = S["AutopilotOut"];
export type AutopilotEvent = S["AutopilotEvent"];

/** What the autopilot saw at its last check: regime reading and events. Always
 *  read fresh; null when unreachable. */
export async function autopilotState(): Promise<Autopilot | null> {
  try {
    const res = await fetch(new URL("/research/autopilot", API_BASE), { cache: "no-store" });
    return res.ok ? ((await res.json()) as Autopilot) : null;
  } catch (err) {
    unstable_rethrow(err);
    return null;
  }
}
