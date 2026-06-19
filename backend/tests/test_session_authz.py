"""Authorization tests for session write paths (BOLA / IDOR — OWASP API1:2023).

These verify that an authenticated officer cannot write turns into a session
owned by a DIFFERENT officer by supplying its session_id, across all three
write endpoints:

  1. POST /api/reports/analyze   (routers.reports.analyze_report)
  2. POST /api/chat              (routers.chat.chat)
  3. GET  /api/chat/stream       (routers.chat.chat_stream)

The fix follows the pattern already used by the read paths: a foreign session
returns HTTP 404 (not 403) so we never reveal that another officer's session
exists. Create-or-append semantics are preserved: a not-yet-existing
session_id is allowed (the officer owns it on creation).

The DB and LLM boundaries are monkeypatched so no MySQL/NoSQL/LLM is needed.
Each test drives its async body with asyncio.run (no pytest-asyncio), matching
the rest of the suite.
"""

import asyncio

import pytest
from fastapi import HTTPException

import routers.chat as chat_mod
import routers.reports as reports_mod


OWNER_ID = 4001
INTRUDER_ID = 9999
SESSION_ID = "sess-owned-by-4001"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rows_for(owner_id):
    """Build the chat_sessions lookup result for a session owned by owner_id."""
    return [{"officer_id": owner_id}]


# --------------------------------------------------------------------------- #
# 1. Reports endpoint
# --------------------------------------------------------------------------- #


def test_reports_rejects_other_officers_session(monkeypatch):
    """An intruder targeting another officer's session_id gets 404 BEFORE any
    file decode or LLM call runs."""
    async def scenario():
        calls = {"decode": 0, "llm": 0}

        async def fake_execute(sql, params=()):
            # Session exists and is owned by OWNER_ID.
            return _rows_for(OWNER_ID)

        def fake_decode(_data):
            calls["decode"] += 1
            raise AssertionError("must not decode file for an unauthorized session")

        async def fake_llm(*a, **k):
            calls["llm"] += 1
            raise AssertionError("must not call the LLM for an unauthorized session")

        monkeypatch.setattr(reports_mod, "execute_query", fake_execute)
        monkeypatch.setattr(reports_mod, "_decode_file", fake_decode)
        monkeypatch.setattr(reports_mod, "call_llm", fake_llm)

        request = reports_mod.ReportAnalysisRequest(
            session_id=SESSION_ID,
            prompt="analyze",
            file_name="report.txt",
            mime_type="text/plain",
            data_base64="aGVsbG8=",  # "hello"
        )
        intruder = {"officer_id": INTRUDER_ID}

        with pytest.raises(HTTPException) as exc:
            await reports_mod.analyze_report(request, officer=intruder)

        assert exc.value.status_code == 404
        assert calls["decode"] == 0
        assert calls["llm"] == 0

    asyncio.run(scenario())


def test_reports_allows_owner_and_new_session(monkeypatch):
    """The real owner (existing session) and a brand-new session_id both pass
    the gate and proceed to extraction + analysis."""
    async def scenario(existing_owner):
        async def fake_execute(sql, params=()):
            return _rows_for(existing_owner) if existing_owner is not None else []

        def fake_decode(_data):
            return b"some report text"

        def fake_extract(raw, name, mime):
            return "Recurring theme: theft near Koramangala."

        async def fake_llm(*a, **k):
            return "Intelligence note: themes identified."

        saved = {"persist": 0, "history": 0}

        async def fake_save_turn(*a, **k):
            saved["history"] += 1

        async def fake_persist(session_id, officer, question, answer, session_exists):
            saved["persist"] += 1
            # New session => session_exists False; owner => True.
            assert session_exists == (existing_owner is not None)

        monkeypatch.setattr(reports_mod, "execute_query", fake_execute)
        monkeypatch.setattr(reports_mod, "_decode_file", fake_decode)
        monkeypatch.setattr(reports_mod, "extract_report_text", fake_extract)
        monkeypatch.setattr(reports_mod, "call_llm", fake_llm)
        monkeypatch.setattr(reports_mod, "get_history", lambda sid: _async_ret([]))
        monkeypatch.setattr(reports_mod, "save_turn", fake_save_turn)
        monkeypatch.setattr(reports_mod, "_persist_report_turn", fake_persist)

        request = reports_mod.ReportAnalysisRequest(
            session_id=SESSION_ID,
            prompt="analyze",
            file_name="report.txt",
            mime_type="text/plain",
            data_base64="aGVsbG8=",
        )
        officer = {"officer_id": OWNER_ID}

        resp = await reports_mod.analyze_report(request, officer=officer)
        assert resp.answer_text == "Intelligence note: themes identified."
        assert saved["persist"] == 1

    # Owner of an existing session.
    asyncio.run(scenario(existing_owner=OWNER_ID))
    # Brand-new session (no row yet).
    asyncio.run(scenario(existing_owner=None))


