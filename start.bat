@echo off
REM KSP Crime Intelligence — Start Script (Windows)
REM Runs tests, starts backend, then starts frontend.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ═══════════════════════════════════════════════════
echo   KSP Crime Intelligence — Startup
echo ═══════════════════════════════════════════════════

REM Check .env exists
if not exist .env (
    echo ERROR: .env file not found. Copy .env.example to .env and fill in values.
    exit /b 1
)

REM Activate venv
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo ERROR: No virtual environment found. Run: python -m venv .venv
    exit /b 1
)

REM 1. Run tests
echo.
echo [1/4] Running backend tests...
python -m pytest backend\tests\test_unit.py backend\tests\test_pipeline_and_sessions.py -q --tb=short
if errorlevel 1 (
    echo Tests failed. Fix errors before starting.
    exit /b 1
)
echo √ All tests passed

REM 2. DB ping
echo.
echo [2/4] Checking database connectivity...
python backend\debug_tools.py db
if errorlevel 1 (
    echo Database check failed. Verify .env credentials.
    exit /b 1
)

REM 3. Start backend in a new window
echo.
echo [3/4] Starting backend (port 8000)...
start "KSP Backend" cmd /k "cd /d %~dp0 && .venv\Scripts\activate.bat && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

REM Wait for backend to start
timeout /t 5 /nobreak >nul

REM Verify health
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo Backend failed to start. Check the backend window for errors.
    exit /b 1
)
echo √ Backend running

REM 4. Start frontend in a new window
echo.
echo [4/4] Starting frontend (port 5173)...
start "KSP Frontend" cmd /k "cd /d %~dp0\frontend && npm install --silent 2>nul && npm run dev"

timeout /t 3 /nobreak >nul

echo.
echo ═══════════════════════════════════════════════════
echo   Ready!
echo   Backend:  http://localhost:8000/docs
echo   Frontend: http://localhost:5173
echo   Health:   http://localhost:8000/health
echo ═══════════════════════════════════════════════════
echo.
echo Close the Backend and Frontend windows to stop the servers.
pause
