#!/bin/bash
# KSP Crime Intelligence — Start Script (Linux/macOS)
# Runs tests, starts backend, then starts frontend.

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  KSP Crime Intelligence — Startup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"

# Check .env exists
if [ ! -f .env ]; then
    echo -e "${RED}ERROR: .env file not found. Copy .env.example to .env and fill in values.${NC}"
    exit 1
fi

# Activate venv
if [ -d .venv ]; then
    source .venv/bin/activate
elif [ -d venv ]; then
    source venv/bin/activate
else
    echo -e "${RED}ERROR: No virtual environment found. Run: python3 -m venv .venv${NC}"
    exit 1
fi

# 1. Run tests
echo ""
echo -e "${CYAN}[1/4] Running backend tests...${NC}"
python -m pytest backend/tests/test_unit.py backend/tests/test_pipeline_and_sessions.py -q --tb=short
if [ $? -ne 0 ]; then
    echo -e "${RED}Tests failed. Fix errors before starting.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ All tests passed${NC}"

# 2. DB ping
echo ""
echo -e "${CYAN}[2/4] Checking database connectivity...${NC}"
python backend/debug_tools.py db
if [ $? -ne 0 ]; then
    echo -e "${RED}Database check failed. Verify .env credentials.${NC}"
    exit 1
fi

# 3. Start backend
echo ""
echo -e "${CYAN}[3/4] Starting backend (port 8000)...${NC}"
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
sleep 3

# Verify health
HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null)
if echo "$HEALTH" | grep -q '"db":"connected"'; then
    echo -e "${GREEN}✓ Backend running — $(echo $HEALTH)${NC}"
else
    echo -e "${RED}Backend health check failed. Check logs above.${NC}"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

# 4. Start frontend
echo ""
echo -e "${CYAN}[4/4] Starting frontend (port 5173)...${NC}"
cd frontend
npm install --silent 2>/dev/null
npm run dev &
FRONTEND_PID=$!
cd "$ROOT"

sleep 2
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Ready!${NC}"
echo -e "${GREEN}  Backend:  http://localhost:8000/docs${NC}"
echo -e "${GREEN}  Frontend: http://localhost:5173${NC}"
echo -e "${GREEN}  Health:   http://localhost:8000/health${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "Press Ctrl+C to stop both servers."

# Wait for Ctrl+C, then cleanup
trap "echo ''; echo 'Shutting down...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM
wait
