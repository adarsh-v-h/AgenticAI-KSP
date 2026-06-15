"""Backward-compatibility tests for conversation history (Requirement 12.5).

These tests verify that the lazy-migration path in ``conversation.history``
keeps working for sessions created before the enhanced message schema
(``message_id`` / ``timestamp``) existed:

  * Legacy messages stored as plain ``{role, content}`` dicts are migrated on
    read so every message gains a non-empty ``message_id`` and ``timestamp``
    while the original ``role`` / ``content`` are preserved.
  * Migrated ``message_id`` values are unique across the set.
  * Messages that already carry ``message_id`` / ``timestamp`` are left
    untouched by migration (idempotent).
  * The in-memory fallback path of ``get_history`` returns the stored messages
    when NoSQL is unavailable.

The migration unit (``_migrate_messages``) is synchronous and is exercised
directly. ``get_history`` is async; since the suite does not depend on
``pytest-asyncio`` we drive the coroutine with ``asyncio.run`` and force the
in-memory fallback by making the httpx client raise.
"""

import asyncio

from conversation import history


# --------------------------------------------------------------------------- #
# _migrate_messages — lazy migration of legacy messages
# --------------------------------------------------------------------------- #


def test_legacy_messages_gain_id_and_timestamp():
    """Plain {role, content} dicts get non-empty message_id + timestamp,
    and the original role/content are preserved (Requirement 12.5)."""
    legacy = [
        {"role": "user", "content": "How many theft cases are open?"},
        {"role": "assistant", "content": "There are 23 open theft cases."},
    ]

    migrated = history._migrate_messages(legacy)

    assert len(migrated) == len(legacy)
    for original, msg in zip(legacy, migrated):
        assert msg.get("message_id"), "migrated message must have a non-empty message_id"
        assert msg.get("timestamp"), "migrated message must have a non-empty timestamp"
        # Original fields preserved verbatim.
        assert msg["role"] == original["role"]
        assert msg["content"] == original["content"]


def test_migrated_message_ids_are_unique():
    """All message_id values assigned during migration are unique
    (Requirement 12.2 / 12.5)."""
    legacy = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"}
        for i in range(20)
    ]

    migrated = history._migrate_messages(legacy)
    ids = [m["message_id"] for m in migrated]

    assert all(ids), "no message_id should be empty"
    assert len(set(ids)) == len(ids), "migrated message_ids must be unique"


def test_already_enhanced_messages_left_unchanged():
    """Messages that already carry message_id and timestamp are not modified
    by migration (idempotent for the enhanced schema)."""
    enhanced = [
        {
            "message_id": "m-existing-1",
            "role": "user",
            "content": "hi",
            "timestamp": "2024-01-15T10:35:00+00:00",
        },
        {
            "message_id": "m-existing-2",
            "role": "assistant",
            "content": "hello",
            "timestamp": "2024-01-15T10:35:15+00:00",
            "sql": "SELECT 1",
        },
    ]

    migrated = history._migrate_messages(enhanced)

    assert migrated[0]["message_id"] == "m-existing-1"
    assert migrated[0]["timestamp"] == "2024-01-15T10:35:00+00:00"
    assert migrated[1]["message_id"] == "m-existing-2"
    assert migrated[1]["timestamp"] == "2024-01-15T10:35:15+00:00"
    # Non-schema fields (e.g. sql) are preserved.
    assert migrated[1]["sql"] == "SELECT 1"


def test_mixed_legacy_and_enhanced_messages():
    """A mix of legacy and enhanced messages: legacy ones are migrated while
    enhanced ones are preserved, and all ids end up unique and non-empty."""
    mixed = [
        {"role": "user", "content": "legacy question"},  # legacy
        {
            "message_id": "m-keep",
            "role": "assistant",
            "content": "enhanced answer",
            "timestamp": "2024-01-15T10:35:15+00:00",
        },  # enhanced
    ]

    migrated = history._migrate_messages(mixed)

    # Enhanced message keeps its id/timestamp.
    assert migrated[1]["message_id"] == "m-keep"
    assert migrated[1]["timestamp"] == "2024-01-15T10:35:15+00:00"
    # Legacy message gained an id/timestamp.
    assert migrated[0]["message_id"]
    assert migrated[0]["timestamp"]
    # All ids non-empty and unique.
    ids = [m["message_id"] for m in migrated]
    assert all(ids)
    assert len(set(ids)) == len(ids)


def test_migration_does_not_mutate_input():
    """Migration returns fresh dicts and never mutates the caller's list."""
    legacy = [{"role": "user", "content": "no id here"}]

    history._migrate_messages(legacy)

    # Original dict is untouched — no message_id/timestamp leaked back in.
    assert "message_id" not in legacy[0]
    assert "timestamp" not in legacy[0]


def test_migration_is_deterministic():
    """Repeated migration of the same legacy input yields identical ids,
    so repeated reads of a stored document are stable."""
    legacy = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]

    first = history._migrate_messages(legacy)
    second = history._migrate_messages(legacy)

    assert [m["message_id"] for m in first] == [m["message_id"] for m in second]
    assert [m["timestamp"] for m in first] == [m["timestamp"] for m in second]


def test_migration_skips_non_dict_entries():
    """Defensive: malformed (non-dict) entries are dropped rather than crashing."""
    turns = [
        {"role": "user", "content": "ok"},
        "not-a-dict",
        None,
    ]

    migrated = history._migrate_messages(turns)

    assert len(migrated) == 1
    assert migrated[0]["content"] == "ok"
    assert migrated[0]["message_id"]


# --------------------------------------------------------------------------- #
# get_history — in-memory fallback path (NoSQL unavailable)
# --------------------------------------------------------------------------- #


class _RaisingAsyncClient:
    """Stand-in for httpx.AsyncClient whose context entry raises, forcing
    get_history down its in-memory fallback branch deterministically (no
    network access)."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        raise RuntimeError("NoSQL unavailable (simulated)")

    async def __aexit__(self, *exc):
        return False


def test_get_history_returns_stored_messages_from_memory(monkeypatch):
    """When NoSQL is unreachable, get_history returns the messages stored in
    the in-memory fallback (Requirement 12.5 — existing sessions keep working)."""
    monkeypatch.setattr(history.httpx, "AsyncClient", _RaisingAsyncClient)

    session_id = "sess-backward-compat"
    stored = [
        {
            "message_id": "m-1",
            "role": "user",
            "content": "stored question",
            "timestamp": "2024-01-15T10:35:00+00:00",
        },
        {
            "message_id": "m-2",
            "role": "assistant",
            "content": "stored answer",
            "timestamp": "2024-01-15T10:35:15+00:00",
        },
    ]

    async def scenario():
        await history._local_set(session_id, stored)
        return await history.get_history(session_id)

    result = asyncio.run(scenario())

    assert result == stored

    # Cleanup so the in-memory store doesn't leak into other tests.
    asyncio.run(history._local_clear(session_id))


def test_get_history_empty_session_returns_empty_list(monkeypatch):
    """An unknown session falls back to the (empty) in-memory store and
    returns [] rather than raising."""
    monkeypatch.setattr(history.httpx, "AsyncClient", _RaisingAsyncClient)

    result = asyncio.run(history.get_history("sess-does-not-exist"))

    assert result == []
