import sys
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

# Ensure the backend directory is in the import path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config.settings import validate_settings, get
from db.connection import create_pool, close_pool
from http_client import init_http_client, close_http_client
from llm.client import ping_model
from voice.zia_voice import ping_voice
from routers.chat import router as chat_router
from routers.auth import router as auth_router
from routers.export import router as export_router
from routers.reports import router as reports_router
from routers.voice import router as voice_router
from routers.governance import router as governance_router
from routers.analytics import router as analytics_router
from routers.decision_support import router as decision_support_router
from routers.profiling import router as profiling_router
from routers.ticker import router as ticker_router
from conversation.history import init_nosql_table
from pipeline.rate_limiter import start_rate_limiter, stop_rate_limiter
from config.catalyst_token import get_access_token

# CONTRACT
# takes:  app (FastAPI) — the FastAPI application instance
# returns: nothing (async context manager yields after startup, runs shutdown after)
# raises:  nothing (DB/NoSQL failures are logged as warnings, never crash startup)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # â”€â”€ STARTUP â”€â”€
    # 1. Validate all env vars â€” crash loudly if anything missing
    validate_settings()

    # 1a. Create the shared httpx.AsyncClient used by every outbound Catalyst
    # call (LLM, NoSQL, Cache, RAG, voice, OAuth). Must exist before anything
    # below that makes an HTTP call.
    init_http_client()

    # 1b. Warm up the Catalyst OAuth token so the first real request doesn't pay
    # the refresh latency, and so a bad refresh config surfaces at startup. The
    # token manager auto-refreshes thereafter (tokens live ~1h). Non-fatal:
    # falls back to the static CATALYST_API_TOKEN.
    try:
        await get_access_token()
    except Exception as e:
        print(f"WARNING: Catalyst token warm-up failed (will retry on demand): {e}", file=sys.stderr)

    # 2. Create DB connection pool
    await create_pool()

    # 2b. Start standalone gRPC servers for LLM and SQL services
    try:
        from llm.grpc_server import start_llm_grpc_server
        from db.grpc_server import start_sql_grpc_server
        await start_llm_grpc_server()
        await start_sql_grpc_server()
    except Exception as e:
        print(f"WARNING: gRPC servers startup failed: {e}", file=sys.stderr)

    # 5. Start the station rate-limiter background sync loop. It flushes local
    # request counts to Catalyst Cache and refreshes per-station caps from
    # MySQL every ~30s. Failure here must not crash startup — the limiter fails
    # OPEN if it can't run.
    try:
        start_rate_limiter()
    except Exception as e:
        print(f"WARNING: rate limiter failed to start (rate limiting disabled): {e}", file=sys.stderr)

    # 6. Start LLM & Voice keep-warm background task to avoid serverless cold starts
    # Run the first warm-up ping and initialization in the background so it doesn't block startup.
    async def _keep_warm_loop():
        try:
            # 2a. Populate in-memory lookup cache for Unit, CrimeSubHead, and CaseStatusMaster
            try:
                from db.lookup_cache import init_lookup_cache
                await init_lookup_cache()
            except Exception as e:
                print(f"WARNING: Lookup cache initialization failed: {e}", file=sys.stderr)

            # 3. Confirm DB is reachable (run a trivial query)
            try:
                from db.connection import execute_query
                await execute_query("SELECT 1")
                app.state.db_ok = True
            except Exception as e:
                print(f"WARNING: DB connection check failed: {e}", file=sys.stderr)
                app.state.db_ok = False

            # 4. Probe Catalyst NoSQL so we surface auth/path issues at startup.
            try:
                await init_nosql_table()
            except Exception as e:
                print(f"WARNING: NoSQL init failed (history will use in-memory store): {e}", file=sys.stderr)

            # 6. Eager background warm-up
            await asyncio.gather(
                ping_model("MODEL_SQL"),
                ping_model("MODEL_ANSWER"),
                ping_voice(),
                return_exceptions=True
            )
        except Exception as e:
            print(f"WARNING: Eager background warm-up failed: {e}", file=sys.stderr)

        while True:
            await asyncio.sleep(300)
            try:
                await asyncio.gather(
                    ping_model("MODEL_SQL"),
                    ping_model("MODEL_ANSWER"),
                    ping_voice(),
                    return_exceptions=True
                )
            except Exception as e:
                print(f"WARNING: Keep-warm loop error: {e}", file=sys.stderr)

    keep_warm_task = asyncio.create_task(_keep_warm_loop())

    # 7. Build intelligence ticker cache (fire-and-forget; non-fatal)
    #    Also starts a 2-hour background refresh loop so the ticker stays
    #    current without a restart.
    async def _ticker_loop():
        try:
            from pipeline.intelligence_ticker import build_intelligence_cache
            await build_intelligence_cache()
        except Exception as e:
            print(f"WARNING: Initial intelligence cache build failed: {e}", file=sys.stderr)
        # Refresh every 2 hours
        while True:
            await asyncio.sleep(2 * 60 * 60)
            try:
                from pipeline.intelligence_ticker import build_intelligence_cache
                await build_intelligence_cache()
            except Exception as e:
                print(f"WARNING: Intelligence cache refresh failed: {e}", file=sys.stderr)

    ticker_task = asyncio.create_task(_ticker_loop())

    # This is the dividing line between startup and shutdown.
    # Everything before yield runs when the app starts.
    yield
    # Everything after yield runs when the app stops.

    # ── SHUTDOWN ──
    keep_warm_task.cancel()
    ticker_task.cancel()
    try:
        await keep_warm_task
    except asyncio.CancelledError:
        pass
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass

    try:
        await stop_rate_limiter()
    except Exception as e:
        print(f"WARNING: rate limiter shutdown error: {e}", file=sys.stderr)

    # Stop gRPC servers and close clients
    try:
        from llm.grpc_server import stop_llm_grpc_server
        from db.grpc_server import stop_sql_grpc_server
        from llm.client import close_llm_client
        from db.connection import close_sql_client
        await stop_llm_grpc_server()
        await stop_sql_grpc_server()
        await close_llm_client()
        await close_sql_client()
    except Exception as e:
        print(f"WARNING: gRPC servers shutdown failed: {e}", file=sys.stderr)

    await close_pool()
    await close_http_client()


