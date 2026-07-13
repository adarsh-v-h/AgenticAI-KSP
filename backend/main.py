import sys
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure the backend directory is in the import path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config.settings import validate_settings, get
from db.connection import create_pool, close_pool
from llm.client import ping_model
from routers.chat import router as chat_router
from routers.auth import router as auth_router
from routers.export import router as export_router
from routers.reports import router as reports_router
from routers.voice import router as voice_router
from routers.governance import router as governance_router
from routers.analytics import router as analytics_router
from routers.decision_support import router as decision_support_router
from routers.profiling import router as profiling_router
from conversation.history import init_nosql_table

# CONTRACT
# takes:  app (FastAPI) — the FastAPI application instance
# returns: nothing (async context manager yields after startup, runs shutdown after)
# raises:  nothing (DB/NoSQL failures are logged as warnings, never crash startup)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # â”€â”€ STARTUP â”€â”€
    # 1. Validate all env vars â€” crash loudly if anything missing
    validate_settings()

    # 2. Create DB connection pool
    await create_pool()

    # 3. Confirm DB is reachable (run a trivial query)
    # If this fails, print a warning but don't crash â€” DB might not be provisioned yet locally
    # (this lets you still start the server and see the health check)
    try:
        from db.connection import execute_query
        await execute_query("SELECT 1")
        app.state.db_ok = True
    except Exception as e:
        print(f"WARNING: DB connection check failed: {e}", file=sys.stderr)
        app.state.db_ok = False

    # 4. Probe Catalyst NoSQL so we surface auth/path issues at startup.
    # Failure is non-fatal â€” history.py falls back to in-memory storage.
    try:
        await init_nosql_table()
    except Exception as e:
        print(f"WARNING: NoSQL init failed (history will use in-memory store): {e}", file=sys.stderr)
    # This is the dividing line between startup and shutdown.
    # Everything before yield runs when the app starts.
    yield
    # Everything after yield runs when the app stops.

    # â”€â”€ SHUTDOWN â”€â”€
    await close_pool()


app = FastAPI(
    title="KSP Crime Intelligence API",
    version="0.4.0-step4",
    docs_url="/docs",       # keep Swagger available during dev
    redoc_url=None,
    lifespan=lifespan
)

# CORS â€” only allow origin from env, never wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get("ALLOWED_ORIGINS")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# Security response headers — defense-in-depth for clickjacking, MIME sniffing, referrer leaks
from starlette.middleware.base import BaseHTTPMiddleware


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        return response


app.add_middleware(_SecurityHeadersMiddleware)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(export_router)
app.include_router(reports_router)
app.include_router(voice_router)
app.include_router(governance_router)
app.include_router(analytics_router)
app.include_router(decision_support_router)
app.include_router(profiling_router)


@app.get("/health")
async def health_check():
    """
    Checks:
    1. DB connectivity (use app.state.db_ok set during startup)
    2. LLM MODEL_SQL reachable (ping_model)
    3. LLM MODEL_ANSWER reachable (ping_model)

    Returns:
    {
        "status": "ok" | "degraded",
        "db": "connected" | "error",
        "llm_coder": "ok" | "error",
        "llm_answer": "ok" | "error",
        "env": "development" | "production"
    }

    HTTP 200 always â€” even if degraded.
    Never return 500 from health check.
    Run LLM pings in parallel using asyncio.gather.
    """
    # 1. Check DB connectivity
    db_ok = getattr(app.state, "db_ok", False)

    # 2. Run LLM pings in parallel
    coder_ok, answer_ok = await asyncio.gather(
        ping_model("MODEL_SQL"),
        ping_model("MODEL_ANSWER")
    )

    db_status = "connected" if db_ok else "error"
    coder_status = "ok" if coder_ok else "error"
    answer_status = "ok" if answer_ok else "error"

    # Status is ok only if all checks passed
    all_ok = db_ok and coder_ok and answer_ok
    status = "ok" if all_ok else "degraded"

    try:
        env = get("APP_ENV")
    except Exception:
        env = "development"

    return {
        "status": status,
        "db": db_status,
        "llm_coder": coder_status,
        "llm_answer": answer_status,
        "env": env
    }

