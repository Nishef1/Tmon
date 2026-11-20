# ۱۴ — اجرا روی PC

به‌روز: ۲۶ آبان ۱۴۰۵. همهٔ محاسبه روی PC انجام می‌شود و سرور فقط نمایش می‌دهد ([15-deploy](15-deploy.md)). Docker، Celery و Redis کنار گذاشته شده‌اند.

> همهٔ خروجی‌ها تحلیل فنی و آموزشی است، نه توصیهٔ سرمایه‌گذاری.

## پیش‌نیازها

- Python 3.13 با `backend/.venv` (`cd backend && uv sync`)، Node.js 26، pnpm 12 و `pnpm install` در `frontend/`.
- دسترسی به TSETMC و کدال فقط از `python.exe` (اسپلیت تونل برنامه‌ای VPN) ممکن است. `curl` روی همین ماشین به آن‌ها نمی‌رسد.

## محیط دادهٔ زنده

```bash
export TMON_DATABASE_URL="sqlite:///D:/Data/Tmon/data/tmon-live.sqlite3"
export TMON_OBJECT_STORE=file
export TMON_OBJECT_STORE_DIR="D:/Data/Tmon/data/objects"
```

همهٔ وضعیت در `data/` است (در `.gitignore`). متغیرهای دیگر (`TMON_HTTP_PROXY`، `TMON_INTRADAY_INTERVAL_SECONDS`، `TMON_BOOK_TOP_N`، `TMON_LLM_API_KEY`) در `backend/src/tmon/core/config.py` تعریف شده‌اند.

## چرخهٔ روزانه

دو کار زمان‌بندی‌شدهٔ ویندوز `backend/scripts/run_collectors.ps1` را اجرا می‌کنند:

| کار | زمان | دستور |
| --- | --- | --- |
| `Tmon-Intraday` | ساعت بازار | `python -m tmon.ingest.tsetmc.cli intraday --follow` |
| `Tmon-EOD` | ۱۹:۳۰، شنبه تا چهارشنبه (از ۱۴۰۵/۰۸/۲۵ به خواست مالک غیرفعال است؛ چرخه دستی اجرا می‌شود) | `run_collectors.ps1 -Eod` |

`-Eod` به‌ترتیب اجرا می‌کند:

1. `python -m tmon.tasks.cycle`: قیمت و حقیقی/حقوقی، شاخص‌ها، تابلو، اخزا، دلار و طلا و نفت، اخبار، ویژگی‌ها، وزن زنده، و آموزش و انتشار D1/W1/M1. گام D1 اجباری است و بقیه اختیاری. زمان هر گام در `data-health` ثبت می‌شود.
2. `python -m tmon.tools.v2_ranking`، سپس `turning_points`، `stock_drivers`، `industry_map`، `ta_signals`، `entry_odds` و `regime_paper` (وضع بازار و آزمون کاغذی برنامهٔ سه‌وضعی). هر کدام یک سند `v2/*.json` می‌نویسد.
3. `python -m tmon.ingest.codal.cli events` و `meetings`؛ پنج‌شنبه‌ها `tmon.ingest.tsetmc.cli info` (EPS و P/E گروه).

بعد از پایان چرخه: `bash deploy/sync-data.sh`.

اجرای دستی همان چرخه: `powershell -File backend/scripts/run_collectors.ps1 -Eod`.

روی هر ماشین فقط یک چرخه اجرا می‌شود. `tmon.tasks.cycle` قفل فایلی `tmon-cycle.lock` (کنار `TMON_OBJECT_STORE_DIR`) می‌گیرد؛ اگر چرخهٔ دیگری آن را دارد، پیام «another cycle is already running» می‌دهد و با کد ۲ خارج می‌شود، و `run_collectors.ps1` هم گام‌های بعدی را اجرا نمی‌کند. قفل با مردن فرایند آزاد می‌شود، پس چرخهٔ کشته‌شده راه بعدی را نمی‌بندد.

## فرمان‌های جداگانه (از `backend/`)

```bash
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli probe          # سلامت دسترسی و قالب پاسخ‌ها
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli eod            # قیمت دسته‌ای و حقیقی/حقوقی سراسری
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli eod --full     # همهٔ نمادها یکی‌یکی (حدود یک ساعت)
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli backfill --since 2021-01-01 --limit 20
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.book_history --top 100 --days 365 --extra-types etf_leveraged  # تابلو و برش روزانه، صندوق‌های اهرمی هم
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.dated_holders --top 100 --months 36   # تعداد سهام و سهامداران اول هر ماه
.venv/Scripts/python.exe -m tmon.ingest.macro.fund_sites                           # تاریخچهٔ NAV و ترکیب دارایی از سایت صندوق‌ها
.venv/Scripts/python.exe -m tmon.ingest.codal.backfill --state ../data/codal-backfill-funds.json --types etf_equity etf_leveraged etf_fixed_income etf_commodity etf_mixed  # نامه‌های کدال صندوق‌ها
.venv/Scripts/python.exe -m tmon.ingest.tsetmc.cli statements --basket ../data/liquid-basket.json  # ترازنامه و سود و زیان ۱۰۰ نماد (حدود ۴ دقیقه)
.venv/Scripts/python.exe -m tmon.ingest.codal.cli letters --symbol فملی
.venv/Scripts/python.exe -m tmon.ingest.codal.cli reports --code ن-۳۰ --limit 20
.venv/Scripts/python.exe -m tmon.tools.adapt_cycle [--replay]
.venv/Scripts/python.exe -m tmon.tools.autopilot
.venv/Scripts/python.exe -m tmon.tools.data_audit
```

- جست‌وجوی کدال پس از چند ده درخواست پاسخ 429 می‌دهد. دستور با همان داده متوقف می‌شود و اجرای بعدی ادامه می‌دهد ([OPEN_QUESTIONS](OPEN_QUESTIONS.md) ۷۱). صفحهٔ کپچای `Decision.aspx` دور زده نمی‌شود؛ بدنهٔ گزارش از خروجی Excel خوانده می‌شود (۷۵).
- دریافت لحظه‌ای هر ۳۰ ثانیه یک درخواست دیدبان می‌فرستد و فقط نمادهایی را که حجمشان تغییر کرده ذخیره می‌کند. صف ۵ سطحی فقط برای ۱۵ نماد پرمعامله گرفته می‌شود.

## سرور API و وب روی PC

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn tmon.api.main:app --port 8000
cd frontend && pnpm dev        # http://127.0.0.1:3000 ، NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## دمو و شبیه‌ساز (بدون شبکه)

- `backend/.venv/Scripts/python.exe backend/scripts/run_demo.py`: دیتابیس مصنوعی `demo/tmon-demo.sqlite3`، API و وب. نمادها «نمونه N» هستند و آستانه‌ها فقط در `demo_db.py` شل شده‌اند. چیزی دربارهٔ بازار واقعی نمی‌گوید.
- `backend/.venv/Scripts/python.exe backend/scripts/run_live.py --stand-in`: سرور ساختگی TSETMC (`tmon.devtools.fake_tsetmc`) با قالب پاسخ‌های واقعی. فقط ثابت می‌کند کد با این قالب‌ها کار می‌کند.

## تست و بررسی

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
cd backend && uv run pytest -m network         # فقط از شبکه‌ای که به TSETMC می‌رسد
cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

همین‌ها در `.github/workflows/ci.yml` اجرا می‌شوند. CI همچنین بررسی می‌کند که `frontend/openapi.json` و `frontend/lib/api-schema.ts` با API بخوانند.
