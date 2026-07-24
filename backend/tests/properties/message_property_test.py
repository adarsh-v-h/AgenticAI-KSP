"""
Property-based tests for message storage and retrieval.

Covers:
  - Property 5:  Message List Ordering (Task 13.3 — Req 10.6)
  - Property 20: Message Timestamp Presence (Task 13.3 — Req 12.3)
  - Property 21: Session Metadata Timestamp Initialization (Task 13.3 — Req 11.4)

Run:  pytest backend/tests/properties/message_property_test.py -v
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

officer_ids = st.integers(min_value=1, max_value=999_999)
message_texts = st.text(min_size=1, max_size=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_document(officer_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "officer_id": officer_id,
        "title": "New chat",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }


async def _cleanup(session_id: str):
    from conversation.history import _local_clear
    from conversation.session_store import _local_sessions, _local_lock
    await _local_clear(session_id)
    async with _local_lock:
        _local_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Fixture: mock all NoSQL I/O
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_nosql():
    """Patch all NoSQL and Cache network calls to no-op AsyncMocks."""
    patches = [
        patch("conversation.session_store.insert_document", AsyncMock(return_value=True)),
        patch("conversation.session_store.update_document", AsyncMock(return_value=True)),
        patch("conversation.session_store.list_documents", AsyncMock(return_value=[])),
        patch("conversation.session_store.get_document", AsyncMock(return_value=None)),
        patch("conversation.history.get_document", AsyncMock(return_value=None)),
        patch("conversation.history.update_document", AsyncMock(return_value=True)),
        patch("conversation.history.insert_document", AsyncMock(return_value=True)),
        patch("db.cache_client.get_value", AsyncMock(return_value=None)),
        patch("db.cache_client.put_value", AsyncMock(return_value=True)),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Property 5: Message List Ordering
# Validates: Requirements 10.6
# ---------------------------------------------------------------------------


class TestMessageListOrdering:
    """Property 5 — messages are returned in chronological order."""

    @given(
        num_turns=st.integers(min_value=1, max_value=5),
        user_msgs=st.lists(message_texts, min_size=5, max_size=5),
    )
    def test_messages_sorted_by_timestamp(self, num_turns, user_msgs):
        from conversation.history import save_turn, get_history

        session_id = f"prop5-{uuid.uuid4()}"

        async def scenario():
            for i in range(num_turns):
                await save_turn(session_id, user_msgs[i], f"Reply {i}")
            history = await get_history(session_id)
            await _cleanup(session_id)
            return history

        history = asyncio.run(scenario())

        timestamps = [msg["timestamp"] for msg in history]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"Out of order at {i}: {timestamps[i - 1]} > {timestamps[i]}"
            )


# ---------------------------------------------------------------------------
# Property 20: Message Timestamp Presence
# Validates: Requirements 12.3
# ---------------------------------------------------------------------------


class TestMessageTimestampPresence:
    """Property 20 — every message has a timestamp field."""

    @given(user_msg=message_texts, assistant_msg=message_texts)
    def test_all_messages_have_timestamp(self, user_msg, assistant_msg):
        from conversation.history import save_turn, get_history

        session_id = f"prop20-{uuid.uuid4()}"

        async def scenario():
            await save_turn(session_id, user_msg, assistant_msg)
            history = await get_history(session_id)
            await _cleanup(session_id)
            return history

        history = asyncio.run(scenario())

        for msg in history:
            assert "timestamp" in msg, f"Missing timestamp: {msg}"
            assert msg["timestamp"], f"Empty timestamp: {msg}"
            ts = msg["timestamp"]
            try:
                datetime.fromisoformat(ts)
            except ValueError:
                raise AssertionError(f"Invalid timestamp format: '{ts}'")


# ---------------------------------------------------------------------------
# Property 21: Session Metadata Timestamp Initialization
# Validates: Requirements 11.4
# ---------------------------------------------------------------------------


class TestSessionMetadataTimestampInitialization:
    """Property 21 — new sessions have valid timestamp fields."""

    @given(officer_id=officer_ids)
    def test_new_session_has_valid_timestamps(self, officer_id):
        from conversation.session_store import create_session, _local_sessions, _local_lock

        doc = _make_session_document(officer_id)

        async def scenario():
            stored = await create_session(doc)
            async with _local_lock:
                _local_sessions.pop(stored["id"], None)
            return stored

        stored = asyncio.run(scenario())

        for field in ("created_at", "updated_at"):
            assert field in stored, f"Missing {field}"
            val = stored[field]
            assert val, f"Empty {field}"
            try:
                parsed = datetime.fromisoformat(val)
            except ValueError:
                raise AssertionError(f"Invalid {field} format: '{val}'")
            assert parsed.year >= 2020, f"Suspiciously old {field}: {val}"

    @given(officer_id=officer_ids)
    def test_created_at_equals_updated_at_at_creation(self, officer_id):
        from conversation.session_store import create_session, _local_sessions, _local_lock

        doc = _make_session_document(officer_id)

        async def scenario():
            stored = await create_session(doc)
            async with _local_lock:
                _local_sessions.pop(stored["id"], None)
            return stored

        stored = asyncio.run(scenario())

        assert stored["created_at"] == stored["updated_at"], (
            f"created_at={stored['created_at']}, updated_at={stored['updated_at']}"
        )
