# مستندات Tmon

به‌روز: ۲۶ آبان ۱۴۰۵. برای کار روی کد اول [AGENTS.md](../AGENTS.md) را بخوان. اگر سندی با کد نخواند، کد درست است و سند باید اصلاح شود. `backend/tests/test_docs_links.py` پیوندهای این پوشه و مسیرهای `docs/...` در کد را بررسی می‌کند.

## محصول و سامانه

| سند | موضوع |
| --- | --- |
| [00-overview](00-overview.md) | هدف، وضعیت امروز، اصل «ممتنع بودن»، محدوده، ریسک‌ها و محدودیت‌ها |
| [10-recommendation-engine](10-recommendation-engine.md) | آنچه سایت نشان می‌دهد (رتبه‌بندی v2، حکم هر نماد، چرخهٔ روزانه) و مسیر v1 |
| [11-architecture-and-data-model](11-architecture-and-data-model.md) | اجزا، بسته‌ها، جهت وابستگی، جریان داده، جدول‌ها |
| [12-roadmap](12-roadmap.md) | چه انجام شده و چه مانده، با شواهد |
| [14-local-run](14-local-run.md) | اجرا روی PC: چرخهٔ روزانه، فرمان‌ها، تست |
| [15-deploy](15-deploy.md) | سرور، انتشار کد، همگام‌سازی داده، امنیت |
| [16-data-completeness](16-data-completeness.md) | تشخیص روز ناقص و دکمهٔ تکمیل |
| [17-portfolios-and-alerts](17-portfolios-and-alerts.md) | پرتفوی، مفید، هشدار، پیش‌بینی بازه، دیدبان سرور |
| [OPEN_QUESTIONS](OPEN_QUESTIONS.md) | پرسش‌های باز و تصمیم‌های مالک (شماره‌ها در کد ارجاع دارند) |
| [glossary](glossary.md) | واژه‌نامه؛ `frontend/tests/glossary.test.ts` آن را با سایت تطبیق می‌دهد |

## دانش دامنه

هر کدام در بالا یادداشت «وضعیت در کد» دارد.

| سند | موضوع |
| --- | --- |
| [01](01-market-structure-and-rules.md) | ساختار بازار و قواعد |
| [02](02-data-sources.md) | منابع داده |
| [03](03-fundamental-analysis.md) | تحلیل بنیادی |
| [04](04-technical-and-orderbook.md) | تکنیکال و تابلوخوانی |
| [05](05-corporate-events.md) | مجمع، سود نقدی، افزایش سرمایه |
| [06](06-funds.md) | صندوق‌ها |
| [07](07-commodity-and-futures.md) | بورس کالا و آتی |
| [08](08-news-and-macro.md) | خبر و کلان |
| [09](09-sectors-and-allocation.md) | صنایع و تخصیص |

## تصمیم‌ها و شواهد

| سند | موضوع |
| --- | --- |
| [ADR 0001](adr/0001-tech-stack.md) | زبان‌ها و ابزارها (بخش اجرا اصلاح شده) |
| [ADR 0002](adr/0002-engine-and-data-decisions.md) | هزینه، آستانه‌ها و تعریف پایان در v1 |
| [ADR 0003](adr/0003-engine-v2-relative-rank-and-exposure.md) | موتور v2 و دروازه‌های G1 تا G6 |
| [ADR 0004](adr/0004-two-level-verdict-and-invested-book.md) | حکم دوسطحی، سبد همیشه سرمایه‌گذاری‌شده و معیار «بخر و نگه‌دار» (تصمیم؛ هر چهار گام در کد) |
| [reports/](reports/README.md) | همهٔ گزارش‌ها با یک خط نتیجه |

تاریخچهٔ تغییرات در `git log` است.

> این مستندات تحلیل فنی و آموزشی است، نه توصیهٔ سرمایه‌گذاری.
