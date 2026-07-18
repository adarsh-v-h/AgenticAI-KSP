"""
Catalyst OAuth access-token manager.

THE PROBLEM this solves:
    Every Catalyst API call (LLM, NoSQL, Cache, RAG, voice) authenticates with a
    `Zoho-oauthtoken {access_token}` header. That access token expires in ~1
    hour. The old code read a STATIC `CATALYST_API_TOKEN` baked into the deploy
    at build time, so ~1 hour after every deploy all Catalyst-backed features
    (LLM answers, chat history, RAG, voice) started failing with 401 until
    someone manually rotated the token and redeployed.

THE FIX:
    Zoho OAuth refresh tokens do NOT expire. This module holds the client id /
    secret / refresh token and mints a fresh access token on demand via the
    OAuth token endpoint, caching it in memory until shortly before it expires.
    Callers ask for `get_access_token()` instead of reading the env var, so the
    running backend keeps itself authenticated indefinitely — no redeploys, no
    manual rotation.

FALLBACK / FAIL-SAFE:
    - If the refresh credentials are not configured, we fall back to the static
      `CATALYST_API_TOKEN` env var (old behaviour) so nothing breaks in envs
      that haven't set the refresh creds yet.
    - If a refresh call fails but we still hold a cached token, we keep using
      the cached token and log a warning rather than crashing a request.

CONCURRENCY:
    A single asyncio lock guards the refresh so a burst of simultaneous requests
    triggers exactly one network refresh, not N. The hot path (token still
    valid) never touches the lock.
"""

import asyncio
import sys
import time

import httpx

from config.settings import get

# How many seconds before actual expiry we proactively refresh. Zoho access
# tokens live ~3600s; refreshing with a 5-minute safety margin avoids handing
# out a token that dies mid-request.
_EXPIRY_SKEW_SECONDS = 300
# Default assumed lifetime when the token response omits expires_in.
_DEFAULT_LIFETIME_SECONDS = 3600

# In-memory cache of the current access token.
_cached_token: str | None = None
_expires_at: float = 0.0  # epoch seconds when the cached token should be renewed
_lock = asyncio.Lock()


# CONTRACT
# takes:  nothing
# returns: (str | None) — the accounts OAuth token endpoint, or None if not resolvable
# raises:  nothing
def _accounts_url() -> str | None:
    """
    Resolve the OAuth token endpoint. Prefer an explicit CATALYST_ACCOUNTS_URL;
    otherwise derive the region from CATALYST_BASE_URL
    (api.catalyst.zoho.in -> accounts.zoho.in).
    """
    try:
        return get("CATALYST_ACCOUNTS_URL")
    except Exception:
        pass
    try:
        base = get("CATALYST_BASE_URL")  # e.g. https://api.catalyst.zoho.in
    except Exception:
        return None
    # Take the TLD suffix after "zoho." to build accounts.zoho.<tld>.
    for tld in (".zoho.in", ".zoho.com", ".zoho.eu", ".zoho.com.au", ".zoho.jp"):
        if tld in base:
            return f"https://accounts{tld}/oauth/v2/token"
    return "https://accounts.zoho.com/oauth/v2/token"


# CONTRACT
# takes:  nothing
# returns: (tuple[str, str, str] | None) — (client_id, client_secret, refresh_token) or None if any missing
# raises:  nothing
def _refresh_credentials():
    try:
        return (
            get("CATALYST_CLIENT_ID"),
            get("CATALYST_CLIENT_SECRET"),
            get("CATALYST_REFRESH_TOKEN"),
        )
    except Exception:
        return None


# CONTRACT
# takes:  nothing
# returns: (str | None) — the static bootstrap access token, or None if unset
# raises:  nothing
def _static_token() -> str | None:
    try:
        return get("CATALYST_API_TOKEN")
    except Exception:
        return None


# CONTRACT
# takes:  timeout (float) — HTTP timeout for the OAuth call
# returns: (str) — a freshly minted access token
# raises:  RuntimeError — when refresh creds/endpoint are missing or the response has no access_token,
#           httpx.HTTPError — on network/HTTP failure
async def _refresh_access_token(timeout: float = 15.0) -> str:
    creds = _refresh_credentials()
    url = _accounts_url()
    if not creds or not url:
        raise RuntimeError("Catalyst refresh credentials are not configured.")
    client_id, client_secret, refresh_tok = creds

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_tok,
            },
            timeout=timeout,
        )
    resp.raise_for_status()
    data = resp.json() or {}
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"OAuth refresh returned no access_token: {data}")

    lifetime = int(data.get("expires_in") or _DEFAULT_LIFETIME_SECONDS)
    global _cached_token, _expires_at
    _cached_token = token
    _expires_at = time.time() + max(0, lifetime - _EXPIRY_SKEW_SECONDS)
    return token


# CONTRACT
# takes:  nothing
# returns: (str) — a valid Catalyst OAuth access token
# raises:  RuntimeError — only when no cached token, no refresh creds, AND no static token exist
async def get_access_token() -> str:
    """
    Return a valid access token, refreshing transparently when the cached one is
    near expiry. This is what all Catalyst clients should call instead of
    reading CATALYST_API_TOKEN directly.

    Order of precedence:
      1. Cached token that is still fresh                → return immediately.
      2. Refresh creds available                         → mint a new token.
      3. Refresh failed but a cached token exists        → reuse it (warn).
      4. No refresh creds                                → static env token.
    """
    global _cached_token, _expires_at

    now = time.time()
    if _cached_token and now < _expires_at:
        return _cached_token

    # No refresh creds → old static behaviour (bootstrap / dev without refresh).
    if _refresh_credentials() is None:
        static = _static_token()
        if static:
            return static
        raise RuntimeError(
            "No Catalyst access token available: refresh credentials are unset "
            "and CATALYST_API_TOKEN is empty."
        )

    async with _lock:
        # Re-check after acquiring the lock — another coroutine may have just
        # refreshed while we were waiting.
        now = time.time()
        if _cached_token and now < _expires_at:
            return _cached_token
        try:
            return await _refresh_access_token()
        except Exception as e:  # noqa: BLE001
            # Refresh failed. Prefer a (possibly stale) cached token, then the
            # static env token, over crashing the caller.
            if _cached_token:
                print(
                    f"WARNING: Catalyst token refresh failed, reusing cached token: {e}",
                    file=sys.stderr,
                )
                return _cached_token
            static = _static_token()
            if static:
                print(
                    f"WARNING: Catalyst token refresh failed, falling back to static token: {e}",
                    file=sys.stderr,
                )
                return static
            raise


# CONTRACT
# takes:  nothing
# returns: nothing (forces the next get_access_token() to refresh)
# raises:  nothing
def invalidate() -> None:
    """
    Drop the cached token so the next get_access_token() re-mints one. Call this
    when a Catalyst call returns 401 despite a supposedly-valid cached token
    (e.g. the token was revoked server-side).
    """
    global _cached_token, _expires_at
    _cached_token = None
    _expires_at = 0.0


# CONTRACT
# takes:  nothing
# returns: nothing (test helper: resets module state)
# raises:  nothing
def _reset_for_tests() -> None:
    invalidate()
