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

const RANKING = {
  available: true,
  disclaimer: DISCLAIMER,
  as_of: "2026-11-10",
  basket_size: 100,
  recommendation_allowed: false,
  buy_top_frac: 0.1,
  hold_top_frac: 0.3,
  exposure: { trend: 1, abs_mom: 1, vol_cap: 1, stress: 0.99, exposure: 0.99 },
  exposure_date: "2026-11-10",
  rows: [
    {
      rank: 1,
      symbol: "شکام",
      name: "کیمیاگران",
      sector_code: null,
      score: 0.99,
      zone: "buy",
      queue_state: "buy_queue",
      median_value: 1e11,
      signals: { ind_buy_power: 0.9, rv_20: 0.9, dist_high_52w: 0.9, mom_12_1: 0.9 },
    },
    {
      rank: 2,
      symbol: "وبانک",
      name: "توسعه ملی",
      sector_code: null,
      score: 0.8,
      zone: "hold",
      queue_state: "none",
      median_value: 1e11,
      signals: { ind_buy_power: 0.5, rv_20: 0.5, dist_high_52w: 0.5, mom_12_1: 0.5 },
    },
    {
      rank: 3,
      symbol: "خودرو",
      name: "ایران خودرو",
      sector_code: null,
      score: 0.3,
      zone: "avoid",
      queue_state: "none",
      median_value: 1e11,
      signals: { ind_buy_power: 0.1, rv_20: 0.1, dist_high_52w: 0.1, mom_12_1: 0.1 },
    },
    {
      rank: 4,
      symbol: "اروند",
      name: "اروند",
      sector_code: null,
      score: null,
      zone: "no_data",
      queue_state: "none",
      median_value: 1e11,
      signals: { ind_buy_power: null, rv_20: null, dist_high_52w: null, mom_12_1: null },
    },
  ],
  evidence: [
    {
      horizon_days: 20,
      ic: 0.097,
      ic_t: 3.8,
      top_excess: 0.04,
      bottom_excess: 0.003,
      excess_t: 4.4,
      n_days: 1378,
    },
  ],
  gates: [
    {
      candidate: "v2",
      first: "2024-06-23",
      last: "2026-11-10",
      days: 495,
      annual: 0.64,
      annual_bench: 0.5,
      max_drawdown: -0.157,
      max_drawdown_bench: -0.239,
      verdict: "رد شد: G4، G6",
      gates: [
        { key: "G1", passed: true, text: "ok" },
        { key: "G4", passed: false, text: "t مازاد ماهانه = 0.47 روی 22 ماه (نیاز ≥ 3.0)" },
      ],
    },
  ],
  book: { n_buys: 571, cancelled_buys: 110, postponed_sells: 32, avg_held: 14.2 },
};

const MARKET = {
  available: true,
  price_date: "2026-11-10",
  n_stocks: 3,
  up: 1,
  down: 1,
  flat: 1,
  at_limit_up: 1,
  at_limit_down: 0,
  total_value: 6e10,
  median_change: 0,
  indices: [{ code: "شاخص کل (هم‌وزن)", close: 1000, change: 0.004, date: "2026-11-10" }],
  bands: [
    { label: "نزدیک صفر", count: 1 },
    { label: "بیش از ۴٪", count: 1 },
  ],
  flow: {
    date: "2026-11-10",
    n_symbols: 2,
    real_buy_value: 3e10,
    real_sell_value: 2e10,
    legal_buy_value: 1e10,
    legal_sell_value: 2e10,
    real_net: 1e10,
    per_capita_buy: 3e9,
    per_capita_sell: 4e9,
    power: 0.75,
  },
  gainers: [{ symbol: "الف", name: null, change: 0.1, value: 1e10, net_real_flow: null }],
  losers: [{ symbol: "ب", name: null, change: -0.05, value: 2e10, net_real_flow: null }],
  by_value: [{ symbol: "ج", name: null, change: 0, value: 3e10, net_real_flow: null }],
  inflow: [{ symbol: "الف", name: null, change: 0.1, value: 1e10, net_real_flow: 1e10 }],
  outflow: [],
  sectors: [{ sector_code: "27", n: 3, avg_change: 0.01, value: 6e10, net_real_flow: 1e10 }],
};

