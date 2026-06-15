"""
Catalyst Cache wrappers.
Used (optionally) for: schema string caching with a 1-hour TTL.

All helpers are non-fatal: failures fall back to a small in-process LRU dict
so callers never need to think about cache outages.
"""

import sys
import time
import asyncio
import httpx

from config.settings import get

_CACHE_TIMEOUT = 3.0
_LOCAL_TTL_FALLBACK_SECS = 3600

_local_cache: dict[str, tuple[float, str]] = {}
_local_lock = asyncio.Lock()


def _cache_headers() -> dict:
    return {
        "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


def _cache_url(key: str) -> str:
    base = get("CACHE_BASE_URL").rstrip("/")
    return f"{base}/{key}"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def _local_get(key: str) -> str | None:
    async with _local_lock:
        entry = _local_cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            _local_cache.pop(key, None)
            return None
        return value


async def _local_set(key: str, value: str, ttl_seconds: int) -> None:
    async with _local_lock:
        _local_cache[key] = (time.time() + ttl_seconds, value)


async def cache_get(key: str) -> str | None:
    """
    Return cached value for `key`, or None on miss/error.
    Never raises.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _cache_url(key),
                headers=_cache_headers(),
                timeout=_CACHE_TIMEOUT,
            )
            if response.status_code == 200:
                payload = response.json()
                doc = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(doc, dict):
                    val = doc.get("value")
                    if isinstance(val, str):
                        return val
                # Some Catalyst Cache deployments put the value at the top level.
                if isinstance(payload, dict) and isinstance(payload.get("value"), str):
                    return payload["value"]
            if response.status_code != 404:
                _log(
                    f"cache GET unexpected status {response.status_code} "
                    f"for {key}"
                )
    except Exception as e:
        _log(f"cache GET failed for {key}: {e}")

    return await _local_get(key)


async def cache_set(key: str, value: str, ttl_seconds: int = 3600) -> None:
    """
    Store `value` under `key` with a TTL. Never raises.
    """
    # Always update the in-process fallback first.
    await _local_set(key, value, min(ttl_seconds, _LOCAL_TTL_FALLBACK_SECS))

    try:
        async with httpx.AsyncClient() as client:
            await client.put(
                _cache_url(key),
                headers=_cache_headers(),
                json={"value": value, "ttl": ttl_seconds},
                timeout=_CACHE_TIMEOUT,
            )
    except Exception as e:
        _log(f"cache SET failed for {key}: {e}")


def _schema_cache_key(table_names: list[str]) -> str:
    # Catalyst Cache keys must be URL-safe — stick to ASCII, no slashes.
    safe = "_".join(sorted(t.replace("/", "_") for t in table_names))
    return f"schema_{safe}"


async def get_cached_schema(table_names: list[str]) -> str | None:
    return await cache_get(_schema_cache_key(table_names))


async def set_cached_schema(table_names: list[str], schema_str: str) -> None:
    await cache_set(_schema_cache_key(table_names), schema_str, ttl_seconds=3600)
