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
import asyncio
import httpx

_clients = {}  # loop -> client


# CONTRACT
# takes:  nothing
# returns: (httpx.AsyncClient) — the newly created shared client
# raises:  nothing
def init_http_client() -> httpx.AsyncClient:
    """Initialize the http client for the current loop."""
    return get_http_client()


# CONTRACT
# takes:  nothing
# returns: (httpx.AsyncClient) — the existing shared client
# raises:  nothing
def get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient resolved for the current loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    global _clients
    if loop not in _clients:
        _clients[loop] = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=30.0,
        )
    return _clients[loop]


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing
async def close_http_client() -> None:
    """Close all shared AsyncClients."""
    global _clients
    for client in list(_clients.values()):
        try:
            await client.aclose()
        except Exception:
            pass
    _clients.clear()
