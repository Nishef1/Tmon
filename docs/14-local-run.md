# اجرای محلی بدون Docker

این سند دو حالت را توضیح می‌دهد: **دموی مصنوعی** (برای دیدن رابط، بدون هیچ دسترسی شبکه) و **اجرای زنده** (داده واقعی TSETMC، از شبکه‌ای که به آن دسترسی دارد). مسیر تولید همچنان Docker Compose است ([11](11-architecture-and-data-model.md)).

> همهٔ خروجی‌ها تحلیل فنی و آموزشی است، نه توصیه سرمایه‌گذاری.

## پیش‌نیازها

- Python 3.13 با محیط `backend/.venv` (با `uv sync` ساخته می‌شود)، Node.js 26، pnpm 12 و `pnpm install` در `frontend/`.
- پایگاه‌داده SQLite و ذخیره‌ساز فایلی جای PostgreSQL/TimescaleDB، Redis و MinIO را می‌گیرند. برای حجم کامل بازار و استفادهٔ چندکاربره از Compose استفاده کنید.

## دموی مصنوعی (یک دستور)

از ریشهٔ پروژه:

```bash
backend/.venv/Scripts/python.exe backend/scripts/run_demo.py
```

- اولین اجرا دیتابیس دمو (`demo/tmon-demo.sqlite3`) و بیلد فرانت را می‌سازد (چند دقیقه)؛ اجراهای بعدی فوری است.
- رابط روی <http://127.0.0.1:3000> و مستندات API روی <http://127.0.0.1:8000/docs> باز می‌شود. `Ctrl+C` هر دو را می‌بندد.
- گزینه‌ها: `--rebuild` (ساخت دوباره)، `--no-browser`.
- **داده کاملاً مصنوعی است:** نمادها «نمونه N» هستند و قیمت‌ها گام تصادفی با لبهٔ کاشته‌شده‌اند. چیزی دربارهٔ بازار واقعی نمی‌گویند.
- برای اینکه کارت توصیه دیده شود، فقط در اسکریپت دمو آستانه‌ها شل شده‌اند (`margin=-1`، `p_floor=0.15`، `ev_min_abs=0` در `backend/scripts/demo_db.py`؛ آستانهٔ واقعی طبق [ADR 0002](adr/0002-engine-and-data-decisions.md) سربه‌سر + ۰٫۰۵ با کف ۰٫۳۵ و EV خالص ≥ ۰٫۵٪ است). با آستانه‌های واقعی روی داده مصنوعی توصیه‌ای نمی‌آید و دروازهٔ سطح A بسته می‌ماند.

اجزا: `backend/scripts/demo_db.py` (ساخت دیتابیس)، `serve_demo.py` (API)، `run_demo.py` (همه با هم).

## اجرای زنده با داده واقعی TSETMC (یک دستور)

> **وضعیت راستی‌آزمایی:** نشانی‌ها و ستون‌های TSETMC از کلاینت‌های مرجع (pytse-client و finpy-tse) گرفته شده‌اند و **هنوز روی سرویس واقعی راستی‌آزمایی نشده‌اند**؛ سرویس از ماشین ساخت در دسترس نبود. به همین دلیل قدم اول همیشه `probe` است که همین را روی شبکهٔ شما می‌سنجد. ← [OPEN_QUESTIONS](OPEN_QUESTIONS.md) بندهای ۴۸ تا ۵۶.

از ریشهٔ پروژه، **از شبکه‌ای که به tsetmc.com دسترسی دارد**:

```bash
backend/.venv/Scripts/python.exe backend/scripts/run_live.py
```

این دستور به‌ترتیب:

