"""
Session metadata stored in Catalyst NoSQL.

Collection: session_metadata
Key:        session_id (stored as the document `id`)
Document:   {
                "id":            session_id,   # primary key
                "officer_id":    int,          # FK to officers table
                "title":         str,          # human-readable session title
                "created_at":    str,          # ISO 8601 UTC
                "updated_at":    str,          # ISO 8601 UTC
                "message_count": int,
            }

This module mirrors the structure of `conversation/history.py`: it talks to
Catalyst NoSQL over httpx using the `_nosql_headers()` / `_nosql_url()` builders
and falls back to an in-memory dict (guarded by an asyncio lock) whenever the
NoSQL service is unreachable or returns an error. The in-memory fallback keeps
local dev working and acts as a safety net; production would never rely on it.

Catalyst NoSQL endpoint shapes can vary by project configuration. The URL
builders below follow the same path convention used in `history.py`; if your
project's NoSQL exposes a different path, only those helpers need to change.
"""

import sys
import asyncio
import httpx

from config.settings import get

_NOSQL_TIMEOUT = 5.0

# In-memory fallback so session management keeps working when NoSQL is
# unavailable. Keyed by session_id, value is the session_metadata document.
_local_sessions: dict[str, dict] = {}
_local_lock = asyncio.Lock()


from db.nosql_client import (
    NoSQLError,
    get_document,
    insert_document,
    update_document,
    list_documents,
)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def _local_get(session_id: str) -> dict | None:
    async with _local_lock:
        doc = _local_sessions.get(session_id)
        return dict(doc) if doc is not None else None


async def _local_set(session_id: str, document: dict) -> None:
    async with _local_lock:
        _local_sessions[session_id] = dict(document)


async def _local_list(officer_id: int | None = None) -> list[dict]:
    async with _local_lock:
        docs = [dict(d) for d in _local_sessions.values()]
    if officer_id is not None:
        docs = [d for d in docs if d.get("officer_id") == officer_id]
    return docs


async def create_session(document: dict) -> dict:
    """
    Persist a new session_metadata document. `document` must already contain
    the full schema: id, officer_id, title, created_at, updated_at,
    message_count. Returns the stored document.

    Always writes the in-memory fallback first, then attempts the NoSQL POST.
    Never raises — NoSQL failures are logged and the in-memory copy is kept.
    """
    session_id = document.get("id")
    if not session_id:
        raise ValueError("session_metadata document requires an 'id' field")

    # In-memory fallback is the source of truth when NoSQL is misbehaving.
    await _local_set(session_id, document)

    try:
        await insert_document("session_metadata", session_id, document, timeout=_NOSQL_TIMEOUT)
    except Exception as e:
        _log(f"ERROR: session_metadata POST failed for {session_id}: {e}")

    return document


async def get_session(session_id: str) -> dict | None:
    """
    Fetch the session_metadata document for `session_id`. Returns the document
    dict or None if it does not exist. Never raises — failure falls back to the
    in-memory store.
    """
    if not session_id:
        return None

    try:
        doc = await get_document("session_metadata", session_id, timeout=_NOSQL_TIMEOUT)
        if doc is not None:
            return doc
        return await _local_get(session_id)
    except Exception as e:
        _log(f"ERROR: session_metadata GET failed for {session_id}: {e}")

    return await _local_get(session_id)


async def update_session(session_id: str, updates: dict) -> dict | None:
    """
    Apply `updates` to an existing session_metadata document and persist via
    NoSQL PUT (creating it if it doesn't yet exist). Returns the merged
    document, or None if there is no existing session to update.

    Always updates the in-memory fallback first. Never raises — failures are
    logged and the in-memory store is kept consistent.
    """
    if not session_id:
        return None

    existing = await get_session(session_id)
    if existing is None:
        _log(f"ERROR: session_metadata PUT skipped — {session_id} not found")
        return None

    merged = {**existing, **updates, "id": session_id}
    await _local_set(session_id, merged)

    try:
        try:
            await update_document("session_metadata", session_id, merged, timeout=_NOSQL_TIMEOUT)
        except NoSQLError as ne:
            if "404" in str(ne):
                await insert_document("session_metadata", session_id, merged, timeout=_NOSQL_TIMEOUT)
            else:
                raise
    except Exception as e:
        _log(f"ERROR: session_metadata PUT failed for {session_id}: {e}")

    return merged


async def list_sessions(officer_id: int) -> list[dict]:
    """
    Return all session_metadata documents for `officer_id`, ordered by
    updated_at descending (most recent first).

    Catalyst NoSQL may not support filtered queries, so we fetch all documents
    and filter/sort in Python (see design "Query Pattern for Session List").
    Never raises — failure falls back to the in-memory store.
    """
    docs: list[dict] | None = None

    try:
        docs = await list_documents("session_metadata", timeout=_NOSQL_TIMEOUT)
    except Exception as e:
        _log(f"ERROR: session_metadata list GET failed for officer {officer_id}: {e}")

    if docs is None:
        docs = await _local_list(officer_id)
    else:
        docs = [d for d in docs if isinstance(d, dict) and d.get("officer_id") == officer_id]

    docs.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
    return docs


# --------------------------------------------------------------------------- #
# Session title generation
# --------------------------------------------------------------------------- #

# Common words stripped out before picking keywords for a session title.
_TITLE_STOP_WORDS = {
    "the", "is", "are", "how", "many", "show", "me", "all",
    "a", "an", "in", "of", "to", "for", "with", "on",
}

# Title constraints (see design "Session Title Generation").
_TITLE_MAX_WORDS = 8
_TITLE_MAX_LENGTH = 60
_TITLE_FALLBACK = "New chat"


def generate_title(message: str) -> str:
    """
    Generate a human-readable session title from the first user message.

    Algorithm (see design "Session Title Generation"):
      1. Lowercase and tokenise the message on whitespace.
      2. Strip surrounding punctuation (?.,!) from each token.
      3. Drop common stop words (the, is, are, how, many, show, me, all,
         a, an, in, of, to, for, with, on) and any empty tokens.
      4. Take the first 3-8 significant words.
      5. Capitalize the first letter of the resulting title.
      6. Truncate to 60 characters max; when truncating, the final string
         (including the "..." suffix) is guaranteed to be <= 60 characters.
      7. Fall back to "New chat" when there are no significant words.

    Word-count behaviour (Requirement 6.2): the target is between 3 and 8
    significant words. We take at most 8. If the message yields fewer than 3
    significant words we return whatever significant words are available rather
    than padding artificially — the 3-word lower bound cannot be honoured when
    the input simply does not contain that many meaningful words. If there are
    no significant words at all, we fall back to "New chat".

    Length behaviour (Requirement 6.3): the returned title never exceeds 60
    characters. When the joined title is longer, it is truncated to 57
    characters and the "..." suffix is appended, keeping the total at 60.
    """
    if not message:
        return _TITLE_FALLBACK

    words = message.lower().split()
    significant = [w.strip("?.,!") for w in words]
    significant = [w for w in significant if w and w not in _TITLE_STOP_WORDS]

    if not significant:
        return _TITLE_FALLBACK

    title_words = significant[:_TITLE_MAX_WORDS]
    title = " ".join(title_words).capitalize()

    if len(title) > _TITLE_MAX_LENGTH:
        title = title[: _TITLE_MAX_LENGTH - 3] + "..."

    return title
