// Browser-side client for the portfolio pages. Each owner's key stays in their own browser
// (localStorage) and travels only in the X-Portfolio-Key header through /api/portfolios.

import { useSyncExternalStore } from "react";
import type { components } from "./api-schema";

type S = components["schemas"];
export type Portfolio = S["PortfolioOut"];
export type Holding = S["HoldingOut"];
export type Alert = S["AlertOut"];
export type Briefing = S["BriefingOut"];
export type Created = S["CreatedOut"];
export type Trade = S["TradeOut"];
export type HistoryDoc = {
  points: { date: string; value: number; return: number; index_return: number | null }[];
  return: number | null;
  index_return: number | null;
};
export type MofidStatus = {
  linked: boolean;
  status: string;
  message?: string | null;
  busy: boolean;
  token_valid?: boolean;
  last_sync_at?: string | null;
  last_result?: {
    positions: {
      symbol: string;
      isin?: string;
      shares: number;
      avg_price: number | null;
      mofid_avg_price?: number;
      cost_source?: "mofid" | "owner" | "doubtful";
      owner_cost?: number | null;
    }[];
    unknown: string[];
    cash: number;
  } | null;
};

export type Saved = { id: number; key: string; name: string };
const STORE = "tmon.portfolios";

function savedPortfolios(): Saved[] {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) ?? "[]") as unknown;
    return Array.isArray(v) ? (v as Saved[]).filter((x) => x && x.id && x.key) : [];
  } catch {
    return [];
  }
}

export function savePortfolio(p: Saved): void {
  try {
    const rest = savedPortfolios().filter((x) => x.id !== p.id);
    localStorage.setItem(STORE, JSON.stringify([...rest, p]));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    /* private mode: the key is shown once on screen, the owner keeps it */
  }
}

export function forgetPortfolio(id: number): void {
  try {
    localStorage.setItem(STORE, JSON.stringify(savedPortfolios().filter((x) => x.id !== id)));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    /* nothing stored */
  }
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function call<T>(
  path: string,
  key: string | null,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(`/api/portfolios${path}`, {
    method: init.method ?? "GET",
    headers: { "content-type": "application/json", ...(key ? { "x-portfolio-key": key } : {}) },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const d = data.detail;
    const msg =
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d.map((x: { msg?: string }) => x.msg ?? "").join("، ")
          : `خطای ${res.status}`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

// Loose shapes of the advice / forecast documents (the API returns them as JSON objects).
export type Band = Record<string, number>;
type AdviceHolding = {
  holding_id: number;
  instrument_id: number;
  symbol: string;
  score: number | null;
  rank: number | null;
  zone: string | null;
  verdict: "strong" | "hold" | "weak" | "sell" | "watch";
  verdict_fa: string;
  reasons: string[];
  pnl_pct: number | null;
  last?: number | null;
  close?: number | null;
  pnl_pct_close?: number | null;
};
type Candidate = {
  instrument_id: number;
  symbol: string;
  name: string | null;
  score: number | null;
  rank: number | null;
  last?: number | null;
  close: number | null;
  verdict?: string | null;
  shares?: number;
  amount?: number;
};
export type Advice = {
  as_of: string | null;
  validated: boolean;
  note: string;
  holdings: AdviceHolding[];
  switches: {
    sell: { symbol: string; score: number };
    buy: Candidate;
    score_gap: number;
    expected_gain_20d: number | null;
    round_trip_cost: number;
    reason: string;
  }[];
  buys: Candidate[];
  buy_note?: string | null;
  candidates: Candidate[];
};
type EntryReview = {
  trade_id: number;
  instrument_id: number;
  symbol: string;
  date: string;
  shares: number | null;
  live: boolean;
  paid: number;
  yesterday: number | null;
  first: number | null;
  high: number | null;
  low: number | null;
  last: number | null;
  close: number | null;
  gap: number | null;
  premium: number | null;
  range_pos: number | null;
  vs_close: number | null;
  pnl_last: number | null;
  pnl_close: number | null;
  flags: { key: string; text: string }[];
  score: number;
  grade: "good" | "fair" | "poor";
};
export type Entries = {
  reviews: EntryReview[];
  skipped: string[];
  lessons: string[];
  edge: number | null;
  round_trip_cost: number;
  fade: {
    days: number;
    rows: {
      label: string;
      n: number;
      open_to_last: number;
      share_below_open: number;
      share_open_near_high: number;
    }[];
  } | null;
};
type ForecastHorizon = {
  key: string;
  label: string;
  days: number;
  portfolio: Band;
  calibrated: Band;
  /** The same horizon without assuming past trends continue (drift weight 0). */
  no_trend?: Band;
  /** Share of each symbol's past trend the band assumes, chosen by backtest (0 to 1). */
  drift_weight?: number;
  value: Band;
  backtest: {
    n: number;
    coverage80?: number;
    coverage90?: number;
    n_effective?: number;
    reliable?: boolean;
  };
  symbols: ({ symbol: string; instrument_id: number } & Band)[];
};
export type Forecast = {
  available: boolean;
  reason?: string;
  skipped: string[];
  as_of?: string;
  value?: number;
  history_days?: number;
  first_day?: string;
  annual_vol_now?: number;
  method?: string;
  horizons?: ForecastHorizon[];
};
type BriefingItem = AdviceHolding & {
  action: "exit" | "reduce" | "hold" | "add";
  action_fa: string;
  confidence: number;
  why: string[];
  news: { title: string; direction: number | null }[];
  codal: { title: string; url: string | null; bad: boolean }[];
  macro?: {
    total: number;
    items: {
      series: string;
      label_fa: string;
      move: number;
      beta: number;
      t: number;
      impact: number;
    }[];
  };
};
type MacroMove = {
  series: string;
  label_fa: string;
  domestic: boolean;
  last: number;
  date: string;
  change_1: number | null;
  change_5: number | null;
};
type ForeignHeadline = {
  title: string;
  source: string;
  url: string;
  iran: boolean;
  tags: string[];
};
export type BriefingDoc = {
  kind: string;
  at: string;
  method: string;
  market_fa: string;
  note: string;
  holdings: BriefingItem[];
  macro?: MacroMove[];
  foreign?: ForeignHeadline[];
};

// -- reading the saved keys from React without effects ------------------------------------------
const CHANGED = "tmon-portfolios-changed";
const listeners = (cb: () => void) => {
  window.addEventListener("storage", cb);
  window.addEventListener(CHANGED, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(CHANGED, cb);
  };
};
function rawSaved(): string {
  try {
    return localStorage.getItem(STORE) ?? "[]";
  } catch {
    return "[]";
  }
}
let memo: { raw: string; list: Saved[] } = { raw: "", list: [] };
function snapshot(): Saved[] {
  const raw = rawSaved();
  if (raw !== memo.raw) memo = { raw, list: savedPortfolios() };
  return memo.list;
}
const SERVER: Saved[] = [];

/** The portfolios saved in this browser; null while rendering on the server. */
export function useSaved(): Saved[] | null {
  const list = useSyncExternalStore(listeners, snapshot, () => SERVER);
  const hydrated = useSyncExternalStore(
    listeners,
    () => true,
    () => false,
  );
  return hydrated ? list : null;
}

/** Notification permission, or "unsupported" (also on the server). */
export function useNotificationPermission(): [
  NotificationPermission | "unsupported",
  () => Promise<void>,
] {
  const perm = useSyncExternalStore(
    listeners,
    () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission),
    () => "unsupported" as const,
  );
  const ask = async () => {
    await Notification.requestPermission();
    window.dispatchEvent(new Event(CHANGED));
  };
  return [perm, ask];
}
