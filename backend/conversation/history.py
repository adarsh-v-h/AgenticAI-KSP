"""
Conversation history stored in Catalyst NoSQL.

Key:   session_id
Value: JSON array of {role, content} dicts (max MAX_TURNS turns kept)

If the NoSQL service is unreachable or returns an error, the helpers fall back
to an in-memory dict so local dev never breaks. Production would never rely on
the in-memory fallback — it's purely a safety net.

Catalyst NoSQL endpoint shapes can vary by project configuration. The URL
builder in `_nosql_url()` follows the path documented for Step 3; if your
project's NoSQL exposes a different path, only that helper needs to change.
"""

import sys
import json
import asyncio
import httpx

from config.settings import get

MAX_TURNS = 10  # last 10 messages = ~5 user + 5 assistant turns
_NOSQL_TIMEOUT = 5.0

# In-memory fallback so the chat keeps working when NoSQL is unavailable.
# Keyed by session_id, value is the list of {role, content} dicts.
_local_history: dict[str, list[dict]] = {}
_local_lock = asyncio.Lock()


def _nosql_headers() -> dict:
    return {
        "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


def _nosql_url(session_id: str) -> str:
    base = get("NOSQL_BASE_URL").rstrip("/")
    return f"{base}/table/conversation_history/document/{session_id}"


def _nosql_collection_url() -> str:
    base = get("NOSQL_BASE_URL").rstrip("/")
    return f"{base}/table/conversation_history/document"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def _local_get(session_id: str) -> list[dict]:
    async with _local_lock:
        return list(_local_history.get(session_id, []))[-MAX_TURNS:]


async def _local_set(session_id: str, turns: list[dict]) -> None:
    async with _local_lock:
        _local_history[session_id] = turns[-MAX_TURNS:]


async def _local_clear(session_id: str) -> None:
    async with _local_lock:
        _local_history.pop(session_id, None)


async def get_history(session_id: str) -> list[dict]:
    """
    Fetch conversation history for `session_id`. Returns the last MAX_TURNS
    turns as a list of {role, content} dicts. Returns [] if not found.
    Never raises — failure falls back to the in-memory store.
    """
    if not session_id:
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _nosql_url(session_id),
                headers=_nosql_headers(),
                timeout=_NOSQL_TIMEOUT,
            )
            if response.status_code == 200:
                payload = response.json()
                # Catalyst returns the document under "data". The actual
                # field name we wrote ("history") may be a JSON-encoded string.
                doc = payload.get("data") or payload
                raw = doc.get("history") if isinstance(doc, dict) else None
                if raw is None:
                    return await _local_get(session_id)
                turns = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(turns, list):
                    return turns[-MAX_TURNS:]
                return []
            if response.status_code == 404:
                return await _local_get(session_id)
            _log(
                f"history GET unexpected status {response.status_code} "
                f"for {session_id}"
            )
    except Exception as e:
        _log(f"history GET failed for {session_id}: {e}")

    return await _local_get(session_id)


async def save_turn(
    session_id: str, user_message: str, assistant_message: str
) -> None:
    """
    Append a user+assistant turn to the session history. Trims to MAX_TURNS.
    Never raises — failures are logged and the in-memory store is updated so
    the chat keeps working.
    """
    if not session_id:
        return

    existing = await get_history(session_id)
    existing.append({"role": "user", "content": user_message})
    existing.append({"role": "assistant", "content": assistant_message})
    trimmed = existing[-MAX_TURNS:]

    # Always update the in-memory fallback first; it's the source of truth
    # when NoSQL is misbehaving.
    await _local_set(session_id, trimmed)

    document = {"history": json.dumps(trimmed)}

    try:
        async with httpx.AsyncClient() as client:
            url = _nosql_url(session_id)
            response = await client.put(
                url,
                headers=_nosql_headers(),
                json={"data": document},
                timeout=_NOSQL_TIMEOUT,
            )
            if response.status_code in (200, 201, 204):
                return
            if response.status_code == 404:
                # Document doesn't exist — create it.
                create_url = _nosql_collection_url()
                created = await client.post(
                    create_url,
                    headers=_nosql_headers(),
                    json={"data": {**document, "id": session_id}},
                    timeout=_NOSQL_TIMEOUT,
                )
                if created.status_code in (200, 201, 204):
                    return
                _log(
                    f"history POST returned {created.status_code} "
                    f"for {session_id}"
                )
                return
            _log(
                f"history PUT returned {response.status_code} "
                f"for {session_id}"
            )
    except Exception as e:
        _log(f"history PUT failed for {session_id}: {e}")


async def clear_history(session_id: str) -> None:
    """Delete history for `session_id`. Never raises."""
    if not session_id:
        return
    await _local_clear(session_id)
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                _nosql_url(session_id),
                headers=_nosql_headers(),
                timeout=_NOSQL_TIMEOUT,
            )
    except Exception as e:
        _log(f"history DELETE failed for {session_id}: {e}")


async def init_nosql_table() -> None:
    """
    Probe Catalyst NoSQL once at startup. We don't try to create the table
    (the table must be defined in the Catalyst console) — just confirm the
    service is reachable so we can warn early if it isn't. Never raises.
    """
    try:
        async with httpx.AsyncClient() as client:
            base = get("NOSQL_BASE_URL").rstrip("/")
            # A HEAD-style probe — fetching a non-existent doc is enough to
            # confirm auth + path work. 404 is a healthy "service alive" signal.
            response = await client.get(
                f"{base}/table/conversation_history/document/__probe__",
                headers=_nosql_headers(),
                timeout=_NOSQL_TIMEOUT,
            )
            if response.status_code in (200, 404):
                return
            _log(
                f"NoSQL probe returned status {response.status_code}; "
                f"history will fall back to in-memory store."
            )
    except Exception as e:
        _log(f"NoSQL probe failed: {e}; history will use in-memory store.")
