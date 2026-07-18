"""
Catalyst Cache client — thin async wrapper over the Catalyst Cache REST API.

Used by the station rate limiter to persist per-station request counters so
multiple AppSail instances converge on a shared count. Mirrors the structure of
db/nosql_client.py: builds auth headers the same way, talks to Catalyst over
httpx, and never assumes a specific in-process state.

Cache API shape (see Catalyst API reference — Cache):
    POST   {base}/segment/{segment_id}/cache      insert {cache_name, cache_value, expiry_in_hours}
    GET    {base}/segment/{segment_id}/cache?cacheKey=<k>
    PUT    {base}/segment/{segment_id}/cache      update {cache_name, cache_value, expiry_in_hours}
    DELETE {base}/segment/{segment_id}/cache?cacheKey=<k>

Notes:
- The Cache API is a plain key-value store; there is NO atomic increment. The
  rate limiter therefore keeps per-instance counts in memory and only flushes
  aggregate values here on a periodic cadence (see pipeline/rate_limiter.py).
- `expiry_in_hours` maxes out at 48h; our 6h window fits comfortably.
- All calls are best-effort: failures raise CacheError and the caller (the rate
  limiter) is expected to fail OPEN — never block requests because Cache is down.
"""

import httpx

from config.settings import get


class CacheError(Exception):
    """Raised when a Catalyst Cache operation fails."""
    pass


# CONTRACT
# takes:  nothing
# returns: (str) — base project URL for cache calls, with any trailing /cache and slash stripped
# raises:  ValueError — when CACHE_BASE_URL env var is not set
def _cache_base_url() -> str:
    """
    Resolve the base project URL for Cache API calls.

    CACHE_BASE_URL is documented as
      {CATALYST_BASE_URL}/baas/v1/project/{project_id}/cache
    but the actual Cache endpoints live under
      {CATALYST_BASE_URL}/baas/v1/project/{project_id}/segment/{segment_id}/cache
    so we strip a trailing "/cache" (and slash) to get the project root, then
    the callers append the correct "/segment/.../cache" path.
    """
    base = get("CACHE_BASE_URL").rstrip("/")
    if base.endswith("/cache"):
        base = base[: -len("/cache")]
    return base


# CONTRACT
# takes:  nothing
# returns: (dict) — authorization and content-type headers for Catalyst Cache API calls
# raises:  ValueError — when required env vars are not set
def _cache_headers() -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


# CONTRACT
# takes:  nothing
# returns: (str) — the cache segment ID to use, from CACHE_SEGMENT_ID env var
# raises:  ValueError — when CACHE_SEGMENT_ID env var is not set
def _segment_id() -> str:
    return get("CACHE_SEGMENT_ID")


# CONTRACT
# takes:  key (str) — cache key to read
#          timeout (float) — HTTP request timeout in seconds
# returns: (str | None) — the stored string value, or None if the key is absent
# raises:  CacheError — on a non-success, non-empty HTTP response
async def get_value(key: str, timeout: float = 5.0) -> str | None:
    """Fetch a cache value by key. Returns None if the key does not exist."""
    url = f"{_cache_base_url()}/segment/{_segment_id()}/cache"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url, headers=_cache_headers(), params={"cacheKey": key}, timeout=timeout
        )
    if resp.status_code == 200:
        data = (resp.json() or {}).get("data") or {}
        val = data.get("cache_value")
        return val if val is not None else None
    if resp.status_code in (204, 404):
        return None
    raise CacheError(f"Cache GET {key} failed: {resp.status_code} {resp.text[:200]}")


# CONTRACT
# takes:  key (str) — cache key, value (str) — value to store,
#          expiry_in_hours (int) — TTL in hours (1..48), timeout (float) — HTTP timeout
# returns: (bool) — True on success
# raises:  CacheError — on a non-success HTTP response
async def put_value(key: str, value: str, expiry_in_hours: int = 7, timeout: float = 5.0) -> bool:
    """
    Insert or update a cache key. Tries POST (insert) first; on a conflict
    (key already exists) falls back to PUT (update). Catalyst caps
    expiry_in_hours at 48.
    """
    url = f"{_cache_base_url()}/segment/{_segment_id()}/cache"
    payload = {"cache_name": key, "cache_value": str(value), "expiry_in_hours": expiry_in_hours}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_cache_headers(), json=payload, timeout=timeout)
        if resp.status_code in (200, 201):
            return True
        # Key already present (or POST not idempotent) — update instead.
        resp = await client.put(url, headers=_cache_headers(), json=payload, timeout=timeout)
        if resp.status_code in (200, 201):
            return True
    raise CacheError(f"Cache PUT {key} failed: {resp.status_code} {resp.text[:200]}")
