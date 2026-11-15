#!/usr/bin/env bash
# Run ONCE on the server as root, after copying tmon-app.tar.gz to /root/. Idempotent.
#   SITE_USER=tmon SITE_PASS='...' bash server-setup.sh     (pass optional: random one is made)
# What it does: unprivileged user, app in /opt/tmon, API+web bound to 127.0.0.1 only, nginx in front
# with HTTPS (self-signed, IP only) and a login (HTTP basic auth), firewall (22/80/443), fail2ban.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
SITE_USER="${SITE_USER:-tmon}"
SITE_PASS="${SITE_PASS:-$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)}"
IP="$(curl -4fs https://ifconfig.me || hostname -I | awk '{print $1}')"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y nginx apache2-utils openssl ufw fail2ban curl ca-certificates tar unattended-upgrades nodejs
node -v | grep -qE '^v(2[2-9]|[3-9][0-9])' || echo "WARNING: node is old ($(node -v)); Next 16 needs >= 20.9. Install a newer Node."

id tmon >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin tmon
mkdir -p /opt/tmon /var/lib/tmon/objects
tar -C /opt/tmon -xzf /root/tmon-app.tar.gz
chown -R tmon:tmon /opt/tmon /var/lib/tmon

# Python 3.13 + dependencies via uv (needs PyPI; if blocked, set UV_INDEX_URL to a reachable mirror)
if ! command -v uv >/dev/null; then curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh; fi
( cd /opt/tmon/backend && sudo -u tmon -H env UV_CACHE_DIR=/var/lib/tmon/uv /usr/local/bin/uv sync --frozen --no-dev --python 3.13 )

cat > /etc/tmon.env <<ENV
TMON_DATABASE_URL=sqlite:////var/lib/tmon/tmon-live.sqlite3
TMON_OBJECT_STORE=file
TMON_OBJECT_STORE_DIR=/var/lib/tmon/objects
TMON_CORS_ORIGINS=["https://$IP"]
API_URL=http://127.0.0.1:8000
HOSTNAME=127.0.0.1
PORT=3000
ENV
chmod 600 /etc/tmon.env

cat > /etc/systemd/system/tmon-api.service <<'UNIT'
[Unit]
Description=Tmon API
After=network.target
[Service]
User=tmon
WorkingDirectory=/opt/tmon/backend
EnvironmentFile=/etc/tmon.env
ExecStart=/opt/tmon/backend/.venv/bin/uvicorn tmon.api.main:app --host 127.0.0.1 --port 8000
Restart=always
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/tmon
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/tmon-web.service <<'UNIT'
[Unit]
Description=Tmon web
After=network.target tmon-api.service
[Service]
User=tmon
WorkingDirectory=/opt/tmon/web
EnvironmentFile=/etc/tmon.env
ExecStart=/usr/bin/node /opt/tmon/web/server.js
Restart=always
NoNewPrivileges=true
ProtectSystem=strict
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
# the daily cycle (ingest, adapt, publish): once on weekdays, 19:30 server time
cat > /etc/systemd/system/tmon-cycle.service <<'UNIT'
[Unit]
Description=Tmon daily cycle
[Service]
Type=oneshot
User=tmon
WorkingDirectory=/opt/tmon/backend
EnvironmentFile=/etc/tmon.env
ExecStart=/opt/tmon/backend/.venv/bin/python -m tmon.tasks.cycle
ProtectSystem=strict
ReadWritePaths=/var/lib/tmon
UNIT
cat > /etc/systemd/system/tmon-cycle.timer <<'UNIT'
[Timer]
OnCalendar=Sat..Wed *-*-* 19:30:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT

# HTTPS (self-signed for the IP) + login
mkdir -p /etc/nginx/tmon
[ -f /etc/nginx/tmon/cert.pem ] || openssl req -x509 -nodes -newkey rsa:3072 -days 825 \
  -keyout /etc/nginx/tmon/key.pem -out /etc/nginx/tmon/cert.pem -subj "/CN=$IP" -addext "subjectAltName=IP:$IP"
htpasswd -bcB /etc/nginx/tmon/htpasswd "$SITE_USER" "$SITE_PASS"
chmod 640 /etc/nginx/tmon/htpasswd /etc/nginx/tmon/key.pem; chgrp www-data /etc/nginx/tmon/htpasswd /etc/nginx/tmon/key.pem
cat > /etc/nginx/sites-available/tmon <<'NGX'
limit_req_zone $binary_remote_addr zone=tmon:10m rate=20r/s;
server { listen 80 default_server; return 301 https://$host$request_uri; }
server {
  listen 443 ssl default_server;
  ssl_certificate /etc/nginx/tmon/cert.pem;
  ssl_certificate_key /etc/nginx/tmon/key.pem;
  ssl_protocols TLSv1.2 TLSv1.3;
  server_tokens off;
  add_header Strict-Transport-Security "max-age=31536000" always;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy no-referrer always;
  auth_basic "Tmon";
  auth_basic_user_file /etc/nginx/tmon/htpasswd;
  limit_req zone=tmon burst=60 nodelay;
  location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
  }
}
NGX
ln -sf /etc/nginx/sites-available/tmon /etc/nginx/sites-enabled/tmon; rm -f /etc/nginx/sites-enabled/default
nginx -t

# firewall + brute-force protection (SSH port left open; see SECURITY NOTES in docs/15-deploy.md)
ufw default deny incoming; ufw default allow outgoing
ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp
ufw --force enable
cat > /etc/fail2ban/jail.d/tmon.local <<'F2B'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
[nginx-http-auth]
enabled = true
F2B

systemctl daemon-reload
systemctl enable --now tmon-api tmon-web tmon-cycle.timer fail2ban
systemctl restart nginx
echo "=============================================="
echo "Site:  https://$IP   (browser warns once: self-signed certificate; accept it)"
echo "Login: $SITE_USER / $SITE_PASS   <- save it now, it is not stored in clear text"
echo "Data:  copy tmon-live.sqlite3 to /var/lib/tmon/ and objects/ to /var/lib/tmon/objects (see docs/15-deploy.md)"
