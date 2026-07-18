#!/usr/bin/env bash
# CI backend deploy helper — non-interactive Catalyst AppSail deploy.
#
# The FRONTEND is deployed automatically by Catalyst Slate (Auto Deploy is ON
# for the main branch). This script handles the backend (AppSail) only.
#
# Expects:
#   CATALYST_TOKEN  in environment
#   .env            at repo root (restored from the ENV_FILE secret)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

BACKEND_URL="${BACKEND_URL:-https://crime-intel-backend-50043099694.development.catalystappsail.in}"
TOKEN_ARG=(--token "${CATALYST_TOKEN:?CATALYST_TOKEN not set}")

echo "▶ Generating backend/app-config.json from .env"
python3 scripts/gen_app_config.py

echo "▶ Bundling backend Python dependencies"
python3 -m pip install -r backend/requirements.txt -t backend/ --upgrade --quiet

echo "▶ Deploying backend (AppSail)"
catalyst deploy --only appsail --ignore-scripts "${TOKEN_ARG[@]}"

echo "✓ Backend deploy complete (frontend auto-deploys via Catalyst Slate)"
