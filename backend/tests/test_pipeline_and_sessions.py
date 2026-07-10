"""
Consolidated pipeline, routing, authorization, and session lifecycle tests.

Merges the former:
  - test_intent_routing.py
  - test_session_authz.py
  - test_session_lifecycle.py

Run: pytest backend/tests/test_pipeline_and_sessions.py -v
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Intent Routing (query pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

import pipeline.query_pipeline as qp


class TestIntentRouting:
    def test_most_recent_table_returns_latest_snapshot(self):
        history = [
            {"role": "user", "content": "theft cases"},
            {"role": "assistant", "content": "Found 3.", "table": [{"fir_id": 1}]},
            {"role": "user", "content": "robbery cases"},
            {"role": "assistant", "content": "Found 2.", "table": [{"fir_id": 9}]},
        ]
        assert qp._most_recent_table(history) == [{"fir_id": 9}]

    def test_most_recent_table_empty_when_no_snapshot(self):
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        assert qp._most_recent_table(history) == []

    def test_direct_route_skips_sql(self, monkeypatch):
        async def scenario():
            calls = {"sql": 0}

            async def fake_route(question, history, has_recent_data): return "DIRECT"
            async def fake_direct(question, history, recent_table): return "Summary."
            async def fake_generate_sql(*a, **k):
                calls["sql"] += 1
                raise AssertionError("SQL must not run")

            monkeypatch.setattr(qp, "route_intent", fake_route)
            monkeypatch.setattr(qp, "generate_direct_answer", fake_direct)
            monkeypatch.setattr(qp, "generate_sql", fake_generate_sql)

            history = [{"role": "user", "content": "theft"}, {"role": "assistant", "content": "3.", "table": [{"fir_id": 1}]}]
            resp = await qp.run_pipeline("summarize that", history=history)
            assert resp.sql_generated == ""
            assert calls["sql"] == 0

        asyncio.run(scenario())

    def test_sql_route_runs_pipeline(self, monkeypatch):
        async def scenario():
            async def fake_route(q, h, has_recent_data): return "SQL"
            async def fake_gen(**kwargs): return "SELECT 1 AS fir_id", 1
            async def fake_exec(sql, params=()): return [{"fir_id": 1}]
            async def fake_fmt(**kwargs): return "One case."
            async def fake_graph(ids): return False
            async def fake_resolve(results): return []

            monkeypatch.setattr(qp, "route_intent", fake_route)
            monkeypatch.setattr(qp, "generate_sql", fake_gen)
            monkeypatch.setattr(qp, "execute_query", fake_exec)
            monkeypatch.setattr(qp, "format_answer", fake_fmt)
            monkeypatch.setattr(qp, "_check_graph_available", fake_graph)
            monkeypatch.setattr(qp, "resolve_media", fake_resolve)
            monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

            resp = await qp.run_pipeline("show theft cases", history=[])
            assert resp.sql_generated == "SELECT 1 AS fir_id"
            assert resp.table_data == [{"fir_id": 1}]

        asyncio.run(scenario())

    def test_cannot_answer_falls_back_to_direct(self, monkeypatch):
        async def scenario():
            async def fake_route(q, h, has_recent_data): return "SQL"
            async def fake_gen(*a, **k): raise qp.CannotAnswerError("nope")
            async def fake_direct(**kwargs): return "Can't pull that from DB."

            monkeypatch.setattr(qp, "route_intent", fake_route)
            monkeypatch.setattr(qp, "generate_sql", fake_gen)
            monkeypatch.setattr(qp, "generate_direct_answer", fake_direct)
            monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

            resp = await qp.run_pipeline("what is your name?", history=[])
            assert "Can't pull" in resp.answer_text

        asyncio.run(scenario())

    def test_empty_history_skips_router(self, monkeypatch):
        async def scenario():
            calls = {"router": 0}
            async def fake_route(q, h, has_recent_data):
                calls["router"] += 1
                return "SQL"
            async def fake_gen(**kwargs): return "SELECT 1", 1
            async def fake_exec(sql, params=()): return [{"fir_id": 1}]
            async def fake_fmt(**kwargs): return "Done."
            async def fake_graph(ids): return False
            async def fake_resolve(r): return []

            monkeypatch.setattr(qp, "route_intent", fake_route)
            monkeypatch.setattr(qp, "generate_sql", fake_gen)
            monkeypatch.setattr(qp, "execute_query", fake_exec)
            monkeypatch.setattr(qp, "format_answer", fake_fmt)
            monkeypatch.setattr(qp, "_check_graph_available", fake_graph)
            monkeypatch.setattr(qp, "resolve_media", fake_resolve)
            monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

            await qp.run_pipeline("show theft cases", history=[])
            assert calls["router"] == 0

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Session Authorization (BOLA / IDOR)
# ═══════════════════════════════════════════════════════════════════════════════

import routers.chat as chat_mod
import routers.reports as reports_mod
from fastapi import HTTPException

OWNER_ID = 4001
INTRUDER_ID = 9999
SESSION_ID = "sess-owned-by-4001"


def _rows_for(owner_id):
    return [{"officer_id": owner_id}]


def _async_ret(value):
    async def _coro(): return value
    return _coro()


class TestSessionAuthz:
    def test_reports_rejects_intruder(self, monkeypatch):
        async def scenario():
            async def fake_exec(sql, params=()): return _rows_for(OWNER_ID)
            def fake_decode(_d): raise AssertionError("must not decode")
            async def fake_llm(*a, **k): raise AssertionError("must not call LLM")

            monkeypatch.setattr(reports_mod, "execute_query", fake_exec)
            monkeypatch.setattr(reports_mod, "_decode_file", fake_decode)
            monkeypatch.setattr(reports_mod, "call_llm", fake_llm)

            request = reports_mod.ReportAnalysisRequest(
                session_id=SESSION_ID, prompt="analyze",
                file_name="r.txt", mime_type="text/plain", data_base64="aGVsbG8=")
            with pytest.raises(HTTPException) as exc:
                await reports_mod.analyze_report(request, officer={"officer_id": INTRUDER_ID})
            assert exc.value.status_code == 404

        asyncio.run(scenario())

    def test_chat_rejects_intruder(self, monkeypatch):
        async def scenario():
            async def fake_exec(sql, params=()): return _rows_for(OWNER_ID)
            async def fake_pipeline(*a, **k): raise AssertionError("pipeline must not run")

            monkeypatch.setattr(chat_mod, "execute_query", fake_exec)
            monkeypatch.setattr(chat_mod, "run_pipeline", fake_pipeline)

            request = chat_mod.ChatRequest(question="how many?", session_id=SESSION_ID)
            with pytest.raises(HTTPException) as exc:
                await chat_mod.chat(request, officer={"officer_id": INTRUDER_ID})
            assert exc.value.status_code == 404

        asyncio.run(scenario())

    def test_chat_stream_rejects_intruder(self, monkeypatch):
        async def scenario():
            async def fake_exec(sql, params=()): return _rows_for(OWNER_ID)
            monkeypatch.setattr(chat_mod, "execute_query", fake_exec)
            with pytest.raises(HTTPException) as exc:
                await chat_mod.chat_stream(
                    question="how many?", session_id=SESSION_ID,
                    officer={"officer_id": INTRUDER_ID})
            assert exc.value.status_code == 404

        asyncio.run(scenario())

    def test_chat_stream_allows_new_session(self, monkeypatch):
        async def scenario():
            async def fake_exec(sql, params=()): return []
            monkeypatch.setattr(chat_mod, "execute_query", fake_exec)
            resp = await chat_mod.chat_stream(
                question="hi", session_id="sess-new", officer={"officer_id": OWNER_ID})
            assert resp.media_type == "text/event-stream"

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Session Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

from conversation import history as history_mod
from conversation import session_store as store_mod


class _FailingAsyncClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): raise RuntimeError("NoSQL disabled")
    async def __aexit__(self, *a): return False


@pytest.fixture
def force_in_memory(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FailingAsyncClient)
    store_mod._local_sessions.clear()
    history_mod._local_history.clear()
    yield
    store_mod._local_sessions.clear()
    history_mod._local_history.clear()


def _new_session_doc(session_id, officer_id, created_at):
    return {"id": session_id, "officer_id": officer_id, "title": store_mod._TITLE_FALLBACK,
            "created_at": created_at, "updated_at": created_at, "message_count": 0}


def _iso(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).isoformat()


class TestSessionLifecycle:
    def test_create_and_retrieve(self, force_in_memory):
        async def scenario():
            doc = _new_session_doc("sess-1", 1001, _iso(2024, 1, 15))
            await store_mod.create_session(doc)
            fetched = await store_mod.get_session("sess-1")
            assert fetched["id"] == "sess-1"
            sessions = await store_mod.list_sessions(1001)
            assert "sess-1" in [s["id"] for s in sessions]
        asyncio.run(scenario())

    def test_send_messages_updates_metadata(self, force_in_memory):
        async def scenario():
            await store_mod.create_session(_new_session_doc("sess-2", 1002, _iso(2024, 1, 1)))
            await history_mod.save_turn("sess-2", "question 1", "answer 1")
            await history_mod.save_turn("sess-2", "question 2", "answer 2")

            hist = await history_mod.get_history("sess-2")
            assert len(hist) == 4
            for msg in hist:
                assert msg.get("message_id")
                assert msg.get("timestamp")

            meta = await store_mod.get_session("sess-2")
            assert meta["message_count"] == 4
            assert meta["title"] != store_mod._TITLE_FALLBACK
        asyncio.run(scenario())

    def test_list_orders_by_updated_at_desc(self, force_in_memory):
        async def scenario():
            await store_mod.create_session(_new_session_doc("sess-a", 1004, _iso(2024, 3, 1)))
            await history_mod.save_turn("sess-a", "first", "answer")
            await asyncio.sleep(0.01)
            await store_mod.create_session(_new_session_doc("sess-b", 1004, _iso(2024, 3, 2)))
            await history_mod.save_turn("sess-b", "second", "answer")

            sessions = await store_mod.list_sessions(1004)
            ids = [s["id"] for s in sessions]
            assert ids.index("sess-b") < ids.index("sess-a")
        asyncio.run(scenario())

    def test_history_capped_at_max_turns(self, force_in_memory):
        async def scenario():
            await store_mod.create_session(_new_session_doc("sess-cap", 1005, _iso(2024, 4, 1)))
            for i in range(8):
                await history_mod.save_turn("sess-cap", f"q{i}", f"a{i}")
            hist = await history_mod.get_history("sess-cap")
            assert len(hist) == history_mod.MAX_TURNS
        asyncio.run(scenario())

    def test_persistence_across_reads(self, force_in_memory):
        async def scenario():
            await store_mod.create_session(_new_session_doc("sess-p", 1008, _iso(2024, 7, 1)))
            await history_mod.save_turn("sess-p", "remember this", "remembered")
            relisted = await store_mod.list_sessions(1008)
            assert "sess-p" in [s["id"] for s in relisted]
            hist = await history_mod.get_history("sess-p")
            assert hist[0]["content"] == "remember this"
        asyncio.run(scenario())