app = FastAPI(
    title="KSP Crime Intelligence API",
    version="0.4.0-step4",
    docs_url="/docs",       # keep Swagger available during dev
    redoc_url=None,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,  # faster JSON serialization on chat/API payloads
)

# CORS — allow the configured frontend origin(s), never wildcard.
#
# IMPORTANT: Catalyst's AppSail proxy (ZGS) answers CORS preflight OPTIONS
# requests itself and injects Access-Control-Allow-Origin ONLY for the project's
# own Web Client Hosting domain (*.catalystserverless.in). It does NOT do this
# for external domains like Catalyst Slate (*.onslate.in), and it intercepts
# OPTIONS before our app sees them — so app-level CORS cannot help a Slate
# frontend. The frontend must therefore be served from this project's Web Client
# Hosting so the proxy handles CORS natively.
#
# We still register CORSMiddleware for local dev (Vite dev server hitting the
# backend directly) and as a belt-and-braces layer for the actual (non-OPTIONS)
# responses.
from fastapi.middleware.cors import CORSMiddleware

_allowed_origins = ["http://localhost:5173"]
try:
    extra = get("ALLOWED_ORIGINS")
    for o in extra.split(","):
        o = o.strip()
        if o and o not in _allowed_origins:
            _allowed_origins.append(o)
except Exception:
    pass

# In production on Catalyst, the proxy already adds the CORS header for the Web
# Client Hosting origin. Adding our own CORSMiddleware there would emit a SECOND
# Access-Control-Allow-Origin header and the browser would reject the response.
# So enable CORSMiddleware only outside production (local dev / direct access).
try:
    _is_production = get("APP_ENV") == "production"
except Exception:
    _is_production = False

if not _is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
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


# Station-wide rate limiting.
#
# Scoped per police-station (Unit.UnitID), NOT per-officer. The station id is
# read from the signed JWT — never from the request body/params — so a crafted
# request can't drain another station's budget. The check itself is a pure
# in-memory dict lookup (zero network I/O on the request path); a background
# task (see pipeline/rate_limiter) periodically converges counts across
# instances via Catalyst Cache and refreshes caps from MySQL.
#
# Applies to /api/* only, and skips the endpoints an officer must reach to get
# or refresh a token / check health.
from starlette.responses import JSONResponse
from pipeline.rate_limiter import check_and_increment, WINDOW_SECONDS
from auth.simple_auth import ALGORITHM
from jose import jwt, JWTError

