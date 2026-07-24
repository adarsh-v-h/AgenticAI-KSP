"""
Property-based tests for the chat-history-sidebar feature — session layer.

Covers:
  - Property 6:  Session Metadata Schema Completeness (Task 1.3)
  - Property 19: Message ID Uniqueness Within Session (Task 1.4)
  - Property 1:  Session ID Uniqueness (Task 2.4)
  - Property 7:  Officer Association (Task 2.5)

Run:  pytest backend/tests/properties/session_property_test.py -v
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies (shared generators)
# ---------------------------------------------------------------------------

officer_ids = st.integers(min_value=1, max_value=999_999)

titles = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), max_codepoint=127),
    min_size=1,
    max_size=60,
)

message_texts = st.text(min_size=1, max_size=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"id", "officer_id", "created_at", "updated_at", "title", "message_count"}


def _make_session_document(officer_id: int, title: str = "New chat") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "officer_id": officer_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }


async def _cleanup_local(session_id: str):
    from conversation.session_store import _local_sessions, _local_lock
    async with _local_lock:
        _local_sessions.pop(session_id, None)


async def _cleanup_history(session_id: str):
    from conversation.history import _local_clear
    from conversation.session_store import _local_sessions, _local_lock
    await _local_clear(session_id)
    async with _local_lock:
        _local_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Fixture: mock all NoSQL I/O so tests use in-memory stores only
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
# Property 6: Session Metadata Schema Completeness
# Validates: Requirements 5.4, 9.2
# ---------------------------------------------------------------------------


class TestSessionMetadataSchemaCompleteness:
    """Property 6 — all sessions include required metadata fields."""

    @given(officer_id=officer_ids, title=titles)
    def test_created_session_has_all_required_fields(self, officer_id, title):
        from conversation.session_store import create_session

        doc = _make_session_document(officer_id, title)
        stored = asyncio.run(create_session(doc))

        missing = _REQUIRED_FIELDS - set(stored.keys())
        assert not missing, f"Missing fields: {missing}"
        assert isinstance(stored["id"], str) and len(stored["id"]) > 0
        assert isinstance(stored["officer_id"], int)
        assert isinstance(stored["title"], str)
        assert isinstance(stored["created_at"], str)
        assert isinstance(stored["updated_at"], str)
        assert isinstance(stored["message_count"], int)

        asyncio.run(_cleanup_local(stored["id"]))


# ---------------------------------------------------------------------------
# Property 19: Message ID Uniqueness Within Session
# Validates: Requirements 12.2
# ---------------------------------------------------------------------------


class TestMessageIdUniqueness:
    """Property 19 — message_ids within a session are always unique."""

    @given(
        num_turns=st.integers(min_value=1, max_value=5),
        user_msgs=st.lists(message_texts, min_size=5, max_size=5),
    )
    def test_message_ids_unique_after_multiple_turns(self, num_turns, user_msgs):
        from conversation.history import save_turn, get_history

        session_id = f"prop19-{uuid.uuid4()}"

        async def scenario():
            for i in range(num_turns):
                await save_turn(session_id, user_msgs[i], f"Reply {i}")
            history = await get_history(session_id)
            await _cleanup_history(session_id)
            return history

        history = asyncio.run(scenario())

        ids = [msg["message_id"] for msg in history]
        assert len(ids) == len(set(ids)), f"Duplicate message_ids: {ids}"
        for msg in history:
            assert msg.get("message_id"), "message_id is empty or missing"


# ---------------------------------------------------------------------------
# Property 1: Session ID Uniqueness
# Validates: Requirements 2.2, 11.2
# ---------------------------------------------------------------------------


class TestSessionIdUniqueness:
    """Property 1 — session_ids are globally unique across creations."""

    @given(officer_ids_list=st.lists(officer_ids, min_size=2, max_size=5))
    def test_all_session_ids_unique(self, officer_ids_list):
        from conversation.session_store import create_session

        async def scenario():
            created = []
            for oid in officer_ids_list:
                doc = _make_session_document(oid)
                stored = await create_session(doc)
                created.append(stored["id"])
            for sid in created:
                await _cleanup_local(sid)
            return created

        ids = asyncio.run(scenario())
        assert len(ids) == len(set(ids)), "Duplicate session_ids generated"


# ---------------------------------------------------------------------------
# Property 7: Officer Association
# Validates: Requirements 5.5, 11.3
# ---------------------------------------------------------------------------


class TestOfficerAssociation:
    """Property 7 — sessions correctly associated with their officer."""

    @given(officer_id=officer_ids, title=titles)
    def test_session_retains_officer_id(self, officer_id, title):
        from conversation.session_store import create_session, get_session

        doc = _make_session_document(officer_id, title)

        async def scenario():
            stored = await create_session(doc)
            fetched = await get_session(stored["id"])
            await _cleanup_local(stored["id"])
            return stored, fetched

        stored, fetched = asyncio.run(scenario())

        assert stored["officer_id"] == officer_id
        assert fetched is not None
        assert fetched["officer_id"] == officer_id

    @given(officers=st.lists(officer_ids, min_size=2, max_size=5, unique=True))
    def test_list_sessions_filters_by_officer(self, officers):
        from conversation.session_store import create_session, list_sessions

        async def scenario():
            created_ids = []
            for oid in officers:
                doc = _make_session_document(oid)
                stored = await create_session(doc)
                created_ids.append(stored["id"])

            target = officers[0]
            results = await list_sessions(target)

            for sid in created_ids:
                await _cleanup_local(sid)
            return target, results

        target, results = asyncio.run(scenario())

        for sess in results:
            assert sess["officer_id"] == target, (
                f"list_sessions returned officer {sess['officer_id']} for query {target}"
            )
