# گزارش‌ها

هر گزارش نتیجهٔ یک اجرای واقعی روی داده است، با تاریخ همان اجرا. گزارش‌ها بازنویسی نمی‌شوند: وقتی نتیجه عوض شود، گزارش تازه نوشته می‌شود و این فهرست به‌روز می‌شود. گزارش‌هایی که کد در `backend/src/tmon` به آن‌ها ارجاع می‌دهد یا تولیدشان می‌کند با * علامت خورده‌اند.

## موتور و دروازه‌ها

| گزارش | چه می‌گوید |
| --- | --- |
| [research-engine-v2](research-engine-v2.md) | چرا v1 شکست خورد و طراحی v2 (پایهٔ ADR 0003). مرور است، نه بک‌تست |
| [m3-baseline-d1-real](m3-baseline-d1-real.md) | baseline قاعده‌محور D1 روی دادهٔ واقعی |
| [m4-lgbm-d1-real](m4-lgbm-d1-real.md)، [w1](m4-lgbm-w1-real.md)، [m1](m4-lgbm-m1-real.md) | LightGBM در سه افق از baseline بهتر نیست |
| [ablation-w1](ablation-w1.md) * | حذف گروه ویژگی‌ها: گروه بازار حذف شد، کلان کمکی نکرد |
| [r0-survivorship](r0-survivorship.md) | سوگیری بقا: کران بدبینانه، G6 رفع نشد |
| [r1-signal-decay](r1-signal-decay.md) | افت چهار سیگنال مبنا با افق |
| [r2-exposure-layer](r2-exposure-layer.md) | لایهٔ مواجهه: معیار با حاشیهٔ نازک برقرار |
| [r3-gates-complete-data](r3-gates-complete-data.md) | سبد مبنا روی دادهٔ کامل از ۲۰۱۹: G1، G4، G5 و G6 رد |
| [r3-gates-top100-liquid](r3-gates-top100-liquid.md)، [top100-own-index](r3-gates-top100-own-index.md)، [top50-liquid](r3-gates-top50-liquid.md)، [top50-own-index](r3-gates-top50-own-index.md) | همان دروازه‌ها روی سبدهای پرنقدشونده |
| [liquid-basket](liquid-basket.md) | محدود کردن جهان به ۱۰۰ و ۵۰ نماد پرمعامله |
| [walkforward-signals](walkforward-signals.md) | آزمون گام‌به‌گام سیگنال‌ها در پنج افق |
| [parameter-sweep](parameter-sweep.md) | پارامترها یکی‌یکی و ترکیبی |
| [adaptive-weights](adaptive-weights.md) | وزن‌دهی تطبیقی: هیچ روشی پایدار از وزن مساوی بهتر نشد |
| [deep-learning](deep-learning.md) | MLP، GRU، TCN و دیفیوژن: هیچ‌کدام از دروازه نگذشتند؛ فقط GBM در افق ۵ روی کل دوره |
| [combined-strategy-and-critique-2026-11-16](combined-strategy-and-critique-2026-11-16.md) | راهبرد ترکیبی چندسیگنالی و خودنقد دور دوم |
| [v2-ranking-page](v2-ranking-page.md) | صفحهٔ «خرید / نگهداری / پرهیز» |
| [project-audit-2026-11-16](project-audit-2026-11-16.md) | بازبینی کد (نه بک‌تست): چرا سایت هرگز «خرید» نمی‌گوید، نقص‌های شبیه‌ساز سبد و مهندسی؛ پایهٔ ADR 0004 |
| [invested-book-2026-11-17](invested-book-2026-11-17.md) | ADR 0004 مرحلهٔ ۲: سبد همیشه سرمایه‌گذاری‌شده، هفت پیکربندی S0 تا S6، فازهای شروع، نیم‌رخ دهک‌ها. داده: `docs/data/invested-study.json` |

## سیگنال‌ها و رفتار بازار

| گزارش | چه می‌گوید |
| --- | --- |
| [turning-points-2026-11](turning-points-2026-11.md) * | حالت‌های کف و سقف روی ۲۴ سال داده |
| [stock-drivers-2026-11](stock-drivers-2026-11.md) * | چه چیزی سهم‌ها را تکان می‌دهد |
| [technical-signals-2026-11](technical-signals-2026-11.md) * | نشانه‌های تکنیکال رایج و XGBoost |
| [indicator-zoo-2026-11](indicator-zoo-2026-11.md) * | ۱۰۲ اندیکاتور TradingView |
| [entry-odds-2026-11](entry-odds-2026-11.md) * | شانس سبز بودن کندل‌های بعد از هر الگوی ورود |
| [glossary-signals-2026-11](glossary-signals-2026-11.md) * | همهٔ واژه‌های نموداری واژه‌نامه روی نمودار و در آزمون |
| [forecast-check-1405](forecast-check-1405.md) | آیا اندیکاتورها کندل‌های بعدی امسال را درست گفتند |
| [orderbook-queue](orderbook-queue.md) | عمق سفارش و صف: چیزی به امتیاز اضافه نکرد؛ برچسب صف |
| [weekly-outlook-2026-11](weekly-outlook-2026-11.md) | حالت بازار و چشم‌انداز هفته |
| [research-practices-and-anomalies](research-practices-and-anomalies.md) | روش‌های فعالان بازار و ناهنجاری‌های شناخته‌شده |
| [market-method-2026-11](market-method-2026-11.md) | آزمون شش ادعای یک آموزگار بازار روی داده خودمان: فقط بنیادی (رشد سود، حاشیه، P/E) در هر دو نیمه همسو بود |
| [fundamental-model-2026-11](fundamental-model-2026-11.md) | صورت‌های مالی کنار سیگنال‌های v2، گام‌به‌گام: ترکیب ساده کمی بهتر، یادگیری ماشین بی‌فایده، t زیر ۲ |
| [small-target-2026-11](small-target-2026-11.md) | خرید در کف و فروش با +۳٪: برنده‌ها زیادند ولی انتظار ناخالص حدود صفر تا +۰٫۶٪ است و هزینهٔ ۱٫۷۵٪ آن را می‌خورد |

## داده

| گزارش | چه می‌گوید |
| --- | --- |
| [adjustment-check](adjustment-check.md) * | تعدیل قیمت در برابر سری TSETMC: بیشینهٔ خطا ۰٫۳۳٪ |
| [data-completeness](data-completeness.md) * | فهرست کامل نمادها و تاریخچهٔ ۱۳۸۰ به بعد |
| [data-quality](data-quality.md) | تطبیق با منبع دوم |
| [instrument-classification-audit](instrument-classification-audit.md) * | طبقه‌بندی نوع نماد |
| [risk-free-check](risk-free-check.md) | نرخ بدون ریسک از اخزا |
| [data-and-methods-research](data-and-methods-research.md) | منابع و روش‌های موجود و آنچه برمی‌داریم |
| [site-inspiration-gap-analysis](site-inspiration-gap-analysis.md) | مقایسه با سایت‌های مرجع |
| [self-critique-2026-11-16](self-critique-2026-11-16.md) | نقاط کور و تضادهای سایت (۲۵ آبان) |

دادهٔ خام مطالعه‌ها در [`docs/data/`](../data/) است.
