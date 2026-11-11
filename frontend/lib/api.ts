// Server-side client for the Tmon API. Pages call it from server components only,
// so the browser never needs to reach the API host directly.

export type Instrument = {
  id: number;
  symbol: string;
  name: string | null;
  sector_code: string | null;
  instrument_type: string | null;
};

export type Reason = { feature: string; value: number | null; contribution: number };

export type Signal = {
  id: number;
  date: string;
  timeframe: string;
  rank: number;
  instrument: Instrument;
  entry_price: number;
  entry_rule: string;
  take_profit: number;
  stop_loss: number;
  horizon_days: number;
  p_win: number;
  ev: number;
  confidence_tier: string;
  position_pct: number;
  top_reasons: Reason[];
  risks: string[];
  model_version: string;
  data_snapshot_id: string;
  outcome: string;
  realized_return: number | null;
  outcome_date: string | null;
};

export type Run = {
  date: string;
  model_version: string;
  data_snapshot_id: string;
  n_candidates: number;
  n_recommended: number;
  defensive_mode: boolean;
  message: string | null;
  created_at: string;
};

export type Gate = { tier_a_allowed: boolean; reasons: string[] };

export type Recommendations = {
  timeframe: string;
  supported: boolean;
  date: string | null;
  available_dates: string[];
  no_recommendation: boolean;
  message: string;
  disclaimer: string;
  run: Run | null;
  gate: Gate | null;
  signals: Signal[];
};

export type Candle = {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type InstrumentDetail = {
  instrument: Instrument;
  adjusted: boolean;
  candles: Candle[];
  features_date: string | null;
  features: { feature: string; value: number | null }[];
  signals: Signal[];
  disclaimer: string;
};

export type HistorySummary = {
  total: number;
  resolved: number;
  pending: number;
  take_profit: number;
  stop_loss: number;
  expired: number;
  mean_realized_return: number | null;
};

export type History = {
  timeframe: string;
  items: Signal[];
  total: number;
  limit: number;
  offset: number;
  summary: HistorySummary;
  disclaimer: string;
};

export type CalibrationBucket = {
  bucket: string;
  n: number;
  mean_p: number | null;
  hit_rate: number | null;
};

export type CalibrationBlock = {
  n: number;
  base_rate: number | null;
  auc: number | null;
  brier: number | null;
  brier_base_rate: number | null;
  brier_skill: number | null;
  buckets: CalibrationBucket[];
};

export type Calibration = {
  timeframe: string;
  supported: boolean;
  model_version: string | null;
  trained_through: string | null;
  backtest: CalibrationBlock | null;
  live: CalibrationBlock;
  gate: Gate | null;
  warnings: string[];
  disclaimer: string;
};

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
