// Server-side client for the Tmon API. Pages call it from server components only,
// so the browser never needs to reach the API host directly.

import type { components } from "./api-schema";

// Response types are generated from the backend's OpenAPI schema (`pnpm gen:api`); the
// Pydantic models in `backend/src/tmon/api/schemas.py` are the single source of truth.
type S = components["schemas"];

export type Instrument = S["InstrumentOut"];
export type Reason = S["Reason"];
export type Signal = S["SignalOut"];
export type Run = S["RunOut"];
export type Gate = S["GateOut"];
export type Diagnosis = S["DiagnosisOut"];
export type Recommendations = S["RecommendationsOut"];
export type Candle = S["Candle"];
export type InstrumentDetail = S["InstrumentDetail"];
export type HistorySummary = S["HistorySummary"];
export type History = S["HistoryOut"];
export type CalibrationBucket = S["CalibrationBucket"];
export type CalibrationBlock = S["CalibrationBlock"];
export type Calibration = S["CalibrationOut"];
export type CorporateEvent = S["CorporateEventOut"];
export type AgmDecision = S["AgmDecisionOut"];
export type Compare = S["CompareOut"];
export type CompareRow = S["CompareRow"];
export type Funds = S["FundsOut"];
export type LiveAccuracy = S["LiveAccuracyOut"];
export type Screener = S["ScreenerOut"];
export type ScreenerRow = S["ScreenerRow"];

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

export type BookLevel = S["BookLevelOut"];

/** Latest stored intraday snapshot + order book (what the poller last wrote). */
export type LiveQuote = S["LiveOut"];