function route(url) {
  const path = url.pathname;
  if (path === "/health") return [200, { status: "ok" }];
  if (path === "/v2/ranking") return [200, RANKING];
  if (path === "/search") {
    const q = url.searchParams.get("q") ?? "";
    const all = [
      { id: 1, symbol: "فولاد", name: "فولاد مبارکه" },
      { id: 2, symbol: "فملی", name: "ملی صنایع مس" },
    ].filter((h) => h.symbol.includes(q) || h.name.includes(q) || "فلزات".includes(q));
    return [
      200,
      {
        query: q,
        total: all.length,
        hits: all.map((h) => ({
          instrument: { ...inst, id: h.id, symbol: h.symbol, name: h.name },
          sector_name: "فلزات اساسی",
          kind: "سهام",
          close: 1005,
          change_pct: 0.01,
          verdict: "hold",
          verdict_label: "نگهداری",
          gauge: 81,
          eps: 500,
          pe: 5,
          sector_pe: 8,
        })),
      },
    ];
  }
  if (path === "/screener") {
    const row = (id, symbol, verdict, label, rank) => ({
      instrument: { ...inst, id, symbol },
      close: 1005,
      change_pct: 0.01,
      value: 5e9,
      trades: 100,
      volume_ratio_30: 1.4,
      per_capita_buy: 1e8,
      per_capita_sell: 8e7,
      power: 1.25,
      net_real_value: 2e9,
      verdict,
      verdict_label: label,
      rank,
      gauge: rank == null ? null : 100 - rank * 5,
      sector_name: "فلزات اساسی",
      eps: 500,
      pe: 5,
      sector_pe: 8,
      rsi_14: 55,
    });
    const only = url.searchParams.get("verdict");
    const rows = [row(1, "وبانک", "hold", "نگهداری", 2), row(2, "خودرو", "sell", "فروش", 3)].filter(
      (r) => !only || r.verdict === only,
    );
    return [
      200,
      {
        timeframe: "D1",
        prices_date: "2025-03-01",
        flow_date: "2025-03-01",
        ranking_date: "2025-03-01",
        scores_date: null,
        gate_reasons: [],
        verdict_counts: { hold: 1, sell: 1 },
        total: rows.length,
        rows,
      },
    ];
  }
  if (path === "/market/overview") return [200, MARKET];
  if (path === "/recommendations") {
    const date = url.searchParams.get("date");
    if (date === "2000-01-01") return [500, { detail: "boom" }];
    const tf = url.searchParams.get("timeframe") ?? "D1";
    if (tf !== "D1") {
      // W1/M1 are supported but have no published run in the fixture: the backend's honest
      // "nothing yet" answer, not borrowed D1 signals.
      return [
        200,
        {
          timeframe: tf,
          supported: true,
          date: null,
          available_dates: [],
          no_recommendation: true,
          message: "هنوز اجرایی برای این تاریخ ثبت نشده است.",
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
        events: [],
        disclaimer: DISCLAIMER,
      },
    ];
  }
  if (path === "/instruments/1/dashboard") {
    return [
      200,
      {
        instrument: inst,
        isin: "IRO1FOLD0001",
        sector_name: "فلزات اساسی",
        board: "بازار اول",
        shares: 7000000000,
        market_cap: 7000000000000,
        price: {
          date: "2025-03-01",
          open: 990,
          high: 1020,
          low: 980,
          last: 1010,
          close: 1005,
          prev_close: 1000,
          last_change: 0.01,
          close_change: 0.005,
          limit_up: 1050,
          limit_down: 950,
          trades: 1200,
          volume: 5000000,
          value: 5000000000,
          base_volume: 100000,
          avg_volume_10: 4000000,
          avg_volume_22: 3500000,
          volume_ratio_30: 1.4,
        },
        flow: {
          date: "2025-03-01",
          buy_volume_i: 3000000,
          buy_volume_n: 2000000,
          sell_volume_i: 2500000,
          sell_volume_n: 2500000,
          buy_count_i: 300,
          buy_count_n: 3,
          sell_count_i: 250,
          sell_count_n: 4,
          per_capita_buy: 10000000,
          per_capita_sell: 8000000,
          power: 1.25,
          net_real_value: 500000000,
          net_real_volume: 500000,
          avg10_per_capita_buy: 9000000,
          avg10_per_capita_sell: 8500000,
          avg10_power: 1.06,
        },
        fund: null,
        fundamental: {
          eps: 500,
          pe: 5,
          sector_pe: 8,
          vs_sector: -0.375,
          verdict: "cheap",
          text: "هر سهم سالانه 500 ریال سود می‌سازد و قیمتش 5 برابر آن است.",
        },
        base_volume: 1,
        ranges: { week_min: 90, week_max: 110, year_min: 60, year_max: 130 },
        meeting: {
          date: "2026-11-23",
          clock: "10:00",
          kind: "دعوت به مجمع عادی سالیانه",
          days_left: 11,
          title: "آگهی دعوت به مجمع عمومی عادی سالیانه",
        },
        events: [{ date: "2026-11-10", label: "دعوت به مجمع عادی سالیانه", title: null }],
        share_changes: [],
        decision: {
          verdict: "hold",
          label: "نگهداری",
          advice_allowed: false,
          headline: "در ناحیهٔ نگهداری مدل است؛ خرید تازه توصیه نمی‌شود.",
          reasons: ["رتبهٔ 20 از 100 نماد پرمعامله؛ امتیاز ترکیبی 80 از ۱۰۰ (۱۰۰ = بهترین)."],
          as_of: "2025-03-01",
          rank: 20,
          basket_size: 100,
          score: 0.8,
          gauge: 81,
          in_basket: true,
          summary: "وضعش متوسط‌رو‌به‌بالاست: اگر دارید نگه دارید.",
          signals: [
            {
              key: "ind_buy_power",
              name: "قدرت خریدار حقیقی",
              pct: 95,
              text: "خریداران حقیقی چقدر بیشتر از فروشندگان پول وارد کرده‌اند؛ از 95٪ سهم‌ها بهتر است.",
            },
            {
              key: "mom_12_1",
              name: "روند ۱۲ ماههٔ قیمت",
              pct: 17,
              text: "رشد یک‌ساله؛ از 17٪ سهم‌ها بهتر است.",
            },
          ],
          holding: {
            horizon_days: 20,
            expected_excess: 0.04,
            lines: [
              "مدل برای نگهداری حدود 20 روز معاملاتی ساخته شده است، نه برای خرید و فروش در همان روز.",
              "اگر سهم را دارید نگه دارید و هر ماه امتیاز را ببینید.",
            ],
          },
        },
      },
    ];
  }
  if (path === "/instruments/1/live") {
    const level = (i) => ({
      row: i,
      bid_price: 1000 - i,
      bid_volume: 1000 * i,
      bid_count: i,
      ask_price: 1000 + i,
      ask_volume: 900 * i,
      ask_count: i,
    });
    return [
      200,
      {
        instrument_id: 1,
        available: true,
        as_of: new Date(Date.now() - 20_000).toISOString(),
        age_seconds: 20,
        stale: false,
        last_price: 1012,
        cum_volume: 456000,
        reference_price: 1000,
        change_pct: 0.012,
        book_as_of: new Date(Date.now() - 20_000).toISOString(),
        book: [1, 2, 3, 4, 5].map(level),
        message: null,
        disclaimer: DISCLAIMER,
      },
    ];
  }
  if (path === "/instruments/2/live") {
    return [
      200,
      {
        instrument_id: 2,
        available: false,
        as_of: null,
        age_seconds: null,
        stale: true,
        last_price: null,
        cum_volume: null,
        reference_price: null,
        change_pct: null,
        book_as_of: null,
        book: [],
        message: "هنوز داده‌ٔ لحظه‌ای برای این نماد ذخیره نشده است.",
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
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*", // the live panel fetches from the browser
  });
  res.end(JSON.stringify(body));
}).listen(PORT, "127.0.0.1", () => console.log(`fixture API on ${PORT}`));