1. **probe**: دسترسی، فهرست بازار، قیمت‌های لحظه‌ای، تاریخچهٔ روزانه، حقیقی/حقوقی، اطلاعات نماد و صف خرید/فروش را می‌سنجد و ستون‌های «بازار لحظه‌ای» را با آخرین کندل تاریخچه تطبیق می‌دهد. اگر شبکه در دسترس نباشد با پیام روشن متوقف می‌شود و چیزی ساخته نمی‌شود.
2. **بک‌فیل** (بار اول، طولانی): فهرست نمادها و تاریخچهٔ روزانه از `--since` (پیش‌فرض ۵ سال). اجراهای بعدی فقط چند روز اخیر را تازه می‌کنند (`eod`).
3. ویژگی‌ها ← آموزش و انتشار سیگنال‌های امروز (`train_and_publish`).
4. بیلد فرانت (در صورت نبود)، سپس **API**، **رابط وب** (<http://127.0.0.1:3000>) و **دریافت لحظه‌ای** (`intraday --follow`) هم‌زمان بالا می‌آیند. `Ctrl+C` همه را می‌بندد.

گزینه‌ها: `--backfill` (بازسازی کامل تاریخچه)، `--since YYYY-MM-DD`، `--limit N` (فقط N نماد اول؛ برای آزمایش سریع)، `--skip-probe`، `--no-browser`.

### فایل‌ها و تنظیمات

- همهٔ وضعیت در `data/` است (در `.gitignore`): `tmon-live.sqlite3`، ذخیره‌ساز فایلی `data/objects/` برای payload خام و عکس‌های فوری، و نشانهٔ `.backfilled`. با حذف پوشه از صفر شروع می‌شود.
- متغیرهای محیطی (پیشوند `TMON_`): `TMON_HTTP_PROXY` (پروکسی خروجی خودتان، اگر شبکه‌تان لازم دارد؛ ما خودمان هیچ پروکسی ثالثی نمی‌گذاریم و محدودیت جغرافیایی را دور نمی‌زنیم)، `TMON_INTRADAY_INTERVAL_SECONDS` (پیش‌فرض ۳۰)، `TMON_BOOK_TOP_N` (پیش‌فرض ۱۵)، `TMON_OBJECT_STORE=file|minio`، `TMON_OBJECT_STORE_DIR`.

### فرمان‌های جداگانه

```bash
cd backend
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli probe
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli backfill --since 2021-01-01 --limit 20
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli eod
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli intraday --once --force
```

### دریافت لحظه‌ای: چه می‌کند و چه نمی‌کند

- هر ۳۰ ثانیه یک درخواست «دیدبان بازار» برای کل بازار؛ فقط نمادهایی که حجمشان تغییر کرده در `intraday_snapshots` ذخیره می‌شوند. payload خام هر ۱۰ بار دریافتِ یک‌بار نگه داشته می‌شود.
- صف خرید/فروش ۵ سطحی فقط برای ۱۵ نماد پرمعامله‌تر لحظه (نه ۷۰۰ نماد) گرفته می‌شود تا از سقف نرخ درخواست رد نشویم.
- فقط در ساعت معاملات (`market_rules.trading_hours`، به وقت تهران) کار می‌کند؛ با `--follow` بیرون از ساعت منتظر می‌ماند و در بازگشایی ادامه می‌دهد. روزهای تعطیل مدل نشده‌اند؛ در آن روزها معاملهٔ جدیدی نیست و ردیفی ذخیره نمی‌شود.
- در رابط، صفحهٔ هر نماد بخش «قیمت لحظه‌ای» دارد که هر ۱۵ ثانیه `/instruments/{id}/live` را می‌خواند: آخرین قیمت، تغییر نسبت به پایانی دیروز، حجم، ۵ سطح صف و **سن داده**. داده‌ای قدیمی‌تر از ۵ دقیقه با هشدار «قدیمی» نمایش داده می‌شود و اگر چیزی ذخیره نشده باشد صریحاً همین گفته می‌شود. این مقادیر آخرین چیزی‌اند که دریافت‌کننده نوشته، نه عبور مستقیم از بورس.
- با Docker، همین کار تسک Celery `snapshot_intraday` است که هر دقیقه در ساعت ۹ تا ۱۲ زمان‌بندی می‌شود.

### چه چیزی راستی‌آزمایی شده است

- منطق ما (تجزیه، تشخیص تغییر، ساعت معاملات، حکم probe، ذخیره‌ساز فایلی، API و پنل) با تست‌های خودکار روی payloadهای **ساختگی** دنبال‌کنندهٔ چیدمان مرجع آزموده شده است.
- پاسخ واقعی TSETMC در هیچ تستی دیده نشده است. تا اجرای `probe` و گزارش سبز آن روی شبکهٔ شما، به ستون‌ها و نشانی‌ها اعتماد نکنید. تست‌های `pytest -m network` همین را بعد از دسترسی بررسی می‌کنند.

## اجرای زنده روی «شبیه‌ساز TSETMC» (وقتی سایت اصلی در دسترس نیست)

```bash
backend/.venv/Scripts/python.exe backend/scripts/run_live.py --stand-in
```

یک سرور محلی **مصنوعی** (`tmon.devtools.fake_tsetmc`) با همان قالب پاسخ‌های مرجع بالا می‌آید و کل زنجیره روی HTTP واقعی اجرا می‌شود: probe ← بک‌فیل ← ویژگی‌ها ← مدل ← API و وب ← دریافت لحظه‌ای (قیمت و صف خرید/فروش در صفحهٔ هر نماد تازه می‌شود). داده در `data/standin/` است و **داده بازار نیست**؛ فقط ثابت می‌کند کد ما با قالب‌های مستند کار می‌کند. همین سرور را می‌توان جدا اجرا کرد: `python -m tmon.devtools.fake_tsetmc [--live]` و با `TMON_TSETMC_OLD_URL` / `TMON_TSETMC_CDN_URL` به آن اشاره داد.

## مسیر تولید: Docker Compose

این مسیر همان چیزی است که در ADR 0001 ثابت شده: PostgreSQL/TimescaleDB، Redis، MinIO، API، Celery worker، Celery beat و فرانت.

### بالا آوردن

```bash
cp .env.example .env          # مقدارها را عوض کنید؛ .env هرگز commit نمی‌شود
cd infra
docker compose --env-file ../.env up -d --build
docker compose --env-file ../.env ps    # همه باید healthy یا Up باشند
```

- مهاجرت‌ها را خود سرویس `backend` پیش از بالا آمدن اجرا می‌کند (`alembic upgrade head`). سرویس‌های `worker` و `beat` فقط پس از سالم شدن `backend` شروع می‌شوند.
- پورت‌های میزبان: ۸۰۰۰ (API)، ۳۰۰۰ (رابط)، ۵۴۳۲ (PostgreSQL)، ۶۳۷۹ (Redis)، ۹۰۰۰ و ۹۰۰۱ (MinIO). اگر پورتی اشغال است، قبل از `up` آن را آزاد کنید یا نگاشت را در `infra/docker-compose.yml` عوض کنید.
- تصویر MinIO: ایمیج رسمی `minio/minio` دیگر روی Docker Hub نیست، پس `chainguard/minio` استفاده شده. ← [OPEN_QUESTIONS](OPEN_QUESTIONS.md) (تصویر MinIO).
- دسترسی به TSETMC باید از داخل کانتینر باز باشد (Docker Desktop معمولاً از همان شبکهٔ میزبان خارج می‌شود). بررسی: `docker compose --env-file ../.env exec -T backend python -m tmon.ingest.tsetmc.cli probe`.

### دادهٔ اولیه

پایگاه‌دادهٔ Compose خالی شروع می‌شود. یک بار:

```bash
docker compose --env-file ../.env exec -T backend sh -c \
  "python -m tmon.ingest.tsetmc.cli backfill --since 2021-11-01 && \
   python -m tmon.ingest.tsetmc.cli indices && \
   python -m tmon.ingest.tsetmc.cli risk-free && \
   python -m tmon.ingest.tsetmc.cli reclassify"
```

بک‌فیل کامل ساعت‌ها طول می‌کشد؛ `--limit N` فقط N نماد اول را می‌گیرد (برای آزمایش).

### زمان‌بندی روزانه (Celery beat، به وقت تهران)

| تسک | زمان | نقش |
|---|---|---|
| `ingest-instruments-daily` | ۰۷:۳۰ | تازه‌سازی فهرست نمادها |
| `snapshot-intraday` | هر دقیقه، ساعت ۹ تا ۱۲ | یک دریافت لحظه‌ای |
| `daily-cycle-tick` | هر ۵ دقیقه، روزهای `TMON_SCHEDULE_DAYS` | چرخهٔ پایان روز، فقط یک بار در هر روز |

زمان چرخهٔ پایان روز **ثابت نیست**: از `market_rules` خوانده می‌شود. پایان آخرین نشست (جلسهٔ پایانی `closing_session_tal`، وگرنه `trading_hours`) به‌علاوهٔ `TMON_EOD_DELAY_MINUTES` (پیش‌فرض ۳۰) = لحظهٔ آماده بودن. با قوانین فعلی ۱۳:۳۰. هر بار که tick اجرا می‌شود و چرخهٔ امروز آماده و ادعا‌نشده باشد، آن را در Redis (`tmon:cycle:<تاریخ>:lock`) ادعا می‌کند و به‌ترتیب اجرا می‌کند:

1. `ingest_eod`: قیمت‌ها و حقیقی/حقوقی
2. `indices` و `risk_free`: شاخص‌ها و بازده اخزا (اختیاری؛ شکستشان چرخه را متوقف نمی‌کند)
3. `features`
4. `publish_and_resolve_outcomes`: آموزش/انتشار سیگنال‌های امروز و تعیین نتیجهٔ سیگنال‌های قدیمی

اگر یک گام اجباری شکست بخورد ادعا آزاد می‌شود و tick بعدی دوباره تلاش می‌کند، حداکثر `TMON_CYCLE_MAX_ATTEMPTS` (پیش‌فرض ۳) بار در روز. پس از موفقیت `tmon:cycle:<تاریخ>:done` ثبت می‌شود و tick‌های بعدی همان روز چیزی اجرا نمی‌کنند.

### دیدن یک چرخه در لاگ

```bash
docker compose --env-file ../.env logs -f worker | grep "cycle day="
```

هر گام `status=start` و `status=ok seconds=… result=…` (یا `failed`) دارد و پایان چرخه `status=complete` است. وضعیت ادعا:

```bash
docker compose --env-file ../.env exec redis redis-cli --scan --pattern 'tmon:cycle:*'
```

### تعطیلی و خرابی

- روز تعطیل یا بدون معامله: ingest چیزی جدید نمی‌گیرد؛ چرخه همچنان اجرا و «توصیه‌ای برای امروز نیست» را منتشر می‌کند. تقویم تعطیلات هنوز مدل نشده است (← OPEN_QUESTIONS).
- اگر `ingest_eod` به‌خاطر شبکه شکست بخورد، لاگ `status=failed` با خطا می‌دهد و ادعا آزاد می‌شود؛ اصلاح شبکه و منتظر tick بعدی بمانید.
- توقف: `docker compose --env-file ../.env down` (داده در volumeها می‌ماند؛ `down -v` همه را پاک می‌کند).
