#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Full Catalyst deployment script
#
# Usage:
#   ./deploy.sh                  # Deploy both backend + frontend
#   ./deploy.sh backend          # Deploy backend (AppSail) only
#   ./deploy.sh frontend         # Deploy frontend (Web Client) only
#
# Prerequisites:
#   - catalyst CLI installed and logged in (catalyst login)
#   - Node.js / npm available
#   - .catalystrc present (project linked)
#
# The script will:
#   1. Build the frontend with VITE_API_BASE_URL baked in
#   2. Copy build output into client-package/
#   3. Run catalyst deploy for the requested component(s)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Backend AppSail URL — the live deployed backend. Override by exporting
# VITE_API_BASE_URL before running this script if the URL changes.
DEFAULT_BACKEND_URL="https://crime-intel-backend-50043099694.development.catalystappsail.in"
BACKEND_URL="${VITE_API_BASE_URL:-$DEFAULT_BACKEND_URL}"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

log() { echo "▶ $*"; }
ok()  { echo "✓ $*"; }
err() { echo "✗ $*" >&2; }

check_catalyst() {
    if ! command -v catalyst &>/dev/null; then
        err "catalyst CLI not found. Install it: npm install -g zcatalyst-cli"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Build frontend
# ---------------------------------------------------------------------------

build_frontend() {
    log "Building frontend with VITE_API_BASE_URL=$BACKEND_URL"
    
    cd "$SCRIPT_DIR/frontend"
    
    # Install deps if node_modules is missing
    if [ ! -d "node_modules" ]; then
        log "Installing frontend dependencies..."
        npm ci
    fi
    
    # Build with the backend URL baked in
    VITE_API_BASE_URL="$BACKEND_URL" npm run build
    
    ok "Frontend built successfully"
    
    # Copy build output to client-package, preserving client-package.json.
    cd "$SCRIPT_DIR"
    find client-package -mindepth 1 ! -name 'client-package.json' -delete
    cp -r frontend/dist/. client-package/
    
    ok "Build output copied to client-package/"
}

# ---------------------------------------------------------------------------
# Deploy backend
# ---------------------------------------------------------------------------

deploy_backend() {
    check_catalyst
    log "Deploying backend (AppSail)..."
    
    cd "$SCRIPT_DIR"
    catalyst deploy --only appsail
    
    ok "Backend deployed"
    echo ""
    echo "NOTE: Copy the backend URL printed above and set VITE_API_BASE_URL"
    echo "      before deploying the frontend."
}

# ---------------------------------------------------------------------------
# Deploy frontend
# ---------------------------------------------------------------------------

deploy_frontend() {
    check_catalyst
    
    # Ensure client-package has a real build (index.html referencing assets).
    if [ ! -f "client-package/index.html" ] || [ ! -d "client-package/assets" ]; then
        log "client-package/ has no build output — building frontend first..."
        build_frontend
    fi
    
    log "Deploying frontend (Web Client Hosting)..."
    
    cd "$SCRIPT_DIR"
    catalyst deploy --only client
    
    ok "Frontend deployed"
    echo ""
    echo "NOTE: Make sure ALLOWED_ORIGINS in Catalyst console env vars"
    echo "      matches the frontend URL printed above (see Part 4 of walkthrough)."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-all}" in
    backend)
        deploy_backend
        ;;
    frontend)
        build_frontend
        deploy_frontend
        ;;
    all)
        deploy_backend
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo ""
        build_frontend
        deploy_frontend
        ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

echo ""
ok "Deployment complete!"
