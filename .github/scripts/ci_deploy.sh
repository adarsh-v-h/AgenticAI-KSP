#!/usr/bin/env bash
# CI deploy helper — non-interactive Catalyst deploy of backend + frontend.
#
# Deploys the backend (AppSail) and the frontend (Web Client Hosting) together.
#
# Expects:
#   CATALYST_CLI_TOKEN  in environment (CLI deploy token from `catalyst token:generate`)
#   .env                at repo root (restored from the ENV_FILE secret)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

BACKEND_URL="${BACKEND_URL:-https://crime-intel-backend-50043099694.development.catalystappsail.in}"
TOKEN_ARG=(--token "${CATALYST_CLI_TOKEN:?CATALYST_CLI_TOKEN not set}")

echo "▶ Building frontend into client-package/"
( cd frontend && npm ci && VITE_API_BASE_URL="$BACKEND_URL" npm run build )
find client-package -mindepth 1 ! -name 'client-package.json' -delete
cp -r frontend/dist/. client-package/

echo "▶ Generating backend/app-config.json from .env"
python3 scripts/gen_app_config.py

echo "▶ Bundling backend Python dependencies"
python3 -m pip install -r backend/requirements.txt -t backend/ --upgrade --quiet

echo "▶ Deploying backend (AppSail) + frontend (Web Client)"
catalyst deploy --only appsail,client --ignore-scripts "${TOKEN_ARG[@]}"

echo "✓ Deploy complete (backend + frontend)"
