# تغییرات

## M0 — اسکلت (۲۰ آبان ۱۴۰۵)

- ساختار ریپو طبق [11](11-architecture-and-data-model.md): `backend/` (uv، Python 3.12)، `frontend/` (Next.js 16، TypeScript، Tailwind 4، RTL و وزیرمتن)، `infra/docker-compose.yml`، `.github/workflows/ci.yml`.
- هسته: تنظیمات از محیط، بارگذاری تایپ‌شده `config/engine.yaml`، زمان UTC با نمایش تهران و شمسی.
- اسکیمای اصلی و مهاجرت Alembic با hypertable در TimescaleDB.
- CI: ruff، mypy، pytest، eslint، tsc، vitest، build.
- **انحراف:** `docker compose up` اجرا نشد (دیمن Docker خاموش)؛ فقط اعتبار فایل بررسی شد. ← [OPEN_QUESTIONS](OPEN_QUESTIONS.md)
- **انحراف:** جدول `price_adjustments` و `raw_payloads` و `signal_runs` به اسکیما افزوده شد (تعدیل مشتق‌شده، فهرست پاسخ‌های خام، روزهای «پیشنهادی نیست»).
