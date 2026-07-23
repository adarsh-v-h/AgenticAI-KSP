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
import orjson
import uuid
import asyncio
from datetime import datetime, timezone

from conversation.session_store import (
    generate_title,
    get_session,
    update_session,
    _TITLE_FALLBACK,
)

MAX_TURNS = 10  # last 10 messages = ~5 user + 5 assistant turns
_NOSQL_TIMEOUT = 5.0

# Max rows of an assistant turn's result set kept in history for follow-up
# (DIRECT) answers. Bounded so the stored NoSQL document stays small.
_TABLE_SNAPSHOT_ROWS = 30

# Deterministic fallback timestamp for legacy messages that predate the
# message_id/timestamp schema. Using a fixed epoch keeps lazy migration
# deterministic (same input → same output) and sorts legacy messages before
# any real, timestamped message.
_LEGACY_TIMESTAMP = "1970-01-01T00:00:00+00:00"


# CONTRACT
# takes:  nothing
# returns: (str) — unique message ID prefixed with 'm-'
# raises:  nothing
def _new_message_id() -> str:
    """Generate a unique message_id prefixed with 'm-'."""
    return f"m-{uuid.uuid4()}"


# CONTRACT
# takes:  nothing
# returns: (str) — current UTC time as ISO 8601 string
# raises:  nothing
def _now_iso() -> str:
    """Current time as an ISO 8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


# CONTRACT
# takes:  turns (list[dict]) — raw message dicts from storage, possibly missing message_id/timestamp
# returns: (list[dict]) — fresh list of message dicts with message_id and timestamp guaranteed
# raises:  nothing
def _migrate_messages(turns: list[dict]) -> list[dict]:
    """
    Lazy migration: ensure every message has a `message_id` and `timestamp`.

    Legacy messages (saved before the enhanced schema) lack these fields. We
    assign them deterministically so repeated reads of the same stored document
    yield stable ids: message_id is derived from the message's position
    (`m-legacy-{index}`) and timestamp falls back to a fixed epoch value.

    Messages that already carry both fields are returned unchanged. The
    returned list is always a fresh copy of dicts (callers may mutate it).
    """
    migrated: list[dict] = []
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        msg = dict(turn)
        if not msg.get("message_id"):
            msg["message_id"] = f"m-legacy-{index}"
        if not msg.get("timestamp"):
            msg["timestamp"] = _LEGACY_TIMESTAMP
        migrated.append(msg)
    return migrated

# In-memory fallback so the chat keeps working when NoSQL is unavailable.
# Keyed by session_id, value is the list of {role, content} dicts.
_local_history: dict[str, list[dict]] = {}
_local_lock = asyncio.Lock()


from db.nosql_client import (
    NoSQLError,
    get_document,
    insert_document,
    update_document,
)


# CONTRACT
# takes:  msg (str) — message to log
# returns: nothing
# raises:  nothing
def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# CONTRACT
# takes:  session_id (str) — session identifier
# returns: (list[dict]) — last MAX_TURNS messages from in-memory store
# raises:  nothing
async def _local_get(session_id: str) -> list[dict]:
    async with _local_lock:
        return list(_local_history.get(session_id, []))[-MAX_TURNS:]


# CONTRACT
# takes:  session_id (str) — session identifier, turns (list[dict]) — messages to store
# returns: nothing
# raises:  nothing
async def _local_set(session_id: str, turns: list[dict]) -> None:
    async with _local_lock:
        _local_history[session_id] = turns[-MAX_TURNS:]


# CONTRACT
# takes:  session_id (str) — session identifier to clear
# returns: nothing
# raises:  nothing
async def _local_clear(session_id: str) -> None:
    async with _local_lock:
        _local_history.pop(session_id, None)


# CONTRACT
# takes:  session_id (str) — session identifier to fetch history for
# returns: (list[dict]) — last MAX_TURNS messages with message_id and timestamp fields
# raises:  nothing (falls back to in-memory store on failure)
async def get_history(session_id: str) -> list[dict]:
    """
    Fetch conversation history for `session_id`. Returns the last MAX_TURNS
    turns as a list of message dicts. Each returned message includes
    `message_id` and `timestamp` fields; legacy messages stored before the
    enhanced schema are lazily migrated on read (see `_migrate_messages`).
    Returns [] if not found. Never raises — failure falls back to the
    in-memory store.
    """
    if not session_id:
        return []

    try:
        doc = await get_document("conversation_history", session_id, timeout=_NOSQL_TIMEOUT, key_name="session_id")
        if doc is not None:
            raw = doc.get("history")
            if raw is None:
                return await _local_get(session_id)
            turns = orjson.loads(raw) if isinstance(raw, str) else raw
            if isinstance(turns, list):
                return _migrate_messages(turns[-MAX_TURNS:])
            return []
        else:
            return await _local_get(session_id)
    except Exception as e:
        _log(f"ERROR: history GET failed for {session_id}: {e}")

    return await _local_get(session_id)


# CONTRACT
# takes:  session_id (str) — session identifier, user_message (str) — first user message text, had_prior_messages (bool) — whether session had prior history, messages_added (int) — count of messages just persisted, now (str) — ISO timestamp of the save
# returns: nothing
# raises:  nothing (never raises, logs failures internally)
async def _sync_session_metadata(
    session_id: str,
    user_message: str,
    had_prior_messages: bool,
    messages_added: int,
    now: str,
) -> None:
    """
    Sync session_metadata after a turn is saved to conversation_history.

    On every call we refresh `message_count` and `updated_at`. When this turn
    contains the session's first user message, we also generate a title from
    the user message and persist it.

    message_count semantics (Requirements 5.2, 13.5 — and the sidebar count
    shown per Req 5.4 / 9.2): the count is maintained *monotonically*. We read
    the existing metadata's `message_count` and add `messages_added` (the
    number of messages persisted this turn — one user + one assistant = 2).
    We deliberately do NOT derive the count from the in-memory history length,
    because that list is trimmed to MAX_TURNS; using it would under-report the
    true message count for long sessions. When no metadata doc exists yet, the
    count is initialised from `messages_added` (existing count treated as 0).

    "First user message" detection is robust: it triggers when the session had
    no prior history (`had_prior_messages` is False) OR when the existing
    metadata still looks brand new (message_count == 0, or title is empty /
    "New chat"). This covers both the POST /sessions flow (metadata doc exists
    with title "New chat") and any flow where the doc was created lazily.

    Never raises — `update_session` may return None when no metadata doc exists
    (e.g. the legacy /api/chat flow). That's acceptable and non-fatal; we log
    and continue. The whole body is wrapped in try/except so save_turn keeps
    its never-raises contract.
    """
    try:
        existing_meta = await get_session(session_id)

        prior_count = 0
        meta_is_new = False
        if existing_meta is not None:
            prior_count = existing_meta.get("message_count") or 0
            current_title = (existing_meta.get("title") or "").strip()
            if prior_count == 0 or current_title in ("", _TITLE_FALLBACK):
                meta_is_new = True

        is_first_user_message = (not had_prior_messages) or meta_is_new

        # Monotonic count: never derived from the trimmed in-memory history.
        new_message_count = prior_count + messages_added

        updates: dict = {
            "message_count": new_message_count,
            "updated_at": now,
        }
        if is_first_user_message and user_message:
            updates["title"] = generate_title(user_message)

        result = await update_session(session_id, updates)
        if result is None:
            _log(
                f"session_metadata sync skipped — no metadata doc for "
                f"{session_id} (non-fatal)"
            )
    except Exception as e:
        _log(f"session_metadata sync failed for {session_id}: {e}")


# CONTRACT
# takes:  session_id (str) — session identifier, user_message (str) — the user's question, assistant_message (str) — the assistant's response, assistant_sql (str | None) — SQL generated for this turn, assistant_table (list[dict] | None) — query result snapshot for follow-ups
# returns: nothing
# raises:  nothing (never raises, failures are logged)
async def save_turn(
    session_id: str,
    user_message: str,
    assistant_message: str,
    assistant_sql: str | None = None,
    assistant_table: list[dict] | None = None,
) -> None:
    """
    Append a user+assistant turn to the session history. Trims to MAX_TURNS.
    If `assistant_sql` is provided, it's stored alongside the assistant turn
    so follow-up SQL generation can preserve the prior filter clauses.
    If `assistant_table` is provided, a compact snapshot (first rows) is stored
    so the next turn can answer follow-ups about the data WITHOUT re-querying.
    Never raises — failures are logged and the in-memory store is updated so
    the chat keeps working.
    """
    if not session_id:
        return

    existing = await get_history(session_id)
    # Capture whether the session had any prior messages BEFORE we append this
    # turn. Used to detect the first user message of a session so we can
    # generate a meaningful title from it.
    had_prior_messages = len(existing) > 0
    now = _now_iso()
    existing.append(
        {
            "message_id": _new_message_id(),
            "role": "user",
            "content": user_message,
            "timestamp": now,
        }
    )
    assistant_turn: dict = {
        "message_id": _new_message_id(),
        "role": "assistant",
        "content": assistant_message,
        "timestamp": _now_iso(),
    }
    if assistant_sql:
        assistant_turn["sql"] = assistant_sql
    if assistant_table:
        # Store a bounded snapshot so a follow-up can be answered from context
        # instead of re-running the query. Kept small to limit NoSQL doc size.
        assistant_turn["table"] = assistant_table[:_TABLE_SNAPSHOT_ROWS]
    existing.append(assistant_turn)
    # Number of messages persisted this turn: one user + one assistant. Used to
    # advance the monotonic message_count in session_metadata (independent of
    # the MAX_TURNS-trimmed in-memory history length).
    messages_added = 2
    trimmed = existing[-MAX_TURNS:]

    # Always update the in-memory fallback first; it's the source of truth
    # when NoSQL is misbehaving.
    await _local_set(session_id, trimmed)

    document = {"history": orjson.dumps(trimmed, default=str).decode()}

    # Run NoSQL save and metadata sync in a background task to prevent blocking the request path
    async def _bg_save():
        await _sync_session_metadata(
            session_id=session_id,
            user_message=user_message,
            had_prior_messages=had_prior_messages,
            messages_added=messages_added,
            now=now,
        )
        try:
            try:
                await update_document("conversation_history", session_id, document, timeout=_NOSQL_TIMEOUT, key_name="session_id")
            except NoSQLError as ne:
                # If document doesn't exist, we get a 404 error
                if "404" in str(ne):
                    await insert_document("conversation_history", session_id, document, timeout=_NOSQL_TIMEOUT, key_name="session_id")
                else:
                    raise
        except Exception as e:
            _log(f"ERROR: history save/update failed for {session_id}: {e}")

    if "pytest" in sys.modules:
        await _bg_save()
    else:
        asyncio.create_task(_bg_save())


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing (never raises, logs warning on failure)
async def init_nosql_table() -> None:
    """
    Probe Catalyst NoSQL once at startup. We don't try to create the table
    (the table must be defined in the Catalyst console) — just confirm the
    service is reachable so we can warn early if it isn't. Never raises.
    """
    try:
        # A probe — fetching a non-existent doc is enough to confirm auth + path work.
        # 404 is handled inside get_document and returns None safely.
        await get_document("conversation_history", "__probe__", timeout=_NOSQL_TIMEOUT, key_name="session_id")
    except Exception as e:
        _log(f"ERROR: NoSQL probe failed: {e}; history will use in-memory store.")
