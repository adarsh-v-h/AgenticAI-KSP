"""
Shared, long-lived httpx.AsyncClient for every outbound Catalyst call (LLM,
NoSQL, Cache, RAG, voice, OAuth token refresh).

Why a singleton:
Every outbound call in this codebase talks to Catalyst over HTTPS. Creating a
fresh `httpx.AsyncClient()` per call pays a new TCP + TLS handshake every
single time -- pure added latency, and wasteful on a 2-shared-vCPU box under
concurrent load. A single shared client keeps a small pool of warm,
keep-alive connections that get reused across requests instead.

Created once during FastAPI startup (see main.py's lifespan) and closed on
shutdown. Call `get_http_client()` to use it -- never instantiate
`httpx.AsyncClient()` directly at a Catalyst call site.
"""
import httpx

_client: httpx.AsyncClient | None = None


# CONTRACT
# takes:  nothing
# returns: (httpx.AsyncClient) — the newly created shared client
# raises:  nothing
def init_http_client() -> httpx.AsyncClient:
    """
    Create the shared AsyncClient. Called once during FastAPI startup.
    Pool sized small and deliberately, given 2 shared vCPUs / limited RAM.
    Per-call timeouts are still set at each call site via the `timeout=`
    kwarg on individual requests, so this default is just a safety net.
    """
    global _client
    _client = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        timeout=30.0,
    )
    return _client


# CONTRACT
# takes:  nothing
# returns: (httpx.AsyncClient) — the existing shared client
# raises:  RuntimeError — when the client has not been created yet
def get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient. Mirrors db/connection.py's get_pool()."""
    if _client is None:
        raise RuntimeError("Shared HTTP client has not been created yet.")
    return _client


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing
async def close_http_client() -> None:
    """Close the shared AsyncClient. Called once during FastAPI shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
