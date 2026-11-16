#!/usr/bin/env bash
# Run on the Windows machine (Git Bash) from the repo root after EVERY commit+push: ships the
# CODE (not the data; data goes with sync-data.sh) to the server, rebuilds the web there,
# restarts both services and checks that they answer.
#   bash deploy/release.sh            # needs ~/.ssh/tmon_vps
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@185.7.172.67
SSH=(ssh -p 1415 -i ~/.ssh/tmon_vps -o BatchMode=yes "$HOST")
SCP=(scp -q -P 1415 -i ~/.ssh/tmon_vps)

COMMIT=$(git rev-parse --short HEAD)
# ship exactly the committed tree: another session's unfinished edits must not reach the server
git status --porcelain -- backend/src frontend | grep -v '^??' | sed 's/^/not shipped (uncommitted): /' || true
rm -rf deploy/stage && mkdir -p deploy/stage
git archive HEAD frontend backend/src backend/config backend/migrations backend/alembic.ini   backend/pyproject.toml backend/uv.lock | tar -x -C deploy/stage
tar -C deploy/stage -czf deploy/tmon-app.tar.gz . && rm -rf deploy/stage
ls -lh deploy/tmon-app.tar.gz
"${SCP[@]}" deploy/tmon-app.tar.gz deploy/install-monitor.sh "$HOST:/root/"
"${SSH[@]}" "COMMIT=$COMMIT bash -s" <<'REMOTE'
set -euo pipefail
# code: replace the sources, keep the Python venv, the web node_modules and the data
rm -rf /opt/tmon/backend/src /opt/tmon/backend/config /opt/tmon/backend/migrations /opt/tmon/frontend
tar -C /opt/tmon -xzf /root/tmon-app.tar.gz
# web sources: drop what the new tree no longer has (stale files break the type check)
for d in app components lib public tests e2e; do rm -rf "/opt/tmon/web/$d"; done
cp -r /opt/tmon/frontend/. /opt/tmon/web/
chown -R tmon:tmon /opt/tmon /var/lib/tmon
cd /opt/tmon/backend
sudo -u tmon -H env UV_CACHE_DIR=/var/lib/tmon/uv /usr/local/bin/uv sync --frozen --no-dev --python 3.13 -q
sudo -u tmon -H bash -c 'cd /opt/tmon/web && pnpm install --frozen-lockfile --silent && API_URL=http://127.0.0.1:8000 pnpm exec next build >/tmp/tmon-build.log 2>&1 || { tail -30 /tmp/tmon-build.log; exit 1; } && cp -r .next/static .next/standalone/.next/static && { [ ! -d public ] || cp -r public .next/standalone/public; }'
systemctl restart tmon-api tmon-web
bash /root/install-monitor.sh
for i in $(seq 60); do curl -sf -o /dev/null 127.0.0.1:8000/health && break; sleep 1; done
for i in $(seq 30); do curl -sf -o /dev/null 127.0.0.1:3000/ && break; sleep 1; done
systemctl is-active tmon-api tmon-web tmon-monitor
curl -sf 127.0.0.1:8000/data-health | head -c 200; echo
echo "$COMMIT $(date -u +%FT%TZ)" > /opt/tmon/RELEASE
rm -f /root/tmon-app.tar.gz /root/install-monitor.sh
REMOTE
echo "released $COMMIT"