# Paths under /api that consume station rate limit quota (AI generation / expensive tasks only).
# Reading sessions, fetching messages, exports, analytics, and auth are NEVER rate limited.
_RATE_LIMITED_PATHS = {
    "/api/chat",
    "/api/chat/stream",
    "/api/reports/analyze",
    "/api/voice/speak",
    "/api/voice/transcribe",
}


# CONTRACT
# takes:  request (Request) — the incoming HTTP request
# returns: (tuple[int | None, str | None]) — (unit_id, unit_name) from the JWT, or
#          (None, None) when there is no valid token / no unit claim
# raises:  nothing (any decode failure → (None, None); auth layer enforces real auth)
def _station_from_request(request) -> tuple:
    token = None
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.query_params.get("token")  # SSE EventSource fallback
    if not token:
        return None, None
    try:
        payload = jwt.decode(token, get("APP_SECRET_KEY"), algorithms=[ALGORITHM])
    except (JWTError, Exception):  # noqa: BLE001 — bad token → not our job to 401 here
        return None, None
    return payload.get("unit_id"), payload.get("unit_name")


class _StationRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path not in _RATE_LIMITED_PATHS:
            return await call_next(request)

        unit_id, unit_name = _station_from_request(request)
        result = check_and_increment(unit_id)
        if not result.allowed:
            body = {
                "error": "rate_limit_exceeded",
                "station": unit_name or f"Unit {result.unit_id}",
                "detail": (
                    f"Your station ({unit_name or 'your unit'}) has reached its shared "
                    f"request limit of {result.cap} for the current 6-hour window "
                    f"({result.used} used). Access resumes automatically when the "
                    "window resets."
                ),
                "unit_id": result.unit_id,
                "limit": result.cap,
                "used": result.used,
                "window_seconds": WINDOW_SECONDS,
                "window_reset_at": result.reset_at,
                "retry_after_seconds": result.retry_after,
            }
            return JSONResponse(
                status_code=429,
                content=body,
                headers={"Retry-After": str(result.retry_after)},
            )
        return await call_next(request)


app.add_middleware(_StationRateLimitMiddleware)


# Response compression (gzip).
#
# Starlette's GZipMiddleware only kicks in when the client's Accept-Encoding
# header includes "gzip" (every browser sends this automatically) — there is
# NO frontend code needed; fetch()/XMLHttpRequest decompress transparently via
# the standard Content-Encoding response header.
#
# Excluded: /api/chat/stream. GZipMiddleware treats any streaming response
# (more_body=True on each chunk, which SSE always is) as a "streaming gzip"
# response and wraps EVERY chunk through gzip regardless of size — that would
# buffer each token event through compression, fighting the
# `X-Accel-Buffering: no` header and the token-by-token flush this endpoint
# depends on for its real-time feel. Every other endpoint returns a normal
# (non-streaming) JSON body and benefits from compression with no downside.
#
# Subclassing (rather than wrapping a separately-constructed GZipMiddleware
# instance) matters here: Starlette wires each middleware's `self.app` to the
# correct next-inner-app when it builds the stack (`cls(app=app, **kwargs)` in
# Starlette.build_middleware_stack) — constructing a GZipMiddleware(app, ...)
# ourselves at decoration time would bind it to the wrong app reference and
# create a parallel, incorrectly-ordered branch instead of a link in the chain.
from fastapi.middleware.gzip import GZipMiddleware

_SSE_EXCLUDED_PATHS = {"/api/chat/stream"}


class _ConditionalGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in _SSE_EXCLUDED_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


app.add_middleware(_ConditionalGZipMiddleware, minimum_size=1000)


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(export_router)
app.include_router(reports_router)
app.include_router(voice_router)
app.include_router(governance_router)
app.include_router(analytics_router)
app.include_router(decision_support_router)
app.include_router(profiling_router)
app.include_router(ticker_router)


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


@app.post("/internal/warm")
async def warm_endpoint():
    """
    Lightweight endpoint to warm up LLM models and Zia voice/translation services.
    Can be called by external scheduler/cron or Catalyst Job Scheduling.
    """
    await asyncio.gather(
        ping_model("MODEL_SQL"),
        ping_model("MODEL_ANSWER"),
        ping_voice(),
        return_exceptions=True
    )
    return {"status": "success", "message": "Pings dispatched successfully"}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT", 9000))
    # CRITICAL: host must be 0.0.0.0 for AppSail to reach the container
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=2, loop="uvloop")


