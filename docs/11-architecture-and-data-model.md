# ۱۱ — معماری و مدل داده

## جریان

```
منابع (TSETMC, Codal, IME, Fipiran, CBI, SCI, News)
  → ingest workers (Celery)  → raw payloads (MinIO)
  → parsers/normalizers      → PostgreSQL + TimescaleDB
  → feature builder (Polars, point-in-time) → features
  → models per timeframe (LightGBM + isotonic) → signals
  → FastAPI → Next.js (داشبورد، صفحه نماد، تقویم مجامع، مقایسه با تورم، آکادمی)
```

موتورها فقط از DB می‌خوانند و فقط در DB می‌نویسند؛ هیچ موتوری مستقیم موتور دیگر را صدا نمی‌زند.

## ساختار ریپو (تثبیت‌شده)

```
/
├─ docs/                    # همه مستندات (این پوشه)
├─ backend/
│  ├─ pyproject.toml        # uv
│  ├─ src/tmon/
│  │  ├─ core/              # config, logging, time (Jalali/Tehran), db session
│  │  ├─ domain/            # Pydantic models, enums (instrument_type, timeframe)
│  │  ├─ ingest/
│  │  │  ├─ tsetmc/  codal/  ime/  fipiran/  macro/  news/
│  │  ├─ storage/           # SQLAlchemy models, repositories
│  │  ├─ features/          # technical.py, orderbook.py, fundamental.py, events.py, macro.py
│  │  ├─ labeling/          # triple_barrier.py
│  │  ├─ models/            # baseline.py, lgbm.py, calibration.py, registry.py
│  │  ├─ engine/            # universe.py, scoring.py, sizing.py, recommend.py
│  │  ├─ backtest/          # walk_forward.py, costs.py, metrics.py, report.py
│  │  ├─ api/               # FastAPI routers
│  │  └─ tasks/             # Celery tasks + beat schedule
│  ├─ migrations/           # Alembic
│  ├─ config/engine.yaml    # همه آستانه‌ها و پارامترها
│  └─ tests/
├─ frontend/                # Next.js + TS, RTL, فونت وزیرمتن
├─ infra/docker-compose.yml
└─ .github/workflows/
```

**هیچ README در ریشه ریپو توضیح محصول نمی‌دهد** (ریپو فعلاً عمومی است).

## اسکیما (جداول اصلی)

| جدول | نوع | کلید | ستون‌های کلیدی |
| --- | --- | --- | --- |
| `instruments` | عادی | `id` | `ins_code` (TSETMC)، `symbol_fa`, `name_fa`, `isin`, `market`, `board`, `instrument_type`, `sector_code`, `tags jsonb`, `listed_at`, `delisted_at` |
| `market_rules` | عادی | `id` | `market`, `rule`, `value jsonb`, `valid_from`, `valid_to`, `source_url` |
| `trading_calendar` | عادی | `(market, date)` | `is_open`, `halt_reason` |
| `prices_daily` | hypertable | `(instrument_id, date)` | OHLC، `last`, `close`, `prev_close`, `volume`, `value`, `trades`, `base_volume`, `limit_up`, `limit_down`, `status` |
| `prices_adjusted` | view/materialized | — | `adj_factor` تجمعی |
| `client_types_daily` | hypertable | `(instrument_id, date)` | حجم/ارزش/تعداد خرید و فروش حقیقی و حقوقی |
| `intraday_snapshots` | hypertable | `(instrument_id, ts)` | آخرین قیمت، حجم تجمعی، حقیقی/حقوقی تجمعی |
| `order_book_snapshots` | hypertable | `(instrument_id, ts)` | ۵ ردیف قیمت/حجم/تعداد هر طرف |
| `financial_statements` | عادی | `id` | `instrument_id`, `period_end`, `period_type`, `statement`, `items jsonb`, `version`, `codal_letter_id`, `published_at` |
| `monthly_activity` | عادی | `id` | فروش محصولات، `published_at`, `version` |
| `corporate_events` | عادی | `id` | `type`, تاریخ‌ها، `dps`, `increase_pct`, `source`, `payment_schedule jsonb` |
| `funds`, `fund_nav_daily` | عادی/hypertable | — | `trade_method`, `nav_issue`, `nav_redeem`, `aum`, `flow` |
| `futures_contracts`, `futures_daily` | عادی/hypertable | — | `underlying`, `expiry`, `settlement`, `open_interest` |
| `macro_series` | hypertable | `(series, source, ref_period)` | `value`, `release_date` |
| `news_raw` | عادی | `id` | `source`, `url`, `published_at`, `fetched_at`, `text`, `hash` |
| `events` | عادی | `id` | خروجی ساختاریافته [08](08-news-and-macro.md) |
| `features` | hypertable | `(instrument_id, date, feature_set_version)` | `values jsonb` یا ستونی (Parquet در MinIO برای آموزش) |
| `labels` | عادی | `(instrument_id, date, timeframe)` | `y`, `realized_return`, `exit_reason`, `exit_date` |
| `model_runs` | عادی | `id` | `timeframe`, `version`, `train_window`, `metrics jsonb`, `artifact_uri` |
| `signals` | عادی | `id` | فیلدهای [10 §۸](10-recommendation-engine.md) + `outcome` |
| `backtests` | عادی | `id` | پیکربندی، معیارها، `report_uri` |

## اصول

- **Point-in-time:** هر ردیف `published_at`/`release_date`/`fetched_at` دارد؛ ساخت ویژگی فقط با `<= as_of`.
- **زمان:** ذخیره UTC؛ نمایش Asia/Tehran و تاریخ شمسی (کتابخانه `jdatetime`).
- **نسخه:** صورت مالی اصلاحیه و مدل جدید هرگز بازنویسی نمی‌شوند.
- **قابلیت تکرار:** `data_snapshot_id` و `model_version` روی هر سیگنال.
- **میزبانی:** سرور ایران برای دسترسی پایدار به منابع داخلی؛ فاز ۲ ناحیه دوم خارج کشور.
