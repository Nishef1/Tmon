# تغییرات

## M0 — اسکلت (۲۰ آبان ۱۴۰۵)

- ساختار ریپو طبق [11](11-architecture-and-data-model.md): `backend/` (uv، Python 3.12)، `frontend/` (Next.js 16، TypeScript، Tailwind 4، RTL و وزیرمتن)، `infra/docker-compose.yml`، `.github/workflows/ci.yml`.
- هسته: تنظیمات از محیط، بارگذاری تایپ‌شده `config/engine.yaml`، زمان UTC با نمایش تهران و شمسی.
- اسکیمای اصلی و مهاجرت Alembic با hypertable در TimescaleDB.
- CI: ruff، mypy، pytest، eslint، tsc، vitest، build.
- **انحراف:** `docker compose up` اجرا نشد (دیمن Docker خاموش)؛ فقط اعتبار فایل بررسی شد. ← [OPEN_QUESTIONS](OPEN_QUESTIONS.md)
- **انحراف:** جدول `price_adjustments` و `raw_payloads` و `signal_runs` به اسکیما افزوده شد (تعدیل مشتق‌شده، فهرست پاسخ‌های خام، روزهای «پیشنهادی نیست»).

## M1 — دریافت داده (۲۰ آبان ۱۴۰۵)

- کلاینت HTTP مؤدب: محدودیت نرخ به‌ازای دامنه، backoff نمایی با jitter، بازتلاش روی ۴۲۹ و ۵xx.
- پاسخ خام پیش از تجزیه در MinIO ذخیره و در `raw_payloads` نمایه می‌شود؛ هر رکورد `source_url` و `fetched_at` دارد.
- پارسرها (فهرست بازار، تاریخچهٔ روزانه، حقیقی/حقوقی، اطلاعات نماد، پنج سطح سفارش) کاملاً خالص و بدون شبکه؛ طبقه‌بندی نوع نماد با `config/instrument_types.yaml`.
- `market_rules` با تاریخ اعتبار seed می‌شود؛ `CostModel` و `RuleBook` هیچ مقدار بازاری را سخت‌کد نمی‌کنند.
- تقویم معاملاتی از فعالیت مشاهده‌شده + بازهٔ توقف بازار؛ روزهای توقف علامت می‌خورند و پر نمی‌شوند.
- تعدیل قیمت برداری (Polars) با ثابت‌شدن «بازده تعدیل‌شده = close/prev_close − 1» (تست hypothesis).
- CLI: `python -m tmon.ingest.tsetmc.cli backfill|eod`؛ تسک‌های Celery برای EOD.
- ۳۷ تست واحد/یکپارچه (HTTP با respx، خط لولهٔ کامل روی SQLite) + ۵ تست `@pytest.mark.network` که در CI رد می‌شوند.
- **تأییدنشده:** بازهٔ ≥ ۵ سال تاریخچه و مقایسهٔ تعدیل با مرجع برای ۲۰ نماد (معیار پذیرش M1) بدون دسترسی به TSETMC قابل اجرا نبود. ← [OPEN_QUESTIONS](OPEN_QUESTIONS.md)

## M2 — ویژگی‌ها (۲۰ آبان ۱۴۰۵)

- اندیکاتورهای [04](04-technical-and-orderbook.md) به‌صورت برداری (Polars، بدون حلقهٔ سطری): SMA/EMA، MACD، ADX، ایچیموکو، RSI (Wilder)، استوکاستیک، Williams %R، ROC، بولینگر، ATR، نوسان تحقق‌یافته، OBV، MFI، ساختار (سقف/کف، شکست با حجم، پیوت).
- ویژگی‌های تابلوخوانی: `ind_buy_power`، `ind_net_flow(_z)`، `inst_to_ind`، `rel_volume`، `vol_to_base`، `smart_money_flag`، `last_close_gap`، `queue_state`/`days_in_queue`، `intraday_range_pos`، `ret/limit_pct`؛ و ویژگی‌های بازار/صنعت (breadth، جریان پول حقیقی کل بازار).
- همهٔ ویژگی‌ها بدون مقیاس‌اند (نسبت/نوسان‌نما)، تا تعدیل‌های بعدی تاریخچه را تغییر ندهند. `FeatureSet` نسخه‌دار و تفکیک‌شده بر اساس تایم‌فریم (فقط D1)، با اثرانگشت ستون‌ها.
- ذخیرهٔ ویژگی‌ها در جدول `features` (JSON)، خروجی Parquet برای آموزش، و تسک Celery روزانه.
- تست‌ها: مقایسه با پیاده‌سازی مرجع ساده (حلقه‌ای) برای هر اندیکاتور، مثال منتشرشدهٔ RSI، ثابت‌بودن نسبت به مقیاس قیمت، و **تست نشت (point-in-time)** با دو روش: برش دادهٔ آینده و جایگزینی دادهٔ آینده با نویز (به‌همراه تست «آشکارساز واقعاً کار می‌کند»).
- حین نوشتن تست نشت، ناپایداری عددی در تصمیم +DM/−DM هنگام تساوی پیدا و با تلورانس نسبی رفع شد.
- کارایی: ۶۰۰ هزار ردیف × ۹۰ ستون در حدود ۰٫۷ ثانیه.
