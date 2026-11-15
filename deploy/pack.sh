#!/usr/bin/env bash
# Run on the Windows machine (Git Bash) from the repo root: makes ONE small
# tarball (code only, no data, no secrets). Output: deploy/tmon-app.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf deploy/stage && mkdir -p deploy/stage/frontend deploy/stage/backend
# web source only: it is built on the server (pnpm links do not survive a Windows copy)
tar -C frontend --exclude=node_modules --exclude=.next --exclude=.next-e2e --exclude=test-results --exclude=playwright-report --exclude='*.tsbuildinfo' -cf - . | tar -C deploy/stage/frontend -xf -
cp -r backend/src backend/config backend/migrations backend/alembic.ini backend/pyproject.toml backend/uv.lock deploy/stage/backend/
tar -C deploy/stage -czf deploy/tmon-app.tar.gz .
rm -rf deploy/stage
ls -lh deploy/tmon-app.tar.gz
