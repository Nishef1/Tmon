// Minimal fixture server for the end-to-end tests. Every value is invented for UI tests;
// none of it is market data and none of it is shown by the real application.
import { createServer } from "node:http";

const PORT = Number(process.env.PORT ?? 8787);
const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

const inst = {
  id: 1,
  symbol: "فولاد",
  name: "فولاد مبارکه اصفهان",
  sector_code: "27",
  instrument_type: "stock",
};
const inst2 = {
  id: 2,
  symbol: "خودرو",
  name: "ایران خودرو",
  sector_code: "34",
  instrument_type: "stock",
};

const signal = (id, rank, i, over = {}) => ({
  id,
  date: "2025-03-01",
  timeframe: "D1",
  rank,
  instrument: i,
  entry_price: 1000,
  entry_rule: "open_next_day",
  take_profit: 1060,
  stop_loss: 970,
  horizon_days: 3,
  p_win: 0.66,
  ev: 0.031,
  confidence_tier: "B",
  position_pct: 0.05,
  top_reasons: [
    { feature: "rsi_14", value: 55.2, contribution: 0.41 },
    { feature: "ind_buy_power", value: 1.8, contribution: 0.22 },
    { feature: "ret_5", value: -0.02, contribution: -0.05 },
  ],
  risks: ["نوسان روزانه بالاتر از میانگین بازار"],
  model_version: "fixture-1",
  data_snapshot_id: "fixture-snap",
  outcome: "pending",
  realized_return: null,
  outcome_date: null,
  ...over,
});

const gate = {
  tier_a_allowed: false,
  reasons: ["تعداد معاملات خارج از نمونه (۱۲) کمتر از حداقل ۱۰۰ است."],
};

const run = (n) => ({
  date: "2025-03-01",
  model_version: "fixture-1",
  data_snapshot_id: "fixture-snap",
  n_candidates: 9,
  n_recommended: n,
  defensive_mode: false,
  message: n ? null : "امروز توصیه‌ای وجود ندارد: هیچ نمادی از آستانه‌ها عبور نکرد.",
  created_at: "2025-03-01T11:00:00Z",
});

function candles() {
  const out = [];
  let p = 1000;
  const start = Date.UTC(2024, 9, 1);
  for (let i = 0; i < 120; i++) {
    const d = new Date(start + i * 86400000);
    if ([5, 6].includes(d.getUTCDay())) continue; // Friday/Saturday: no trading
    const o = p;
    p = Math.round(p * (1 + Math.sin(i / 7) * 0.012));
    out.push({
      date: d.toISOString().slice(0, 10),
      open: o,
      high: Math.max(o, p) + 8,
      low: Math.min(o, p) - 8,
      close: p,
      volume: 1e6,
    });
  }
  return out;
}

const history = [
  signal(10, 1, inst, {
    date: "2025-02-26",
    outcome: "tp",
    realized_return: 0.06,
    outcome_date: "2025-02-28",
  }),
  signal(11, 1, inst2, {
    date: "2025-02-25",
    outcome: "sl",
    realized_return: -0.03,
    outcome_date: "2025-02-26",
  }),
  signal(12, 1, inst, {
    date: "2025-02-24",
    outcome: "expiry",
    realized_return: 0.004,
    outcome_date: "2025-02-27",
  }),
  signal(13, 1, inst2, { date: "2025-03-01" }),
];

const bucket = (b, n, p, h) => ({ bucket: b, n, mean_p: p, hit_rate: h });
const block = {
  n: 640,
  base_rate: 0.31,
  auc: 0.58,
  brier: 0.205,
  brier_base_rate: 0.214,
  brier_skill: 0.042,
  buckets: [
    bucket("0.2-0.3", 220, 0.26, 0.25),
    bucket("0.3-0.4", 260, 0.34, 0.32),
    bucket("0.6-0.7", 40, 0.64, 0.55),
  ],
};

function route(url) {
  const path = url.pathname;
  if (path === "/health") return [200, { status: "ok" }];
  if (path === "/recommendations") {
    const date = url.searchParams.get("date");
    if (date === "2000-01-01") return [500, { detail: "boom" }];
    const tf = url.searchParams.get("timeframe") ?? "D1";
    if (tf !== "D1") {
      return [
        200,
        {
          timeframe: tf,
          supported: false,
          date: null,
          available_dates: [],
          no_recommendation: true,
          message: "مدل این تایم‌فریم در فاز ۱ ساخته نشده است؛ فقط D1 فعال است.",
          disclaimer: DISCLAIMER,
          run: null,
          gate: null,
          signals: [],
        },
      ];
    }
    const none = date === "2025-02-20";
    const signals = none
      ? []
      : [signal(1, 1, inst), signal(2, 2, inst2, { p_win: 0.63, ev: 0.024, confidence_tier: "C" })];
    return [
      200,
      {
        timeframe: "D1",
        supported: true,
        date: none ? "2025-02-20" : "2025-03-01",
        available_dates: ["2025-03-01", "2025-02-20"],
        no_recommendation: none,
        message: none ? run(0).message : `${signals.length} توصیه`,
        disclaimer: DISCLAIMER,
        run: run(signals.length),
        gate,
        signals,
      },
    ];
  }
  if (path === "/instruments/1") {
    return [
      200,
      {
        instrument: inst,
        adjusted: true,
        candles: candles(),
        features_date: "2025-03-01",
        features: [
          { feature: "rsi_14", value: 55.2 },
          { feature: "adx_14", value: null },
          { feature: "breadth", value: 0.52 },
        ],
        signals: [signal(1, 1, inst)],
        disclaimer: DISCLAIMER,
      },
    ];
  }
  if (path.startsWith("/instruments/")) return [404, { detail: "نماد پیدا نشد" }];
  if (path === "/signals/history") {
    const o = url.searchParams.get("outcome");
    const items = o
      ? history.filter((s) => (o === "sl" ? s.outcome.startsWith("sl") : s.outcome === o))
      : history;
    return [
      200,
      {
        timeframe: "D1",
        items,
        total: items.length,
        limit: 25,
        offset: 0,
        summary: {
          total: 4,
          resolved: 3,
          pending: 1,
          take_profit: 1,
          stop_loss: 1,
          expired: 1,
          mean_realized_return: 0.0113,
        },
        disclaimer: DISCLAIMER,
      },
    ];
  }
  if (path === "/metrics/calibration") {
    return [
      200,
      {
        timeframe: "D1",
        supported: true,
        model_version: "fixture-1",
        trained_through: "2025-02-28",
        backtest: block,
        live: {
          n: 0,
          base_rate: null,
          auc: null,
          brier: null,
          brier_base_rate: null,
          brier_skill: null,
          buckets: [],
        },
        gate,
        warnings: ["هزینه‌ها و قوانین بازار هنوز با داده واقعی تأیید نشده‌اند."],
        disclaimer: DISCLAIMER,
      },
    ];
  }
  return [404, { detail: "not found" }];
}

createServer((req, res) => {
  const [status, body] = route(new URL(req.url ?? "/", `http://${req.headers.host}`));
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}).listen(PORT, "127.0.0.1", () => console.log(`fixture API on ${PORT}`));
