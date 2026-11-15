#!/usr/bin/env bash
# Run on the Windows machine (Git Bash) from the repo root: builds the web app and makes ONE small
# tarball (code only, no data, no secrets). Output: deploy/tmon-app.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
( cd frontend && pnpm exec next build )
rm -rf deploy/stage && mkdir -p deploy/stage/web deploy/stage/backend
cp -r frontend/.next/standalone/. deploy/stage/web/
mkdir -p deploy/stage/web/.next && cp -r frontend/.next/static deploy/stage/web/.next/static
[ -d frontend/public ] && cp -r frontend/public deploy/stage/web/public || true
cp -r backend/src backend/config backend/migrations backend/alembic.ini backend/pyproject.toml backend/uv.lock deploy/stage/backend/
tar -C deploy/stage -czf deploy/tmon-app.tar.gz .
rm -rf deploy/stage
ls -lh deploy/tmon-app.tar.gz