# --------------------------------------------------------------------------- #
# 2. POST /api/chat
# --------------------------------------------------------------------------- #


def test_chat_rejects_other_officers_session(monkeypatch):
    """POST /api/chat returns 404 and never runs the pipeline for a foreign
    session_id."""
    async def scenario():
        calls = {"pipeline": 0}

        async def fake_execute(sql, params=()):
            return _rows_for(OWNER_ID)

        async def fake_pipeline(*a, **k):
            calls["pipeline"] += 1
            raise AssertionError("pipeline must not run for an unauthorized session")

        monkeypatch.setattr(chat_mod, "execute_query", fake_execute)
        monkeypatch.setattr(chat_mod, "run_pipeline", fake_pipeline)

        request = chat_mod.ChatRequest(question="how many theft cases?", session_id=SESSION_ID)
        intruder = {"officer_id": INTRUDER_ID}

        with pytest.raises(HTTPException) as exc:
            await chat_mod.chat(request, officer=intruder)

        assert exc.value.status_code == 404
        assert calls["pipeline"] == 0

    asyncio.run(scenario())


def test_chat_allows_owner(monkeypatch):
    """The real owner passes the gate, runs the pipeline, and persists with the
    correct session_exists flag."""
    async def scenario():
        class _Result:
            answer_text = "There are 23 theft cases."
            table_data = []
            media_attachments = []
            sql_generated = "SELECT 1"
            graph_available = False
            error = None

        async def fake_execute(sql, params=()):
            return _rows_for(OWNER_ID)

        async def fake_pipeline(*a, **k):
            return _Result()

        persisted = {"session_exists": None}

        async def fake_persist(session_id, officer, question, result, session_exists):
            persisted["session_exists"] = session_exists

        monkeypatch.setattr(chat_mod, "execute_query", fake_execute)
        monkeypatch.setattr(chat_mod, "run_pipeline", fake_pipeline)
        monkeypatch.setattr(chat_mod, "get_history", lambda sid: _async_ret([]))
        monkeypatch.setattr(chat_mod, "save_turn", lambda *a, **k: _async_ret(None))
        monkeypatch.setattr(chat_mod, "_persist_turn", fake_persist)

        request = chat_mod.ChatRequest(question="how many theft cases?", session_id=SESSION_ID)
        owner = {"officer_id": OWNER_ID}

        resp = await chat_mod.chat(request, officer=owner)
        assert resp.error is None
        assert resp.answer_text == "There are 23 theft cases."
        # Existing session owned by this officer => session_exists True.
        assert persisted["session_exists"] is True

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 3. GET /api/chat/stream
# --------------------------------------------------------------------------- #


def test_chat_stream_rejects_other_officers_session(monkeypatch):
    """The SSE endpoint raises HTTP 404 before opening the stream for a foreign
    session_id (clean rejection, not an in-stream error event)."""
    async def scenario():
        async def fake_execute(sql, params=()):
            return _rows_for(OWNER_ID)

        monkeypatch.setattr(chat_mod, "execute_query", fake_execute)

        intruder = {"officer_id": INTRUDER_ID}
        with pytest.raises(HTTPException) as exc:
            await chat_mod.chat_stream(
                question="how many theft cases?",
                session_id=SESSION_ID,
                officer=intruder,
            )
        assert exc.value.status_code == 404

    asyncio.run(scenario())


def test_chat_stream_allows_new_session(monkeypatch):
    """A brand-new session_id is allowed (returns a StreamingResponse), since
    create-or-append semantics let the officer own it on first write."""
    async def scenario():
        async def fake_execute(sql, params=()):
            return []  # session does not exist yet

        monkeypatch.setattr(chat_mod, "execute_query", fake_execute)

        owner = {"officer_id": OWNER_ID}
        resp = await chat_mod.chat_stream(
            question="how many theft cases?",
            session_id="sess-brand-new",
            officer=owner,
        )
        # No exception => gate passed; we get a streaming response object back.
        assert resp.media_type == "text/event-stream"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# tiny async helper
# --------------------------------------------------------------------------- #


def _async_ret(value):
    async def _coro():
        return value
    return _coro()
