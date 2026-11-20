#!/usr/bin/env bash
# Runs ON THE SERVER (release.sh and rollback.sh pipe it in): installs one code tarball, restarts
# the services and waits until the API is ready. Usage: remote-install.sh <tarball> <commit>
set -euo pipefail
TARBALL=$1
COMMIT=$2
# code: replace the sources, keep the Python venv, the web node_modules and the data
rm -rf /opt/tmon/backend/src /opt/tmon/backend/config /opt/tmon/backend/migrations /opt/tmon/frontend
tar -C /opt/tmon -xzf "$TARBALL"
# web sources: drop what the new tree no longer has (stale files break the type check)
for d in app components lib public tests e2e; do rm -rf "/opt/tmon/web/$d"; done
cp -r /opt/tmon/frontend/. /opt/tmon/web/
chown -R tmon:tmon /opt/tmon /var/lib/tmon
cd /opt/tmon/backend
sudo -u tmon -H env UV_CACHE_DIR=/var/lib/tmon/uv /usr/local/bin/uv sync --frozen --no-dev --python 3.13 -q
sudo -u tmon -H bash -c 'cd /opt/tmon/web && pnpm install --frozen-lockfile --silent && API_URL=http://127.0.0.1:8000 pnpm exec next build >/tmp/tmon-build.log 2>&1 || { tail -30 /tmp/tmon-build.log; exit 1; } && cp -r .next/static .next/standalone/.next/static && { [ ! -d public ] || cp -r public .next/standalone/public; }'
systemctl restart tmon-api tmon-web
bash /root/install-monitor.sh
# /health: the process answers. /ready: the start-up build of the derived columns is done (a
# minute or two), so the first visitor does not wait for it.
for i in $(seq 60); do curl -sf -o /dev/null 127.0.0.1:8000/health && break; sleep 1; done
for i in $(seq 30); do curl -sf -o /dev/null 127.0.0.1:3000/ && break; sleep 1; done
READY=no
for i in $(seq 60); do curl -sf -o /dev/null 127.0.0.1:8000/ready && READY=yes && break; sleep 5; done
echo "ready: $READY"
systemctl is-active tmon-api tmon-web tmon-monitor
curl -sf 127.0.0.1:8000/data-health | head -c 200; echo
echo "$COMMIT $(date -u +%FT%TZ)" > /opt/tmon/RELEASE
# keep the last three code tarballs so that rollback.sh can put one back without a build on the PC
mkdir -p /opt/tmon/releases
case "$TARBALL" in /opt/tmon/releases/*) ;; *) cp "$TARBALL" "/opt/tmon/releases/$COMMIT.tar.gz" ;; esac
ls -1t /opt/tmon/releases/*.tar.gz | tail -n +4 | xargs -r rm -f
[ "$READY" = yes ] || { echo "WARNING: the API did not become ready within 5 minutes" >&2; exit 1; }
