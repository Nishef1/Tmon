# ۱۲ — نقشه راه و معیار پذیرش

هر مرحله فقط وقتی «تمام» است که معیار پذیرشش با تست یا گزارش اثبات شده باشد.

## وضعیت فاز ۱ (۲۲ آبان ۱۴۰۵)

| مرحله | وضعیت | شواهد |
| --- | --- | --- |
| M0 | تمام | Compose روی ماشین مالک بالا آمد ([docs/14](14-local-run.md)، [OQ ۱](OPEN_QUESTIONS.md)) |
| M1 | تمام | تاریخچه ۲۰۲۱-۱۱ تا ۲۰۲۶-۱۱، ۲٬۶۲۸ نماد؛ [adjustment-check](reports/adjustment-check.md)؛ شاخص‌ها و اخزا ([risk-free-check](reports/risk-free-check.md)) |
| M2 | تمام | تست فرمول‌ها و ضد look-ahead (`backend/tests/test_features.py`) |
| M3 | تمام | [m3-baseline-d1-real](reports/m3-baseline-d1-real.md) |
| M4 | ساخته شد، معیار برآورده نشد | [m4-lgbm-d1-real](reports/m4-lgbm-d1-real.md): مدل از baseline بهتر نیست؛ دروازهٔ سطح A بسته است و توصیه‌ای منتشر نمی‌شود |
| M5 | تمام | API و رابط RTL؛ Vitest و Playwright سبز ([CHANGELOG](CHANGELOG.md)) |
| M6 | بخشی | W1 و M1: [W1](reports/m4-lgbm-w1-real.md)، [M1](reports/m4-lgbm-m1-real.md) (از baseline بهتر نیستند)؛ کدال و مجمع ساخته شد؛ ویژگی بنیادی به‌دلیل پوشش گزارش‌ها مسدود ([OQ ۷۷](OPEN_QUESTIONS.md)) |
| M7 | بخشی | صفحهٔ مقایسه با تورم، دلار و طلا، NAV و حباب صندوق، خط لولهٔ خبر؛ [ablation-w1](reports/ablation-w1.md): گروه بازار حذف شد، کلان کمکی نکرد. بورس کالا و تورم رسمی مسدود ([OQ ۷۹، ۸۰](OPEN_QUESTIONS.md)) |
| M8 | تمام | همهٔ واژه‌های [glossary.md](glossary.md) در سایت (`frontend/tests/glossary.test.ts`)؛ صفحهٔ «دقت زنده»؛ کلید قطع Brier و حالت دفاعی |

تصمیم‌های باز مالک: [OPEN_QUESTIONS — تصمیم‌های باز مالک](OPEN_QUESTIONS.md#تصمیم‌های-باز-مالک).

| مرحله | خروجی | معیار پذیرش |
| --- | --- | --- |
| M0 — اسکلت | ساختار ریپو، Docker Compose (Postgres+Timescale، Redis، MinIO)، CI با ruff/mypy/pytest | `docker compose up` سالم؛ CI سبز |
| M1 — داده بازار | ingest نمادها، قیمت روزانه تاریخی، حقیقی/حقوقی، تعدیل‌ها از TSETMC؛ تقویم معاملاتی؛ `market_rules` | ≥ ۵ سال سابقه برای همه نمادهای فعال؛ تست تطبیق قیمت تعدیل‌شده با مرجع برای ۲۰ نماد |
| M2 — ویژگی تکنیکال و تابلو | ماژول‌های [04](04-technical-and-orderbook.md) | تست واحد هر فرمول با مقدار مرجع؛ تست ضد look-ahead |
| M3 — برچسب و baseline | triple-barrier، موتور بک‌تست walk-forward با هزینه، baseline قاعده‌محور D1 | گزارش بک‌تست HTML با معیارهای [10 §۹](10-recommendation-engine.md) |
| M4 — مدل D1 | LightGBM + کالیبراسیون، رتبه‌بندی EV، اندازه پوزیشن | Brier بهتر از baseline؛ بازده خالص پس از هزینه بهتر از baseline و شاخص هم‌وزن در دوره تست |
| M5 — API و داشبورد | FastAPI؛ Next.js RTL: صفحه پیشنهاد روز با انتخاب تایم‌فریم، صفحه نماد، تاریخچه سیگنال و دقت | E2E Playwright سبز؛ موبایل‌پسند |
| M6 — بنیادی و مجامع | کدال، نسبت‌ها، گزارش ماهانه، معادله مجمع؛ مدل‌های W1 و M1 | همان معیار M4 برای W1 و M1 |
| M7 — کلان، خبر، صندوق، کالا | [06](06-funds.md)، [07](07-commodity-and-futures.md)، [08](08-news-and-macro.md)، [09](09-sectors-and-allocation.md) | افزایش معنادار معیارها در ablation؛ صفحه مقایسه با تورم |
| M8 — آکادمی و پایش | واژه‌نامه از [glossary.md](glossary.md)، داشبورد دقت زنده، کلید قطع | هر عدد UI به مدخل آکادمی لینک دارد |
| فاز ۲ — بین‌الملل | `instruments.market` جدید، فیدهای مجاز (مثلاً Polygon، Alpha Vantage، Binance API)، تقویم و منطقه زمانی | بررسی حقوقی دسترسی و پرداخت پیش از شروع |

ترتیب اولویت با هدف فعلی: **M0 → M1 → M2 → M3 → M4 → M5** یک محصول قابل استفاده D1 می‌دهد؛ بقیه بعد از آن.
