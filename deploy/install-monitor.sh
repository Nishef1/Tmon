#!/usr/bin/env bash
# Runs ON THE SERVER (release.sh pipes it in; idempotent): installs the 24/7 watcher that raises
# the urgent alerts and records the intraday tape. It idles outside the trading hours, so it stays
# enabled all the time; docs/17-advisor-spec.md item 1.
set -euo pipefail
grep -q '^TMON_PUBLIC_WEB_URL=' /etc/tmon.env || echo 'TMON_PUBLIC_WEB_URL=https://185.7.172.67' >> /etc/tmon.env
# the raw 4 MB market-watch payload every few polls would add ~250 MB a day here; the typed
# snapshot tables carry everything the site reads
grep -q '^TMON_MONITOR_RAW_EVERY=' /etc/tmon.env || echo 'TMON_MONITOR_RAW_EVERY=0' >> /etc/tmon.env
cat > /etc/systemd/system/tmon-monitor.service <<'UNIT'
[Unit]
Description=Tmon monitor (urgent alerts, intraday tape)
After=network-online.target tmon-api.service
Wants=network-online.target
[Service]
User=tmon
WorkingDirectory=/opt/tmon/backend
EnvironmentFile=/etc/tmon.env
ExecStart=/opt/tmon/backend/.venv/bin/python -m tmon.portfolio.monitor
Restart=always
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/tmon
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p /etc/systemd/system/tmon-monitor.service.d
cat > /etc/systemd/system/tmon-monitor.service.d/limits.conf <<'UNIT'
[Service]
MemoryHigh=700M
MemoryMax=1000M
Nice=5
UNIT
systemctl daemon-reload
systemctl enable tmon-monitor >/dev/null 2>&1
systemctl restart tmon-monitor
