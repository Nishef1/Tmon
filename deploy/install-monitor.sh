#!/usr/bin/env bash
# Runs ON THE SERVER (release.sh pipes it in; idempotent): installs the 24/7 watcher that raises
# the urgent alerts and records the intraday tape. It idles outside the trading hours, so it stays
# enabled all the time; docs/17-portfolios-and-alerts.md («اجرا روی سرور»).
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

# watchdog: every minute checks that the API and the web answer, and restarts the one that has
# not answered three times in a row (a stuck process is the usual cause of a 504). It leaves a
# service alone for 5 minutes after it started, so a slow start is not mistaken for a hang.
# TMON_WATCH_NOTIFY_URL in /etc/tmon.env (an ntfy topic URL, optional) gets a one-line message.
cat > /usr/local/bin/tmon-watchdog <<'SCRIPT'
#!/usr/bin/env bash
set -u
TMON_WATCH_NOTIFY_URL=$(grep -s "^TMON_WATCH_NOTIFY_URL=" /etc/tmon.env | cut -d= -f2-)
STATE=/run/tmon-watchdog
mkdir -p "$STATE"
check() { # service url
  local svc=$1 url=$2 f="$STATE/$1.fails"
  if curl -sf -o /dev/null -m 15 "$url"; then rm -f "$f"; return; fi
  local started now
  started=$(date -d "$(systemctl show "$svc" -p ActiveEnterTimestamp --value)" +%s 2>/dev/null || echo 0)
  now=$(date +%s)
  [ $((now - started)) -lt 300 ] && return
  local n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$f"
  if [ "$n" -ge 3 ]; then
    rm -f "$f"
    logger -t tmon-watchdog "$svc did not answer $url three times: restarting"
    systemctl restart "$svc"
    [ -n "${TMON_WATCH_NOTIFY_URL:-}" ] && curl -s -m 10 -d "tmon: $svc did not answer, restarted" "$TMON_WATCH_NOTIFY_URL" >/dev/null
  fi
}
check tmon-api http://127.0.0.1:8000/health
check tmon-web http://127.0.0.1:3000/
SCRIPT
chmod +x /usr/local/bin/tmon-watchdog
cat > /etc/systemd/system/tmon-watchdog.service <<'UNIT'
[Unit]
Description=Tmon watchdog (restarts a service that stopped answering)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/tmon-watchdog
UNIT
cat > /etc/systemd/system/tmon-watchdog.timer <<'UNIT'
[Unit]
Description=Run the Tmon watchdog every minute
[Timer]
OnBootSec=5min
OnUnitActiveSec=1min
AccuracySec=10s
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now tmon-watchdog.timer >/dev/null 2>&1
