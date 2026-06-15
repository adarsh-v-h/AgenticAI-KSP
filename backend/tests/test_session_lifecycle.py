"""End-to-end session lifecycle tests (Task 14.1).

These integration-style tests exercise the complete user flows described in the
chat-history-sidebar spec through the real `conversation.session_store`,
`conversation.history`, and `routers.chat` modules — using their in-memory
fallback path so no NoSQL service is required.

To keep the tests fast and deterministic we monkeypatch `httpx.AsyncClient` so
every NoSQL HTTP call raises immediately, forcing each helper down its
"never raises → fall back to in-memory store" branch. This mirrors production
behaviour when NoSQL is unreachable and lets us verify the full lifecycle:

  1. Create session            (session_store.create_session / get_session / list_sessions)
  2. Send messages             (history.save_turn → get_history + metadata sync)
  3. Switch between sessions    (list_sessions ordering by updated_at DESC)
  4. Pagination correctness     (routers.chat.get_session_messages newest-first + has_more)
  5. Persistence across login   (fresh reads still return previously saved data)

pytest-asyncio is intentionally NOT required: each test wraps its async body in
`asyncio.run(...)`, which is dependency-free.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from conversation import history as history_mod
from conversation import session_store as store_mod
from routers.chat import get_session_messages


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


class _FailingAsyncClient:
    """Stand-in for httpx.AsyncClient that fails fast on entry.

    The application code uses `async with httpx.AsyncClient() as client:`. By
    raising inside `__aenter__` we trigger the modules' `except Exception`
    fallback to the in-memory store without any real network I/O or timeout.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        raise RuntimeError("NoSQL disabled in tests — forcing in-memory fallback")

    async def __aexit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def force_in_memory(monkeypatch):
    """Force every NoSQL call to fail fast and clear the in-memory stores.

    `monkeypatch` works fine with plain (sync) test functions, and patching the
    shared `httpx.AsyncClient` covers both `history` and `session_store` since
    they import the same `httpx` module.
    """
    monkeypatch.setattr(httpx, "AsyncClient", _FailingAsyncClient)
    # Start each test from a clean slate so global in-memory dicts don't bleed
    # across tests.
    store_mod._local_sessions.clear()
    history_mod._local_history.clear()
    yield
    store_mod._local_sessions.clear()
    history_mod._local_history.clear()


def _new_session_doc(session_id: str, officer_id: int, created_at: str) -> dict:
    """Build a full session_metadata document matching the real schema."""
    return {
        "id": session_id,
        "officer_id": officer_id,
        "title": store_mod._TITLE_FALLBACK,  # "New chat"
        "created_at": created_at,
        "updated_at": created_at,
        "message_count": 0,
    }


