#!/usr/bin/env bash
# CI deploy helper — non-interactive Catalyst deploy of backend + frontend.
#
# Used by .github/workflows/deploy.yml for both the initial deploy and the
# auto-revert redeploy. Expects:
#   - CATALYST_TOKEN  in the environment (from `catalyst token:generate`)
#   - .env            present at repo root (restored from the ENV_FILE secret)
#   - catalyst CLI, python3, and node installed
#
# Mirrors ./deploy.sh but non-interactive and token-authenticated.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

BACKEND_URL="${BACKEND_URL:-https://crime-intel-backend-50043099694.development.catalystappsail.in}"
TOKEN_ARG=(--token "${CATALYST_TOKEN:?CATALYST_TOKEN not set}")

echo "▶ Generating backend/app-config.json from .env"
python3 scripts/gen_app_config.py

echo "▶ Bundling backend Python dependencies (cp310, matches python_3_10 stack)"
python3 -m pip install -r backend/requirements.txt -t backend/ --upgrade --quiet

echo "▶ Building frontend (VITE_API_BASE_URL=$BACKEND_URL)"
pushd frontend >/dev/null
npm ci
VITE_API_BASE_URL="$BACKEND_URL" npm run build
popd >/dev/null

echo "▶ Copying frontend build into client-package/ (preserving client-package.json)"
find client-package -mindepth 1 ! -name 'client-package.json' -delete
cp -r frontend/dist/. client-package/

echo "▶ Deploying backend (AppSail)"
catalyst deploy --only appsail --ignore-scripts "${TOKEN_ARG[@]}"

echo "▶ Deploying frontend (Web Client)"
catalyst deploy --only client "${TOKEN_ARG[@]}"

echo "✓ CI deploy complete"
