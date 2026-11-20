#!/usr/bin/env bash
# Run on the Windows machine (Git Bash) from the repo root after EVERY commit+push: ships the
# CODE (not the data; data goes with sync-data.sh) to the server, rebuilds the web there,
# restarts both services and waits until the API is ready. A failed release can be undone with
# deploy/rollback.sh.
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
"${SCP[@]}" deploy/tmon-app.tar.gz deploy/install-monitor.sh deploy/remote-install.sh "$HOST:/root/"
"${SSH[@]}" "bash /root/remote-install.sh /root/tmon-app.tar.gz $COMMIT; rc=\$?; rm -f /root/tmon-app.tar.gz /root/install-monitor.sh /root/remote-install.sh; exit \$rc"
echo "released $COMMIT"
