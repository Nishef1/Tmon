# استقرار روی سرور (VPS ایران)

معماری: فقط پورت‌های ۲۲، ۸۰ و ۴۴۳ باز است. nginx با HTTPS و ورود (نام کاربری و رمز) جلوی سایت است؛ API (پورت ۸۰۰۰) و وب (۳۰۰۰) فقط روی `127.0.0.1` گوش می‌دهند. اجرا با systemd، با کاربر بی‌دسترسی `tmon`. چرخهٔ روزانه با تایمر systemd (شنبه تا چهارشنبه ۱۹:۳۰) اجرا می‌شود. Docker و Celery نیستند.

## مراحل
1. روی ویندوز (Git Bash، ریشهٔ ریپو): `bash deploy/pack.sh` ← `deploy/tmon-app.tar.gz` (فقط کد).
2. فایل‌ها را بفرست (از ترمینال خودت): `scp deploy/tmon-app.tar.gz deploy/server-setup.sh root@IP:/root/`
3. روی سرور: `bash /root/server-setup.sh` — در پایان آدرس و نام کاربری و رمز ورود سایت چاپ می‌شود.
4. داده: `data/tmon-live.sqlite3` (۱۵ گیگ) و `data/objects` (۸٫۴ گیگ) را به `/var/lib/tmon/` ببر (`rsync -avP`) و `chown -R tmon:tmon /var/lib/tmon`. ظرفیت دیسک را قبلش با `df -h` ببین. اگر کم است، دادهٔ تاریخی را کوچک کن یا سرور را بزرگ‌تر بگیر.

## امنیت
- رمز root در چت فرستاده شد: **همین حالا عوضش کن** (`passwd`) و بعد با کلید SSH وارد شو و ورود با رمز را ببند (`PasswordAuthentication no` در `/etc/ssh/sshd_config`، سپس `systemctl restart ssh`) — اول مطمئن شو ورود با کلید کار می‌کند.
- گواهی خودامضاست (بدون دامنه). با داشتن دامنه، certbot گواهی معتبر می‌دهد.
- تغییر رمز سایت: `htpasswd -B /etc/nginx/tmon/htpasswd tmon && systemctl reload nginx`.
- لاگ‌ها: `journalctl -u tmon-api -u tmon-web -u tmon-cycle`.

## یادداشت‌های نصب واقعی (Ubuntu 24.04)
- Node از nodesource (۲۶ یا ۲۴)، pnpm با npm؛ `corepack` در Node جدید نیست. وب روی سرور بیلد می‌شود.
- `libgomp1` برای lightgbm لازم است.
- ورود SSH با رمز بسته و فقط کلید مجاز است (`/etc/ssh/sshd_config.d/00-tmon.conf`).
- پورت SSH روی **1415** است (۲۲ بسته). اتصال: `ssh -p 1415 -i ~/.ssh/tmon_vps root@185.7.172.67`. در Ubuntu 24.04 باید `ssh.socket` خاموش باشد تا پورت sshd_config اعمال شود.
