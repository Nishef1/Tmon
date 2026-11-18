# ۱۱ — معماری و مدل داده

به‌روز: ۲۶ آبان ۱۴۰۵. این سند همان چیزی را می‌گوید که در کد هست. اگر با کد نخواند، کد درست است و این سند باید اصلاح شود.

## اجزا

| جزء | کجا | چه می‌کند |
| --- | --- | --- |
| پایگاه داده | SQLite (`TMON_DATABASE_URL`)، مهاجرت با Alembic در `backend/migrations` | همهٔ جدول‌های پایین |
| ذخیره‌ساز فایل | `TMON_OBJECT_STORE=file`، پوشهٔ `TMON_OBJECT_STORE_DIR` (`storage/objectstore.py`) | payload خام، snapshot مدل‌ها، و سندهای JSON که API می‌خواند (`v2/*.json`، `models/`، `scores/`، `data-health/`) |
| API | FastAPI، `backend/src/tmon/api` (روترها در `api/routers`) | فقط می‌خواند و جمله می‌سازد؛ هیچ محاسبهٔ سنگینی ندارد |
| وب | Next.js، `frontend/app` | صفحه‌ها؛ نوع‌های API از `frontend/openapi.json` ساخته می‌شوند (`pnpm gen:api`) |
| چرخهٔ روزانه | `python -m tmon.tasks.cycle` و ابزارهای `tmon.tools.*` (از `backend/scripts/run_collectors.ps1 -Eod`) | گرفتن داده تا انتشار؛ روی PC |
| پایشگر | `python -m tmon.portfolio.monitor` (روی سرور، `tmon-monitor.service`) | در ساعت بازار هشدار فوری پرتفوی و نوار لحظه‌ای |
| سرور | systemd روی VPS: `tmon-api`، `tmon-web`، `tmon-monitor`، nginx | فقط نمایش؛ داده از PC با `deploy/sync-data.sh` می‌آید ([15-deploy](15-deploy.md)) |

Docker، Postgres، Redis و Celery کنار گذاشته شده‌اند. ذخیره‌ساز MinIO هنوز در `storage/objectstore.py` به‌عنوان گزینه هست، ولی PC و سرور هر دو `TMON_OBJECT_STORE=file` دارند.

## بسته‌های بک‌اند (`backend/src/tmon`)

| بسته | نقش |
| --- | --- |
| `core` | تنظیمات (`config.py`، `engine_config.py` برای `config/engine.yaml`)، اتصال پایگاه داده، زمان |
| `domain` | قواعد بازار (`rules.py`: کارمزد، دامنه، ساعت)، تقویم، مجمع، مقایسه با تورم |
| `storage` | مدل‌های SQLAlchemy (`models.py`)، seed قواعد، ذخیره‌ساز فایل |
| `ingest` | `tsetmc` (قیمت، حقیقی/حقوقی، تابلو، لحظه‌ای)، `codal`، `macro` (fipiran، tgju، yahoo، تورم)، `news` |
| `features` | ساخت ویژگی‌ها، تعدیل قیمت، اندیکاتورها، تابلو، کیفیت داده |
| `labeling` | برچسب triple-barrier و نسبی (v1) |
| `models` | LightGBM، تقسیم walk-forward، توضیح SHAP (v1) |
| `engine` | دروازه‌ها، آستانه‌ها، حالت دفاعی، مواجهه، وزن زنده (`adapt.py`)، رژیم، حکم هر نماد (`verdict.py`: توابع خالص روی سندهای ذخیره‌شده) |
| `backtest` | بک‌تست و مطالعه‌ها؛ هر گزارش `docs/reports` از یکی از این‌ها می‌آید |
| `tools` | خروجی‌های روزانه برای API: `v2_ranking`، `turning_points`، `stock_drivers`، `ta_signals`، `entry_odds`، `adapt_cycle`، `autopilot`، `data_health` |
| `portfolio` | پرتفوی: دفتر، مفید، توصیه، پیش‌بینی بازه، هشدار، گزارش پیش از گشایش، پایشگر |
| `tasks` | چرخهٔ روزانه و زمان‌بندی آن |
| `api` | FastAPI و روترها |

جهت مجاز وابستگی‌ها را `backend/tests/test_layering.py` نگه می‌دارد: یال تازه بین بسته‌ها تست را می‌شکند.

## جریان داده

```
TSETMC / کدال / fipiran / tgju / yahoo / RSS
  → ingest (+ payload خام در ذخیره‌ساز)
  → prices_daily, client_types_daily, order_book_daily, codal_*, macro_series, news_*
  → features (جدول features)
  → tools (v2/*.json در ذخیره‌ساز)
  → api → وب
```

هر سند `v2/*.json` یک نسخه از داده است. API آن را بدون کش زمانی می‌خواند و تازگی را با روز داده می‌سنجد، نه با ساعت.

## جدول‌ها (`storage/models.py`)

| گروه | جدول‌ها |
| --- | --- |
| نماد و قواعد | `instruments`، `sector_names` (هر بار که حلقهٔ لحظه‌ای شروع می‌شود از `GetStaticData` تازه می‌شود)، `market_rules`، `trading_calendar` |
| بازار روزانه | `prices_daily`، `price_adjustments`، `client_types_daily`، `market_index_daily`، `order_book_daily`، `intraday_profile_daily` |
| لحظه‌ای | `intraday_snapshots`، `order_book_snapshots` |
| رویداد و کدال | `corporate_events`، `share_changes`، `shareholders`، `financial_statements`، `codal_letters`، `codal_reports`، `codal_report_cells` |
| کلان، صندوق، خبر | `macro_series`، `fund_nav`، `news_raw`، `news_events` |
| ویژگی و مدل v1 | `features`، `labels`؛ و `model_runs`، `signals`، `signal_runs`، `backtests` که از ۲۸ آبان ۱۴۰۵ فقط سابقه‌اند |
| پرتفوی | `portfolios`، `holdings`، `portfolio_trades`، `broker_links`، `portfolio_alerts`، `portfolio_briefings`، `tracked_picks` |
| خام | `raw_payloads` |

هر ردیف دریافتی `source_url` و `fetched_at` دارد. قیمت‌ها خام ذخیره می‌شوند و تعدیل هنگام خواندن اعمال می‌شود (`price_adjustments`).