def _iso(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# 1. Create session
# --------------------------------------------------------------------------- #


def test_create_session_is_retrievable_and_listed():
    async def scenario():
        officer_id = 1001
        session_id = "sess-create-1"
        created_at = _iso(2024, 1, 15, 10, 30, 0)
        doc = _new_session_doc(session_id, officer_id, created_at)

        stored = await store_mod.create_session(doc)
        assert stored["id"] == session_id

        # get_session returns the stored document.
        fetched = await store_mod.get_session(session_id)
        assert fetched is not None
        assert fetched["id"] == session_id
        assert fetched["officer_id"] == officer_id
        assert fetched["title"] == store_mod._TITLE_FALLBACK
        assert fetched["message_count"] == 0

        # list_sessions for that officer includes it.
        sessions = await store_mod.list_sessions(officer_id)
        ids = [s["id"] for s in sessions]
        assert session_id in ids

        # Another officer does NOT see this session (officer isolation).
        other = await store_mod.list_sessions(9999)
        assert session_id not in [s["id"] for s in other]

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 2. Send messages
# --------------------------------------------------------------------------- #


def test_send_messages_updates_history_and_metadata():
    async def scenario():
        officer_id = 1002
        session_id = "sess-messages-1"
        created_at = _iso(2024, 1, 1, 0, 0, 0)
        await store_mod.create_session(
            _new_session_doc(session_id, officer_id, created_at)
        )

        turns = [
            ("How many theft cases are open in Koramangala?", "There are 23 open theft cases."),
            ("Show me the oldest one", "The oldest is FIR-001 from 2022."),
            ("Who is the investigating officer?", "Inspector Mahesh Gowda."),
        ]
        for user_msg, assistant_msg in turns:
            await history_mod.save_turn(session_id, user_msg, assistant_msg)

        # History returns turns in chronological order with message_id + timestamp.
        hist = await history_mod.get_history(session_id)
        assert len(hist) == len(turns) * 2  # user+assistant per turn, < MAX_TURNS
        for msg in hist:
            assert msg.get("message_id"), "every message must carry a message_id"
            assert msg.get("timestamp"), "every message must carry a timestamp"
            assert msg["role"] in ("user", "assistant")

        # Roles alternate user, assistant, user, assistant, ...
        expected_roles = ["user", "assistant"] * len(turns)
        assert [m["role"] for m in hist] == expected_roles

        # Chronological order: timestamps are non-decreasing.
        timestamps = [m["timestamp"] for m in hist]
        assert timestamps == sorted(timestamps)

        # message_ids are unique within the session.
        ids = [m["message_id"] for m in hist]
        assert len(ids) == len(set(ids))

        # Metadata: message_count advanced monotonically (2 per turn) and
        # updated_at moved past created_at.
        meta = await store_mod.get_session(session_id)
        assert meta["message_count"] == len(turns) * 2
        assert meta["updated_at"] > created_at

        # Title generated from the first user message (no longer "New chat").
        assert meta["title"] != store_mod._TITLE_FALLBACK
        assert meta["title"] == store_mod.generate_title(turns[0][0])

    asyncio.run(scenario())


def test_message_count_advances_monotonically_per_turn():
    async def scenario():
        officer_id = 1003
        session_id = "sess-monotonic-1"
        created_at = _iso(2024, 2, 1, 0, 0, 0)
        await store_mod.create_session(
            _new_session_doc(session_id, officer_id, created_at)
        )

        counts = []
        for i in range(4):
            await history_mod.save_turn(session_id, f"question {i}", f"answer {i}")
            meta = await store_mod.get_session(session_id)
            counts.append(meta["message_count"])

        # Each turn adds exactly two messages, strictly increasing.
        assert counts == [2, 4, 6, 8]
        assert all(b > a for a, b in zip(counts, counts[1:]))

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 3. Switch sessions
# --------------------------------------------------------------------------- #


def test_list_sessions_orders_by_updated_at_desc():
    async def scenario():
        officer_id = 1004
        first_id = "sess-switch-a"
        second_id = "sess-switch-b"

        await store_mod.create_session(
            _new_session_doc(first_id, officer_id, _iso(2024, 3, 1, 8, 0, 0))
        )
        await history_mod.save_turn(first_id, "first session question", "first answer")

        # Tiny delay so the second session's updated_at is strictly later than
        # the first session's, making ordering deterministic.
        await asyncio.sleep(0.01)

        await store_mod.create_session(
            _new_session_doc(second_id, officer_id, _iso(2024, 3, 2, 8, 0, 0))
        )
        await history_mod.save_turn(second_id, "second session question", "second answer")

        sessions = await store_mod.list_sessions(officer_id)
        ids = [s["id"] for s in sessions]

        # Both sessions present.
        assert first_id in ids
        assert second_id in ids

        # Ordered by updated_at DESC (most recently updated first).
        updated_values = [s["updated_at"] for s in sessions]
        assert updated_values == sorted(updated_values, reverse=True)
        # The most recently touched session (second) appears before the first.
        assert ids.index(second_id) < ids.index(first_id)

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 4. Pagination correctness (via routers.chat.get_session_messages)
# --------------------------------------------------------------------------- #


def test_get_history_capped_at_max_turns_and_chronological():
    async def scenario():
        officer_id = 1005
        session_id = "sess-cap-1"
        await store_mod.create_session(
            _new_session_doc(session_id, officer_id, _iso(2024, 4, 1, 0, 0, 0))
        )

        # Save more turns than MAX_TURNS can hold (10 messages).
        for i in range(8):  # 16 messages, capped to last 10
            await history_mod.save_turn(session_id, f"q{i}", f"a{i}")

        hist = await history_mod.get_history(session_id)
        assert len(hist) == history_mod.MAX_TURNS
        timestamps = [m["timestamp"] for m in hist]
        assert timestamps == sorted(timestamps)  # chronological

    asyncio.run(scenario())


def test_messages_endpoint_newest_first_and_has_more():
    async def scenario():
        officer_id = 1006
        session_id = "sess-page-1"
        await store_mod.create_session(
            _new_session_doc(session_id, officer_id, _iso(2024, 5, 1, 0, 0, 0))
        )

        for i in range(5):  # 10 messages = MAX_TURNS exactly
            await history_mod.save_turn(session_id, f"question {i}", f"answer {i}")

        officer = {"officer_id": officer_id}

        # Full page (limit covers everything): newest-first, no more pages.
        resp = await get_session_messages(
            session_id, limit=50, before_message_id=None, officer=officer
        )
        assert resp.has_more is False
        assert len(resp.messages) == history_mod.MAX_TURNS
        ts_desc = [m.timestamp for m in resp.messages]
        assert ts_desc == sorted(ts_desc, reverse=True), "messages must be newest-first"

        # Small page → older messages remain → has_more True.
        small = await get_session_messages(
            session_id, limit=4, before_message_id=None, officer=officer
        )
        assert len(small.messages) == 4
        assert small.has_more is True
        # The small page contains the 4 newest messages.
        assert small.messages[0].timestamp == ts_desc[0]

        # Pagination with before_message_id: ask for messages older than the
        # oldest currently-loaded message → returns the strictly older slice.
        full_chrono = await history_mod.get_history(session_id)
        cursor_id = full_chrono[3]["message_id"]  # 4th message chronologically
        older = await get_session_messages(
            session_id, limit=50, before_message_id=cursor_id, officer=officer
        )
        # Everything strictly older than index 3 → 3 messages, newest-first.
        assert len(older.messages) == 3
        older_ts = [m.timestamp for m in older.messages]
        assert older_ts == sorted(older_ts, reverse=True)
        assert older.has_more is False

        # Unknown cursor → nothing older.
        none_page = await get_session_messages(
            session_id, limit=50, before_message_id="m-does-not-exist", officer=officer
        )
        assert none_page.messages == []
        assert none_page.has_more is False

    asyncio.run(scenario())


def test_messages_endpoint_rejects_other_officers_session():
    async def scenario():
        owner_id = 1007
        session_id = "sess-owned-1"
        await store_mod.create_session(
            _new_session_doc(session_id, owner_id, _iso(2024, 6, 1, 0, 0, 0))
        )
        await history_mod.save_turn(session_id, "private question", "private answer")

        intruder = {"officer_id": 7777}
        # Ownership check returns a 404 HTTPException (never reveals existence).
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_session_messages(
                session_id, limit=50, before_message_id=None, officer=intruder
            )
        assert exc.value.status_code == 404

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 5. Persistence across "login" (re-fetch returns previously saved data)
# --------------------------------------------------------------------------- #


def test_session_data_persists_across_fresh_reads():
    async def scenario():
        officer_id = 1008
        session_id = "sess-persist-1"
        await store_mod.create_session(
            _new_session_doc(session_id, officer_id, _iso(2024, 7, 1, 0, 0, 0))
        )
        await history_mod.save_turn(session_id, "remember this question", "remembered answer")

        # Simulate logout/login by issuing brand new read calls. The in-memory
        # store persists for the process lifetime, mirroring how a re-login
        # would re-fetch the officer's sessions and history from storage.
        relisted = await store_mod.list_sessions(officer_id)
        assert session_id in [s["id"] for s in relisted]

        rehistory = await history_mod.get_history(session_id)
        assert len(rehistory) == 2
        assert rehistory[0]["content"] == "remember this question"
        assert rehistory[1]["content"] == "remembered answer"

        # Metadata survives the "re-login" too.
        meta = await store_mod.get_session(session_id)
        assert meta is not None
        assert meta["message_count"] == 2
        assert meta["title"] == store_mod.generate_title("remember this question")

    asyncio.run(scenario())
